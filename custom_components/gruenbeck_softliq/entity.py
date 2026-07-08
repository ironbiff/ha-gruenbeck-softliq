"""Base entity for the Grünbeck softliQ Cloud integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import GruenbeckCoordinator


class GruenbeckEntity(CoordinatorEntity[GruenbeckCoordinator]):
    """Common base for all Grünbeck softliQ entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: GruenbeckCoordinator, key: str) -> None:
        super().__init__(coordinator)
        device = coordinator.data.device
        self._attr_unique_id = f"{coordinator.serial_number}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.serial_number)},
            manufacturer="Grünbeck",
            model=device.get("name") or "softliQ",
            name=device.get("name") or "Grünbeck softliQ",
            serial_number=device.get("serialNumber"),
            sw_version=device.get("softwareVersion"),
            configuration_url="https://www.mygruenbeck.de/",
        )
