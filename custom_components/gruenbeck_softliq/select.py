"""Select entities for the Grünbeck softliQ Cloud integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.select import (
    SelectEntity,
    SelectEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import OPERATION_MODES
from .coordinator import GruenbeckConfigEntry
from .entity import GruenbeckEntity

# Weekday modes (used while the main mode is "individual") only allow
# Eco/Comfort/Power — "individual" itself is not a per-day option.
DAY_MODES = {
    mode: option
    for mode, option in OPERATION_MODES.items()
    if option != "individual"
}


@dataclass(frozen=True, kw_only=True)
class GruenbeckSelectDescription(SelectEntityDescription):
    """Describes a mode parameter of the softliQ device."""

    parameter: str
    modes: dict[int, str]


SELECTS: tuple[GruenbeckSelectDescription, ...] = (
    GruenbeckSelectDescription(
        key="operation_mode",
        translation_key="operation_mode",
        parameter="pmode",
        modes=OPERATION_MODES,
        entity_category=EntityCategory.CONFIG,
    ),
    *(
        GruenbeckSelectDescription(
            key=f"operation_mode_{day}",
            translation_key=f"operation_mode_{day}",
            parameter=parameter,
            modes=DAY_MODES,
            entity_category=EntityCategory.CONFIG,
        )
        for day, parameter in (
            ("monday", "pmodemo"),
            ("tuesday", "pmodetu"),
            ("wednesday", "pmodewe"),
            ("thursday", "pmodeth"),
            ("friday", "pmodefr"),
            ("saturday", "pmodesa"),
            ("sunday", "pmodesu"),
        )
    ),
    GruenbeckSelectDescription(
        key="hardness_unit",
        translation_key="hardness_unit",
        parameter="phunit",
        modes={1: "dh", 2: "fh"},
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
    GruenbeckSelectDescription(
        key="regeneration_mode",
        translation_key="regeneration_mode",
        parameter="pregmode",
        modes={0: "automatic", 1: "fixed"},
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GruenbeckConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the select entities for a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        GruenbeckSelect(coordinator, description) for description in SELECTS
    )


class GruenbeckSelect(GruenbeckEntity, SelectEntity):
    """An operating-mode parameter of the softliQ device."""

    entity_description: GruenbeckSelectDescription

    def __init__(
        self,
        coordinator,
        description: GruenbeckSelectDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._attr_options = list(description.modes.values())
        self._mode_by_option = {
            option: mode for mode, option in description.modes.items()
        }

    @property
    def current_option(self) -> str | None:
        """Return the currently active mode."""
        mode = self.coordinator.data.parameters.get(
            self.entity_description.parameter
        )
        try:
            return self.entity_description.modes.get(int(mode))
        except (TypeError, ValueError):
            return None

    async def async_select_option(self, option: str) -> None:
        """Change the mode parameter."""
        await self.coordinator.async_set_parameters(
            {self.entity_description.parameter: self._mode_by_option[option]}
        )
