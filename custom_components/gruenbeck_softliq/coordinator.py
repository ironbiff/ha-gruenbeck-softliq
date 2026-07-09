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
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import (
    GruenbeckAuthError,
    GruenbeckCloudApi,
    GruenbeckConnectionError,
)
from .const import (
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEVICE_INFO_INTERVAL,
    DOMAIN,
    MEASUREMENTS_INTERVAL,
    MIN_SCAN_INTERVAL,
    PARAMETERS_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

type GruenbeckConfigEntry = ConfigEntry[GruenbeckCoordinator]


@dataclass
class GruenbeckData:
    """Container for all data of one softliQ device."""

    device: dict[str, Any] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    realtime: dict[str, Any] = field(default_factory=dict)
    salt: list[dict[str, Any]] = field(default_factory=list)
    water: list[dict[str, Any]] = field(default_factory=list)


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
        self._last_device_fetch = 0.0
        self._last_parameters_fetch = 0.0
        self._last_measurements_fetch = 0.0
        self._ws_task: asyncio.Task | None = None

    async def _async_update_data(self) -> GruenbeckData:
        """Poll the cloud API."""
        data = self.data or GruenbeckData(device=self._initial_device)
        now = time.monotonic()

        try:
            # Keep the device in realtime mode so the websocket keeps
            # pushing values, and pull a fresh snapshot.
            await self.api.async_realtime(self.device_id, "enter")
            if snapshot := await self.api.async_realtime(
                self.device_id, "refresh"
            ):
                self._merge_realtime(data.realtime, snapshot)

            # Only stamp the fetch time when the cloud returned data, so
            # an empty answer is retried on the next cycle instead of
            # after the full interval.
            if now - self._last_device_fetch >= DEVICE_INFO_INTERVAL:
                if device := await self.api.async_get_device(self.device_id):
                    data.device = device
                    self._last_device_fetch = now

            if now - self._last_parameters_fetch >= PARAMETERS_INTERVAL:
                if parameters := await self.api.async_get_parameters(
                    self.device_id
                ):
                    data.parameters = parameters
                    self._last_parameters_fetch = now

            if now - self._last_measurements_fetch >= MEASUREMENTS_INTERVAL:
                salt = await self.api.async_get_measurements(
                    self.device_id, "salt"
                )
                water = await self.api.async_get_measurements(
                    self.device_id, "water"
                )
                data.salt = salt or data.salt
                data.water = water or data.water
                if salt or water:
                    self._last_measurements_fetch = now
        except GruenbeckAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except GruenbeckConnectionError as err:
            raise UpdateFailed(str(err)) from err

        return data

    async def async_refresh_parameters(self) -> None:
        """Re-read the parameters (after a write) and notify entities."""
        try:
            self.data.parameters = await self.api.async_get_parameters(
                self.device_id
            )
            self._last_parameters_fetch = time.monotonic()
        except GruenbeckConnectionError as err:
            _LOGGER.warning("Could not refresh parameters: %s", err)
        self.async_update_listeners()

    @staticmethod
    def _merge_realtime(
        target: dict[str, Any], update: dict[str, Any]
    ) -> None:
        """Merge a realtime snapshot / push message into the state."""
        for key, value in update.items():
            if isinstance(value, (str, int, float, bool)):
                target[key] = value

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
        try:
            await self.api.async_realtime(self.device_id, "leave")
        except (GruenbeckAuthError, GruenbeckConnectionError):
            _LOGGER.debug("Could not leave realtime mode on shutdown")
        await super().async_shutdown()

    async def _websocket_loop(self) -> None:
        """Keep the websocket connected, reconnecting with backoff."""
        backoff = 5
        while True:
            try:
                await self.api.async_listen_websocket(self._handle_ws_message)
                backoff = 5
            except GruenbeckAuthError:
                _LOGGER.debug("Websocket auth failed, retrying after login")
            except GruenbeckConnectionError as err:
                _LOGGER.debug("Websocket error: %s", err)
            except asyncio.CancelledError:
                raise
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
        self._merge_realtime(self.data.realtime, message)
        self.async_set_updated_data(self.data)
