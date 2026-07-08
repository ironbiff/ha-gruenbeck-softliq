"""Buttons for the Grünbeck softliQ Cloud integration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import (
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import GruenbeckCloudApi, GruenbeckError
from .coordinator import GruenbeckConfigEntry
from .entity import GruenbeckEntity


@dataclass(frozen=True, kw_only=True)
class GruenbeckButtonDescription(ButtonEntityDescription):
    """Describes a Grünbeck button."""

    press_fn: Callable[[GruenbeckCloudApi, str], Awaitable[None]]


BUTTONS: tuple[GruenbeckButtonDescription, ...] = (
    GruenbeckButtonDescription(
        key="regenerate",
        translation_key="regenerate",
        press_fn=lambda api, device_id: api.async_regenerate(device_id),
    ),
    GruenbeckButtonDescription(
        key="boost_mode",
        translation_key="boost_mode",
        press_fn=lambda api, device_id: api.async_activate_boost_mode(
            device_id
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GruenbeckConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the buttons for a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        GruenbeckButton(coordinator, description) for description in BUTTONS
    )


class GruenbeckButton(GruenbeckEntity, ButtonEntity):
    """A command button of the softliQ device."""

    entity_description: GruenbeckButtonDescription

    def __init__(
        self,
        coordinator,
        description: GruenbeckButtonDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        """Send the command to the device."""
        try:
            await self.entity_description.press_fn(
                self.coordinator.api, self.coordinator.device_id
            )
        except GruenbeckError as err:
            raise HomeAssistantError(
                f"Command {self.entity_description.key} failed: {err}"
            ) from err
