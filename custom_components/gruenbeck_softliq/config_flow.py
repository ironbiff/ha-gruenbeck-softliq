"""Config flow for the Grünbeck softliQ Cloud integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    GruenbeckAuthError,
    GruenbeckCloudApi,
    GruenbeckConnectionError,
    GruenbeckInvalidCredentials,
)
from .const import (
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)
from .coordinator import GruenbeckConfigEntry

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL)
        ),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
)


class GruenbeckConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow for a myGrünbeck account."""

    VERSION = 1

    async def _async_validate(
        self, username: str, password: str
    ) -> tuple[dict[str, str], list[dict[str, Any]]]:
        """Try to log in and list devices; returns (errors, devices)."""
        # DummyCookieJar: see comment in __init__.async_setup_entry.
        session = async_create_clientsession(
            self.hass, cookie_jar=aiohttp.DummyCookieJar()
        )
        api = GruenbeckCloudApi(session, username, password)
        try:
            devices = await api.async_get_devices()
        except GruenbeckInvalidCredentials as err:
            _LOGGER.warning("Grünbeck login rejected: %s", err)
            return {"base": "invalid_auth"}, []
        except GruenbeckAuthError as err:
            _LOGGER.warning("Grünbeck login flow failed: %s", err)
            return {"base": "login_flow_failed"}, []
        except GruenbeckConnectionError as err:
            _LOGGER.warning("Grünbeck cloud not reachable: %s", err)
            return {"base": "cannot_connect"}, []
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error during login")
            return {"base": "unknown"}, []
        finally:
            await session.close()
        return {}, devices

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step (account credentials)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            await self.async_set_unique_id(username.lower())
            self._abort_if_unique_id_configured()

            errors, devices = await self._async_validate(
                username, user_input[CONF_PASSWORD]
            )
            if not errors and not devices:
                return self.async_abort(reason="no_devices_found")
            if not errors:
                return self.async_create_entry(
                    title=devices[0].get("name") or username,
                    data={
                        CONF_USERNAME: username,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, user_input
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle re-authentication after the password changed."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the new password."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()
        if user_input is not None:
            errors, _ = await self._async_validate(
                reauth_entry.data[CONF_USERNAME],
                user_input[CONF_PASSWORD],
            )
            if not errors:
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    )
                }
            ),
            description_placeholders={
                CONF_USERNAME: reauth_entry.data[CONF_USERNAME]
            },
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: GruenbeckConfigEntry,
    ) -> GruenbeckOptionsFlow:
        """Return the options flow."""
        return GruenbeckOptionsFlow()


class GruenbeckOptionsFlow(OptionsFlow):
    """Options for the Grünbeck softliQ Cloud integration."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL,
                            max=3600,
                            step=10,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="s",
                        )
                    )
                }
            ),
        )
