"""Data update coordinator for the Grünbeck softliQ Cloud integration."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util

from .api import (
    GruenbeckAuthError,
    GruenbeckCloudApi,
    GruenbeckConnectionError,
    GruenbeckError,
    GruenbeckInvalidCredentials,
)
from .const import (
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEVICE_INFO_INTERVAL,
    DOMAIN,
    EMPTY_RETRY_INTERVAL,
    MEASUREMENTS_INTERVAL,
    MIN_SCAN_INTERVAL,
    PARAMETERS_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

# Delay between full-login retries of the websocket after an auth error;
# hammering the B2C login is what gets accounts blocked by Grünbeck.
_WS_AUTH_RETRY = 900

type GruenbeckConfigEntry = ConfigEntry[GruenbeckCoordinator]


@dataclass
class GruenbeckData:
    """Container for all data of one softliQ device."""

    device: dict[str, Any] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    realtime: dict[str, Any] = field(default_factory=dict)
    salt: list[dict[str, Any]] = field(default_factory=list)
    water: list[dict[str, Any]] = field(default_factory=list)
    # Consumption since local midnight, tracked against the total
    # counters: {"date": iso, "baselines": {...}, "today": {...}}.
    daily: dict[str, Any] = field(default_factory=dict)


def hardness_unit(data: GruenbeckData) -> str:
    """Return the hardness unit configured on the device (1=°dH, 2=°fH)."""
    return "°fH" if data.device.get("unit") == 2 else "°dH"


class GruenbeckCoordinator(DataUpdateCoordinator[GruenbeckData]):
    """Coordinates polling and websocket push updates for one device."""

    config_entry: GruenbeckConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: GruenbeckConfigEntry,
        api: GruenbeckCloudApi,
        device: dict[str, Any],
    ) -> None:
        scan_interval = max(
            entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            MIN_SCAN_INTERVAL,
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {device.get('id')}",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.api = api
        self.device_id: str = device["id"]
        self.serial_number: str = str(
            device.get("serialNumber") or self.device_id
        ).replace("/", "_")
        self._initial_device = device
        # Per-endpoint fetch bookkeeping: key -> (last fetch, had data).
        # Empty cloud answers are retried after EMPTY_RETRY_INTERVAL
        # instead of the full interval.
        self._fetch_state: dict[str, tuple[float, bool]] = {}
        self._ws_task: asyncio.Task | None = None
        # Midnight baselines for the built-in "consumption today"
        # sensors, persisted across restarts.
        self._store: Store[dict[str, Any]] = Store(
            hass, 1, f"{DOMAIN}.daily_{entry.entry_id}"
        )
        self._loaded_daily: dict[str, Any] = {}

    async def async_load_daily(self) -> None:
        """Load the persisted daily-consumption baselines."""
        self._loaded_daily = await self._store.async_load() or {}

    def _fetch_due(self, key: str, interval: int, now: float) -> bool:
        """Whether an endpoint is due for a fetch."""
        last, had_data = self._fetch_state.get(key, (0.0, False))
        due_after = (
            interval if had_data else min(interval, EMPTY_RETRY_INTERVAL)
        )
        return now - last >= due_after

    async def _async_update_data(self) -> GruenbeckData:
        """Poll the cloud API."""
        data = self.data or GruenbeckData(
            device=self._initial_device, daily=self._loaded_daily
        )
        now = time.monotonic()

        try:
            # Keep the device in realtime mode so the websocket keeps
            # pushing values, and pull a fresh snapshot.
            await self.api.async_realtime(self.device_id, "enter")
            if snapshot := await self.api.async_realtime(
                self.device_id, "refresh"
            ):
                self._merge_realtime(data.realtime, snapshot)

            if self._fetch_due("device", DEVICE_INFO_INTERVAL, now):
                device = await self.api.async_get_device(self.device_id)
                if device:
                    data.device = device
                self._fetch_state["device"] = (now, bool(device))

            if self._fetch_due("parameters", PARAMETERS_INTERVAL, now):
                parameters = await self.api.async_get_parameters(
                    self.device_id
                )
                if parameters:
                    data.parameters = parameters
                self._fetch_state["parameters"] = (now, bool(parameters))

            for kind in ("salt", "water"):
                if self._fetch_due(kind, MEASUREMENTS_INTERVAL, now):
                    measurements = await self.api.async_get_measurements(
                        self.device_id, kind
                    )
                    if measurements:
                        setattr(data, kind, measurements)
                    self._fetch_state[kind] = (now, bool(measurements))
        except GruenbeckInvalidCredentials as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except GruenbeckError as err:
            raise UpdateFailed(str(err)) from err

        self._update_daily(data)
        return data

    # Total counters feeding the "consumption today" sensors.
    _DAILY_COUNTERS = {"water": "mcountwater1", "salt": "msaltusage"}

    def _update_daily(self, data: GruenbeckData) -> bool:
        """Track consumption since local midnight; return True on change."""
        daily = data.daily
        today = dt_util.now().date().isoformat()
        changed = False
        if daily.get("date") != today:
            daily.clear()
            daily.update({"date": today, "baselines": {}, "today": {}})
            changed = True
        for key, source in self._DAILY_COUNTERS.items():
            value = data.realtime.get(source)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            baseline = daily["baselines"].get(key)
            if baseline is None or value < baseline:
                # Start of day (or the cloud counter was reset).
                daily["baselines"][key] = baseline = value
                changed = True
            consumed = round(value - baseline, 3)
            if daily["today"].get(key) != consumed:
                daily["today"][key] = consumed
                changed = True
        if changed:
            self._store.async_delay_save(lambda: dict(data.daily), 60)
        return changed

    async def async_set_parameters(self, updates: dict[str, Any]) -> None:
        """Write device parameters and update local state."""
        try:
            await self.api.async_set_parameters(self.device_id, updates)
        except GruenbeckError as err:
            raise HomeAssistantError(
                f"Setting {', '.join(updates)} failed: {err}"
            ) from err
        # The cloud applies writes asynchronously; show the new values
        # right away and let the periodic parameters poll reconcile.
        self.data.parameters.update(updates)
        self.async_update_listeners()

    @staticmethod
    def _merge_realtime(
        target: dict[str, Any], update: dict[str, Any]
    ) -> bool:
        """Merge a realtime snapshot / push message; return True on change."""
        changed = False
        for key, value in update.items():
            if (
                isinstance(value, (str, int, float, bool))
                and target.get(key) != value
            ):
                target[key] = value
                changed = True
        return changed

    # ------------------------------------------------------------------
    # Websocket handling
    # ------------------------------------------------------------------

    def start_websocket(self) -> None:
        """Start the background websocket listener."""
        if self._ws_task is None or self._ws_task.done():
            self._ws_task = self.config_entry.async_create_background_task(
                self.hass,
                self._websocket_loop(),
                name=f"{DOMAIN}_websocket_{self.serial_number}",
            )

    async def async_shutdown(self) -> None:
        """Stop the websocket and tell the device to leave realtime mode."""
        if self._ws_task is not None:
            self._ws_task.cancel()
            self._ws_task = None
        if self.data and self.data.daily:
            await self._store.async_save(dict(self.data.daily))
        try:
            await self.api.async_realtime(self.device_id, "leave")
        except GruenbeckError:
            _LOGGER.debug("Could not leave realtime mode on shutdown")
        await super().async_shutdown()

    async def _websocket_loop(self) -> None:
        """Keep the websocket connected, reconnecting with backoff."""
        backoff = 5
        while True:
            try:
                await self.api.async_listen_websocket(self._handle_ws_message)
                backoff = 5
            except GruenbeckInvalidCredentials:
                _LOGGER.warning(
                    "Websocket stopped: the Grünbeck cloud rejected the"
                    " credentials; waiting for re-authentication"
                )
                return
            except GruenbeckAuthError as err:
                # A full login retry on every reconnect would hammer the
                # B2C endpoint; back off far more aggressively.
                _LOGGER.debug("Websocket auth error: %s", err)
                await asyncio.sleep(_WS_AUTH_RETRY)
                continue
            except GruenbeckConnectionError as err:
                _LOGGER.debug("Websocket error: %s", err)
            _LOGGER.debug("Websocket reconnect in %s seconds", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 300)

    def _handle_ws_message(self, message: dict[str, Any]) -> None:
        """Handle a pushed realtime update."""
        # Messages carry the device id; ignore pushes of other devices.
        msg_id = str(message.get("id", ""))
        if msg_id and msg_id not in (self.device_id, self.serial_number):
            return
        if self.data is None:
            return
        merged = self._merge_realtime(self.data.realtime, message)
        daily_changed = self._update_daily(self.data)
        if merged or daily_changed:
            # async_update_listeners (unlike async_set_updated_data) does
            # not reset the poll schedule, so the realtime keep-alive
            # keeps firing every scan interval even during push bursts.
            self.async_update_listeners()
