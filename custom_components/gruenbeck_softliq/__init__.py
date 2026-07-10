"""The Grünbeck softliQ Cloud integration."""

from __future__ import annotations

import aiohttp

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import (
    GruenbeckCloudApi,
    GruenbeckError,
    GruenbeckInvalidCredentials,
)
from .coordinator import GruenbeckConfigEntry, GruenbeckCoordinator

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TIME,
]


async def async_setup_entry(
    hass: HomeAssistant, entry: GruenbeckConfigEntry
) -> bool:
    """Set up Grünbeck softliQ Cloud from a config entry."""
    # The B2C login cookies are managed manually because Grünbeck uses
    # cookie names (e.g. "x-ms-cpim-cache|...") that aiohttp's cookie jar
    # rejects; the jar would strip them and break the login on
    # aiohttp >= 3.12, so it is disabled entirely.
    session = async_create_clientsession(
        hass, cookie_jar=aiohttp.DummyCookieJar()
    )
    api = GruenbeckCloudApi(
        session, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD]
    )

    try:
        devices = await api.async_get_devices()
    except GruenbeckInvalidCredentials as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except GruenbeckError as err:
        # Transient cloud problems (throttling, changed login page,
        # gateway errors) are retried instead of forcing a re-auth.
        raise ConfigEntryNotReady(str(err)) from err

    if not devices:
        raise ConfigEntryNotReady("No softliQ devices found in this account")

    # One coordinator per account entry; softliQ accounts typically hold
    # a single device, we use the first one (like the mobile app).
    coordinator = GruenbeckCoordinator(hass, entry, api, devices[0])
    await coordinator.async_load_daily()
    await coordinator.async_config_entry_first_refresh()
    coordinator.start_websocket()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(
    hass: HomeAssistant, entry: GruenbeckConfigEntry
) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: GruenbeckConfigEntry
) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS
    ):
        await entry.runtime_data.async_shutdown()
    return unload_ok
