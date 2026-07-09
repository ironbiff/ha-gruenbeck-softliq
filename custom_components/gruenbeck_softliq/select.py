"""Select entities for the Grünbeck softliQ Cloud integration."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import OPERATION_MODES
from .coordinator import GruenbeckConfigEntry
from .entity import GruenbeckEntity

MODE_BY_OPTION = {option: mode for mode, option in OPERATION_MODES.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GruenbeckConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the select entities for a config entry."""
    coordinator = entry.runtime_data
    async_add_entities([GruenbeckOperationModeSelect(coordinator)])


class GruenbeckOperationModeSelect(GruenbeckEntity, SelectEntity):
    """The operating mode (Eco / Comfort / Power / Individual)."""

    _attr_translation_key = "operation_mode"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(OPERATION_MODES.values())

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "operation_mode")

    @property
    def current_option(self) -> str | None:
        """Return the currently active mode."""
        mode = self.coordinator.data.parameters.get("pmode")
        try:
            return OPERATION_MODES.get(int(mode))
        except (TypeError, ValueError):
            return None

    async def async_select_option(self, option: str) -> None:
        """Change the operating mode."""
        await self.coordinator.async_set_parameter(
            "pmode", MODE_BY_OPTION[option]
        )
