"""Switch entities for the Grünbeck softliQ Cloud integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import (
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import GruenbeckConfigEntry
from .entity import GruenbeckEntity


@dataclass(frozen=True, kw_only=True)
class GruenbeckSwitchDescription(SwitchEntityDescription):
    """Describes a boolean parameter of the softliQ device."""

    parameter: str


SWITCHES: tuple[GruenbeckSwitchDescription, ...] = (
    GruenbeckSwitchDescription(
        key="dst_auto",
        translation_key="dst_auto",
        parameter="pdlstauto",
        entity_category=EntityCategory.CONFIG,
    ),
    GruenbeckSwitchDescription(
        key="buzzer",
        translation_key="buzzer",
        parameter="pbuzzer",
        entity_category=EntityCategory.CONFIG,
    ),
    GruenbeckSwitchDescription(
        key="email_notification",
        translation_key="email_notification",
        parameter="pallowemail",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
    GruenbeckSwitchDescription(
        key="push_notification",
        translation_key="push_notification",
        parameter="pallowpushnotification",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GruenbeckConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the switches for a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        GruenbeckSwitch(coordinator, description)
        for description in SWITCHES
    )


class GruenbeckSwitch(GruenbeckEntity, SwitchEntity):
    """A boolean parameter of the softliQ device."""

    entity_description: GruenbeckSwitchDescription

    def __init__(
        self,
        coordinator,
        description: GruenbeckSwitchDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return the state of the parameter."""
        value = self.coordinator.data.parameters.get(
            self.entity_description.parameter
        )
        return bool(value) if value is not None else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the parameter."""
        await self.coordinator.async_set_parameters(
            {self.entity_description.parameter: True}
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the parameter."""
        await self.coordinator.async_set_parameters(
            {self.entity_description.parameter: False}
        )
