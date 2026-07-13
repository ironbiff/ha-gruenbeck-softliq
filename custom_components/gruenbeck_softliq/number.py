"""Number entities for the Grünbeck softliQ Cloud integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import GruenbeckConfigEntry, hardness_unit
from .entity import GruenbeckEntity

# Conversion factor between German and French hardness degrees.
_DH_TO_FH = 1.79


@dataclass(frozen=True, kw_only=True)
class GruenbeckNumberDescription(NumberEntityDescription):
    """Describes a writable Grünbeck parameter."""

    parameter: str
    # Hardness values follow the unit configured on the device.
    hardness: bool = False


NUMBERS: tuple[GruenbeckNumberDescription, ...] = (
    GruenbeckNumberDescription(
        key="raw_water_hardness",
        translation_key="raw_water_hardness",
        parameter="prawhard",
        hardness=True,
        native_min_value=1,
        native_max_value=45,
        native_step=1,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    ),
    GruenbeckNumberDescription(
        key="soft_water_hardness_setpoint",
        translation_key="soft_water_hardness_setpoint",
        parameter="psetsoft",
        hardness=True,
        native_min_value=0,
        native_max_value=15,
        native_step=1,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    ),
    GruenbeckNumberDescription(
        key="forced_regeneration_interval",
        translation_key="forced_regeneration_interval",
        parameter="pforcedregdist",
        entity_registry_enabled_default=False,
        native_min_value=1,
        native_max_value=14,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.DAYS,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    ),
    GruenbeckNumberDescription(
        key="maintenance_interval",
        translation_key="maintenance_interval",
        parameter="pmaintint",
        entity_registry_enabled_default=False,
        native_min_value=1,
        native_max_value=730,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.DAYS,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    ),
    GruenbeckNumberDescription(
        key="residual_capacity_limit",
        translation_key="residual_capacity_limit",
        parameter="prescaplimit",
        entity_registry_enabled_default=False,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    ),
    GruenbeckNumberDescription(
        key="led_brightness",
        translation_key="led_brightness",
        parameter="pledbright",
        entity_registry_enabled_default=False,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.SLIDER,
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
        GruenbeckNumber(coordinator, description) for description in NUMBERS
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
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit, following the device's hardness setting."""
        if self.entity_description.hardness:
            return hardness_unit(self.coordinator.data)
        return self.entity_description.native_unit_of_measurement

    @property
    def native_max_value(self) -> float:
        """Return the maximum, scaled for French hardness degrees."""
        maximum = self.entity_description.native_max_value
        if (
            self.entity_description.hardness
            and hardness_unit(self.coordinator.data) == "°fH"
        ):
            return round(maximum * _DH_TO_FH)
        return maximum

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
        await self.coordinator.async_set_parameters(
            {
                self.entity_description.parameter: (
                    int(value) if value.is_integer() else value
                )
            }
        )
