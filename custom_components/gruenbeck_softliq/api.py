"""Async client for the Grünbeck myGrünbeck cloud API.

The protocol was reverse engineered from the myGrünbeck mobile app; the
implementation follows the flow used by the ioBroker.gruenbeck adapter
(https://github.com/TA2k/ioBroker.gruenbeck):

1. Azure AD B2C login with PKCE (authorize -> SelfAsserted -> confirmed
   -> token endpoint) using the credentials of the myGrünbeck account.
2. REST API at prod-eu-gruenbeck-api.azurewebsites.net for device info,
   parameters, measurements and commands (regenerate / boost).
3. A SignalR websocket that pushes realtime values while the device is
   in "realtime" mode (entered/kept alive via the realtime endpoints).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import re
import secrets
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

import aiohttp

from .const import (
    API_BASE,
    API_VERSION,
    APP_USER_AGENT,
    B2C_AUTHORIZE_URL,
    B2C_CLIENT_ID,
    B2C_HOST,
    B2C_REDIRECT_URI,
    B2C_SCOPE,
    SIGNALR_NEGOTIATE_URL,
    SIGNALR_WS_URL,
)

_LOGGER = logging.getLogger(__name__)

_SIGNALR_RECORD_SEPARATOR = "\x1e"

# Give the cloud a generous timeout; the Azure functions occasionally
# take several seconds to spin up.
_TIMEOUT = aiohttp.ClientTimeout(total=30)


class GruenbeckError(Exception):
    """Base error for the Grünbeck cloud client."""


class GruenbeckAuthError(GruenbeckError):
    """Authentication with the Grünbeck cloud failed."""


class GruenbeckInvalidCredentials(GruenbeckAuthError):
    """The Grünbeck cloud explicitly rejected the username/password."""


class GruenbeckConnectionError(GruenbeckError):
    """Communication with the Grünbeck cloud failed."""


def _pkce_pair() -> tuple[str, str]:
    """Return a PKCE (code_verifier, code_challenge) pair."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def _setting(page: str, key: str) -> str:
    """Extract a value from the SETTINGS blob of the B2C login page."""
    match = re.search(rf'"{key}":\s*"([^"]*)"', page)
    if not match:
        raise GruenbeckAuthError(f"Could not find '{key}' in B2C login page")
    return match.group(1)


def _cookie_header(response: aiohttp.ClientResponse) -> str:
    """Build a Cookie header from the Set-Cookie headers of a response."""
    cookies = [
        raw.split(";")[0]
        for raw in response.headers.getall("Set-Cookie", [])
        if raw
    ]
    return "; ".join(cookies)


class GruenbeckCloudApi:
    """Client for the Grünbeck cloud REST API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
    ) -> None:
        self._session = session
        self._username = username
        self._password = password

        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._token_expires: float = 0.0
        self._tenant: str | None = None
        self._auth_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Authentication (Azure AD B2C)
    # ------------------------------------------------------------------

    async def login(self) -> None:
        """Perform the full B2C login flow with username/password."""
        verifier, challenge = _pkce_pair()

        authorize_params = {
            "client_id": B2C_CLIENT_ID,
            "redirect_uri": B2C_REDIRECT_URI,
            "response_type": "code",
            "scope": B2C_SCOPE,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "client_info": "1",
            "haschrome": "1",
            "x-client-SKU": "MSAL.iOS",
            "x-client-Ver": "0.8.0",
            "x-client-OS": "14.3",
            "x-client-CPU": "64",
            "x-client-DM": "iPhone",
            "x-app-name": "Grünbeck",
            "x-app-ver": "1.2.1",
            "state": secrets.token_urlsafe(16),
        }

        try:
            # Step 1: fetch the login page to obtain CSRF token,
            # transaction id, policy and tenant.
            async with self._session.get(
                B2C_AUTHORIZE_URL,
                params=authorize_params,
                headers={
                    "Accept": (
                        "text/html,application/xhtml+xml,application/xml;"
                        "q=0.9,*/*;q=0.8"
                    ),
                    "Accept-Language": "de-de",
                    "User-Agent": APP_USER_AGENT,
                },
                timeout=_TIMEOUT,
            ) as resp:
                page = await resp.text()
                cookie = _cookie_header(resp)

            csrf = _setting(page, "csrf")
            trans_id = _setting(page, "transId")
            policy = _setting(page, "policy")
            self._tenant = _setting(page, "tenant")

            # Step 2: submit the credentials.
            async with self._session.post(
                f"{B2C_HOST}{self._tenant}/SelfAsserted",
                params={"tx": trans_id, "p": policy},
                data={
                    "request_type": "RESPONSE",
                    "signInName": self._username,
                    "password": self._password,
                },
                headers={
                    "X-CSRF-TOKEN": csrf,
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "Origin": B2C_HOST,
                    "Cookie": cookie,
                    "User-Agent": APP_USER_AGENT,
                },
                timeout=_TIMEOUT,
            ) as resp:
                body = await resp.text()
                cookie = _cookie_header(resp) + f"; x-ms-cpim-csrf={csrf}"

            # Only a parsed JSON answer with status != 200 means the
            # credentials were rejected; anything else (HTML error page,
            # changed login flow) is a flow failure, not a wrong password.
            try:
                result = json.loads(body)
            except json.JSONDecodeError as err:
                raise GruenbeckAuthError(
                    "Unexpected (non-JSON) login response; the Grünbeck"
                    f" login flow may have changed: {body[:120]!r}"
                ) from err
            if not isinstance(result, dict):
                raise GruenbeckAuthError(
                    f"Unexpected login response format: {body[:120]!r}"
                )
            if str(result.get("status")) != "200":
                raise GruenbeckInvalidCredentials(
                    "Grünbeck cloud rejected the credentials: "
                    f"{result.get('message') or body[:200]}"
                )

            # Step 3: confirm the login; the redirect carries the
            # authorization code.
            async with self._session.get(
                f"{B2C_HOST}{self._tenant}"
                "/api/CombinedSigninAndSignup/confirmed",
                params={"csrf_token": csrf, "tx": trans_id, "p": policy},
                headers={
                    "Accept": (
                        "text/html,application/xhtml+xml,application/xml;"
                        "q=0.9,*/*;q=0.8"
                    ),
                    "Accept-Language": "de-de",
                    "Cookie": cookie,
                    "User-Agent": APP_USER_AGENT,
                },
                allow_redirects=False,
                timeout=_TIMEOUT,
            ) as resp:
                location = resp.headers.get("Location", "")
                body = await resp.text()

            code = self._extract_code(location, body)

            # Step 4: exchange the authorization code for tokens.
            await self._token_request(
                {
                    "client_id": B2C_CLIENT_ID,
                    "client_info": "1",
                    "scope": B2C_SCOPE,
                    "grant_type": "authorization_code",
                    "code": code,
                    "code_verifier": verifier,
                    "redirect_uri": B2C_REDIRECT_URI,
                }
            )
        except GruenbeckError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise GruenbeckConnectionError(f"Login failed: {err}") from err

        _LOGGER.debug("Grünbeck cloud login successful")

    @staticmethod
    def _extract_code(location: str, body: str) -> str:
        """Extract the authorization code from the confirm response."""
        if "code=" in location:
            query = parse_qs(urlparse(location).query)
            if code := query.get("code", [""])[0]:
                return code
        # Fallback: the HTML body contains an urlencoded redirect link
        # ("...code%3d<code>...>here</a>"), like the mobile app parses it.
        if (start := body.find("code%3d")) != -1:
            end = body.find(">here", start)
            if end != -1:
                return body[start + len("code%3d") : end - 1]
        # Surface the B2C error (e.g. access_denied) for diagnosis; the
        # location only contains an error description here, no secrets.
        query = parse_qs(urlparse(location).query)
        detail = (
            query.get("error_description", query.get("error", ["unknown"]))[0]
        )
        raise GruenbeckAuthError(
            f"No authorization code received (B2C answer: {detail})"
        )

    async def _token_request(self, data: dict[str, str]) -> None:
        """Call the B2C token endpoint and store the tokens."""
        if not self._tenant:
            raise GruenbeckAuthError("Not logged in (missing tenant)")
        async with self._session.post(
            f"{B2C_HOST}{self._tenant}/oauth2/v2.0/token",
            data=data,
            headers={
                "Accept": "application/json",
                "User-Agent": APP_USER_AGENT,
            },
            timeout=_TIMEOUT,
        ) as resp:
            try:
                payload = await resp.json(content_type=None)
            except ValueError as err:  # includes json.JSONDecodeError
                raise GruenbeckConnectionError(
                    f"Token endpoint returned invalid JSON (HTTP {resp.status})"
                ) from err
        if resp.status >= 400 or "access_token" not in payload:
            raise GruenbeckAuthError(
                f"Token request failed: {payload.get('error_description', payload)}"
            )
        self._access_token = payload["access_token"]
        self._refresh_token = payload.get(
            "refresh_token", self._refresh_token
        )
        expires_in = int(payload.get("expires_in", 3600))
        # Renew a few minutes early.
        self._token_expires = time.monotonic() + expires_in - 300

    async def async_ensure_token(self) -> str:
        """Return a valid access token, refreshing or re-logging in."""
        async with self._auth_lock:
            if self._access_token and time.monotonic() < self._token_expires:
                return self._access_token
            if self._refresh_token:
                try:
                    await self._token_request(
                        {
                            "client_id": B2C_CLIENT_ID,
                            "client_info": "1",
                            "scope": B2C_SCOPE,
                            "grant_type": "refresh_token",
                            "refresh_token": self._refresh_token,
                        }
                    )
                    return self._access_token  # type: ignore[return-value]
                except GruenbeckError:
                    _LOGGER.debug(
                        "Token refresh failed, performing full login"
                    )
                    self._refresh_token = None
            await self.login()
            if not self._access_token:
                raise GruenbeckAuthError("Login did not yield a token")
            return self._access_token

    # ------------------------------------------------------------------
    # REST API
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        json_data: Any | None = None,
        retry_auth: bool = True,
    ) -> Any:
        """Perform an authenticated request against the device API."""
        token = await self.async_ensure_token()
        # Device ids contain a slash (e.g. "softliq.d/BSxxxxxxxx") that
        # must stay part of the URL path.
        url = f"{API_BASE}/{path}?api-version={API_VERSION}"
        try:
            async with self._session.request(
                method,
                url,
                json=json_data,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "de-de",
                    "User-Agent": APP_USER_AGENT,
                    "cache-control": "no-cache",
                },
                timeout=_TIMEOUT,
            ) as resp:
                if resp.status in (401, 403) and retry_auth:
                    _LOGGER.debug(
                        "Got HTTP %s from %s, refreshing session",
                        resp.status,
                        path,
                    )
                    self._token_expires = 0.0
                    return await self._request(
                        method, path, json_data, retry_auth=False
                    )
                if resp.status in (401, 403):
                    raise GruenbeckAuthError(
                        f"Unauthorized ({resp.status}) for {path}"
                    )
                if resp.status >= 400:
                    raise GruenbeckConnectionError(
                        f"HTTP {resp.status} for {path}: {await resp.text()}"
                    )
                if resp.status == 204 or not (text := await resp.text()):
                    return None
                try:
                    return json.loads(text)
                except json.JSONDecodeError as err:
                    raise GruenbeckConnectionError(
                        f"Invalid JSON from {path}: {text[:120]!r}"
                    ) from err
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise GruenbeckConnectionError(
                f"Request {method} {path} failed: {err}"
            ) from err

    async def async_get_devices(self) -> list[dict[str, Any]]:
        """Return all softliQ devices of the account."""
        devices = await self._request("GET", "devices") or []
        return [
            device
            for device in devices
            if "soft" in str(device.get("id", "")).lower()
        ]

    async def async_get_device(self, device_id: str) -> dict[str, Any]:
        """Return the device details (incl. next regeneration, errors)."""
        return await self._request("GET", f"devices/{device_id}") or {}

    async def async_get_parameters(self, device_id: str) -> dict[str, Any]:
        """Return the device parameters (settings)."""
        return await self._request("GET", f"devices/{device_id}/parameters") or {}

    async def async_set_parameters(
        self, device_id: str, parameters: dict[str, Any]
    ) -> None:
        """Change device parameters (e.g. raw water hardness, mode)."""
        await self._request(
            "PATCH", f"devices/{device_id}/parameters", json_data=parameters
        )

    async def async_get_measurements(
        self, device_id: str, kind: str
    ) -> list[dict[str, Any]]:
        """Return daily measurements; kind is 'salt' or 'water'."""
        result = await self._request(
            "GET", f"devices/{device_id}/measurements/{kind}"
        )
        return result if isinstance(result, list) else []

    async def async_regenerate(self, device_id: str) -> None:
        """Start a manual regeneration."""
        await self._request(
            "POST", f"devices/{device_id}/regenerate", json_data={}
        )

    async def async_activate_boost_mode(self, device_id: str) -> None:
        """Activate the boost mode."""
        await self._request(
            "POST", f"devices/{device_id}/activate-boost-mode", json_data={}
        )

    async def async_realtime(
        self, device_id: str, action: str
    ) -> dict[str, Any] | None:
        """Call a realtime endpoint; action is enter/refresh/leave."""
        result = await self._request(
            "POST", f"devices/{device_id}/realtime/{action}", json_data={}
        )
        return result if isinstance(result, dict) else None

    # ------------------------------------------------------------------
    # SignalR websocket (push updates)
    # ------------------------------------------------------------------

    async def async_ws_negotiate(self) -> tuple[str, str]:
        """Negotiate a websocket session; returns (connection_id, token)."""
        token = await self.async_ensure_token()
        headers = {
            "Content-Type": "text/plain;charset=UTF-8",
            "Origin": "file://",
            "Accept": "*/*",
            "User-Agent": APP_USER_AGENT,
            "X-Requested-With": "XMLHttpRequest",
        }
        try:
            async with self._session.get(
                f"{API_BASE}/realtime/negotiate",
                headers={**headers, "Authorization": f"Bearer {token}"},
                timeout=_TIMEOUT,
            ) as resp:
                if resp.status >= 400:
                    raise GruenbeckConnectionError(
                        f"Realtime negotiate failed: HTTP {resp.status}"
                    )
                ws_token = (await resp.json(content_type=None))["accessToken"]

            async with self._session.post(
                SIGNALR_NEGOTIATE_URL,
                data=b"",
                headers={**headers, "Authorization": f"Bearer {ws_token}"},
                timeout=_TIMEOUT,
            ) as resp:
                if resp.status >= 400:
                    raise GruenbeckConnectionError(
                        f"SignalR negotiate failed: HTTP {resp.status}"
                    )
                connection_id = (await resp.json(content_type=None))[
                    "connectionId"
                ]
        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
            ValueError,  # includes json.JSONDecodeError
            KeyError,
        ) as err:
            raise GruenbeckConnectionError(
                f"Websocket negotiation failed: {err}"
            ) from err
        return connection_id, ws_token

    async def async_listen_websocket(
        self, callback: Callable[[dict[str, Any]], None]
    ) -> None:
        """Connect to the SignalR hub and forward pushed device data.

        Runs until the connection closes or an error occurs; the caller
        is responsible for reconnecting.
        """
        connection_id, ws_token = await self.async_ws_negotiate()
        url = (
            f"{SIGNALR_WS_URL}&id={quote(connection_id)}"
            f"&access_token={quote(ws_token)}"
        )
        try:
            async with self._session.ws_connect(
                url,
                headers={
                    "Origin": "null",
                    "User-Agent": (
                        "Mozilla/5.0 (iPhone; CPU iPhone OS 14_2 like"
                        " Mac OS X) AppleWebKit/605.1.15 (KHTML, like"
                        " Gecko) Mobile/15E148"
                    ),
                },
                heartbeat=55,
            ) as ws:
                # SignalR protocol handshake.
                await ws.send_str(
                    '{"protocol":"json","version":1}'
                    + _SIGNALR_RECORD_SEPARATOR
                )
                _LOGGER.debug("Grünbeck websocket connected")
                async for msg in ws:
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        break
                    for record in msg.data.split(_SIGNALR_RECORD_SEPARATOR):
                        if not record:
                            continue
                        try:
                            message = json.loads(record)
                        except json.JSONDecodeError:
                            _LOGGER.debug(
                                "Ignoring invalid websocket record: %s",
                                record,
                            )
                            continue
                        msg_type = message.get("type")
                        if msg_type == 6:  # ping
                            await ws.send_str(
                                '{"type":6}' + _SIGNALR_RECORD_SEPARATOR
                            )
                        elif msg_type == 7:  # close
                            _LOGGER.debug(
                                "Websocket close requested: %s",
                                message.get("error"),
                            )
                            return
                        for argument in message.get("arguments") or []:
                            if isinstance(argument, dict):
                                callback(argument)
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise GruenbeckConnectionError(
                f"Websocket connection failed: {err}"
            ) from err
