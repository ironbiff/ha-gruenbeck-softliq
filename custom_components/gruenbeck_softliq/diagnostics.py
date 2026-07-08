"""Diagnostics support for the Grünbeck softliQ Cloud integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .coordinator import GruenbeckConfigEntry

TO_REDACT = {
    CONF_PASSWORD,
    CONF_USERNAME,
    "id",
    "serialNumber",
    "name",
    "location",
    "owner",
    "email",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: GruenbeckConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "data": async_redact_data(asdict(coordinator.data), TO_REDACT),
    }
