"""Number entities for the Grünbeck softliQ Cloud integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import GruenbeckError
from .coordinator import GruenbeckConfigEntry
from .entity import GruenbeckEntity


@dataclass(frozen=True, kw_only=True)
class GruenbeckNumberDescription(NumberEntityDescription):
    """Describes a writable Grünbeck parameter."""

    parameter: str


NUMBERS: tuple[GruenbeckNumberDescription, ...] = (
    GruenbeckNumberDescription(
        key="raw_water_hardness",
        translation_key="raw_water_hardness",
        parameter="prawhard",
        native_min_value=1,
        native_max_value=45,
        native_step=1,
        native_unit_of_measurement="°dH",
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    ),
    GruenbeckNumberDescription(
        key="soft_water_hardness_setpoint",
        translation_key="soft_water_hardness_setpoint",
        parameter="psetsoft",
        native_min_value=0,
        native_max_value=15,
        native_step=1,
        native_unit_of_measurement="°dH",
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GruenbeckConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the number entities for a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        GruenbeckNumber(coordinator, description)
        for description in NUMBERS
        if description.parameter in coordinator.data.parameters
    )


class GruenbeckNumber(GruenbeckEntity, NumberEntity):
    """A writable numeric parameter of the softliQ device."""

    entity_description: GruenbeckNumberDescription

    def __init__(
        self,
        coordinator,
        description: GruenbeckNumberDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        """Return the current parameter value."""
        value = self.coordinator.data.parameters.get(
            self.entity_description.parameter
        )
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        """Write the parameter to the device."""
        parameter = self.entity_description.parameter
        try:
            await self.coordinator.api.async_set_parameters(
                self.coordinator.device_id,
                {parameter: int(value) if value.is_integer() else value},
            )
        except GruenbeckError as err:
            raise HomeAssistantError(
                f"Setting {parameter} failed: {err}"
            ) from err
        self.coordinator.data.parameters[parameter] = value
        await self.coordinator.async_refresh_parameters()
