"""Binary sensors for the Grünbeck softliQ Cloud integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import GruenbeckConfigEntry, GruenbeckData
from .entity import GruenbeckEntity


@dataclass(frozen=True, kw_only=True)
class GruenbeckBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a Grünbeck binary sensor."""

    value_fn: Callable[[GruenbeckData], bool | None]
    exists_fn: Callable[[GruenbeckData], bool] = lambda data: True


def _regeneration_active(data: GruenbeckData) -> bool | None:
    status = data.realtime.get("mregstatus")
    if status is None:
        return None
    try:
        return int(status) != 0
    except (TypeError, ValueError):
        return None


BINARY_SENSORS: tuple[GruenbeckBinarySensorDescription, ...] = (
    GruenbeckBinarySensorDescription(
        key="has_error",
        translation_key="has_error",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.device.get("hasError"),
        exists_fn=lambda data: "hasError" in data.device,
    ),
    GruenbeckBinarySensorDescription(
        key="regeneration_active",
        translation_key="regeneration_active",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=_regeneration_active,
        exists_fn=lambda data: "mregstatus" in data.realtime,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GruenbeckConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensors for a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        GruenbeckBinarySensor(coordinator, description)
        for description in BINARY_SENSORS
        if description.exists_fn(coordinator.data)
    )


class GruenbeckBinarySensor(GruenbeckEntity, BinarySensorEntity):
    """A binary sensor of the softliQ device."""

    entity_description: GruenbeckBinarySensorDescription

    def __init__(
        self,
        coordinator,
        description: GruenbeckBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return the state of the binary sensor."""
        return self.entity_description.value_fn(self.coordinator.data)
