"""Time entity for the fixed regeneration time."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import GruenbeckConfigEntry
from .entity import GruenbeckEntity

# The device stores three regeneration time slots per weekday; the app
# manages a single fixed time, which maps to slot 1 of every weekday.
_REG_TIME_PARAMETERS = (
    "pregmo1",
    "pregtu1",
    "pregwe1",
    "pregth1",
    "pregfr1",
    "pregsa1",
    "pregsu1",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GruenbeckConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the time entities for a config entry."""
    async_add_entities([GruenbeckRegenerationTime(entry.runtime_data)])


class GruenbeckRegenerationTime(GruenbeckEntity, TimeEntity):
    """The fixed regeneration time (used when the mode is 'fixed')."""

    _attr_translation_key = "regeneration_time"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "regeneration_time")

    @property
    def native_value(self) -> time | None:
        """Return the configured time (Monday slot 1)."""
        value = self.coordinator.data.parameters.get(_REG_TIME_PARAMETERS[0])
        if not isinstance(value, str) or ":" not in value:
            return None
        try:
            return time.fromisoformat(value)
        except ValueError:
            # "--:--" means no time is set.
            return None

    async def async_set_value(self, value: time) -> None:
        """Write the time to slot 1 of every weekday, like the app."""
        hhmm = value.strftime("%H:%M")
        await self.coordinator.async_set_parameters(
            {parameter: hhmm for parameter in _REG_TIME_PARAMETERS}
        )
