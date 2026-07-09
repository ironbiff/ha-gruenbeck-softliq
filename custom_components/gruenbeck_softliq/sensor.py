"""Sensors for the Grünbeck softliQ Cloud integration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from homeassistant.components.sensor import (
    DOMAIN as SENSOR_DOMAIN,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfMass,
    UnitOfTime,
    UnitOfVolume,
    UnitOfVolumeFlowRate,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import GruenbeckConfigEntry, GruenbeckData
from .entity import GruenbeckEntity


@dataclass(frozen=True, kw_only=True)
class GruenbeckSensorDescription(SensorEntityDescription):
    """Describes a Grünbeck sensor."""

    value_fn: Callable[[GruenbeckData], StateType | datetime | date]
    exists_fn: Callable[[GruenbeckData], bool] = lambda data: True
    attributes_fn: Callable[[GruenbeckData], Mapping[str, Any] | None] = (
        lambda data: None
    )


def _realtime(key: str) -> Callable[[GruenbeckData], StateType]:
    return lambda data: data.realtime.get(key)


def _realtime_exists(key: str) -> Callable[[GruenbeckData], bool]:
    return lambda data: key in data.realtime


def _latest_measurement(kind: str) -> Callable[[GruenbeckData], StateType]:
    def _value(data: GruenbeckData) -> StateType:
        entries = getattr(data, kind)
        if not entries:
            return None
        latest = max(entries, key=lambda entry: str(entry.get("date", "")))
        return latest.get("value")

    return _value


def _as_timestamp(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    if (parsed := dt_util.parse_datetime(value)) is None:
        return None
    return dt_util.as_local(parsed)


def _as_date(value: Any) -> date | None:
    if not value or not isinstance(value, str):
        return None
    if parsed := dt_util.parse_datetime(value):
        return parsed.date()
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


SENSORS: tuple[GruenbeckSensorDescription, ...] = (
    # --- realtime values (websocket / realtime refresh) ---
    GruenbeckSensorDescription(
        key="mflow1",
        translation_key="flow_rate",
        native_unit_of_measurement=UnitOfVolumeFlowRate.CUBIC_METERS_PER_HOUR,
        device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_realtime("mflow1"),
    ),
    GruenbeckSensorDescription(
        key="mflow2",
        translation_key="flow_rate_2",
        native_unit_of_measurement=UnitOfVolumeFlowRate.CUBIC_METERS_PER_HOUR,
        device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_realtime("mflow2"),
        exists_fn=_realtime_exists("mflow2"),
    ),
    GruenbeckSensorDescription(
        key="mcountwater1",
        translation_key="soft_water_quantity",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=_realtime("mcountwater1"),
    ),
    GruenbeckSensorDescription(
        key="mcountwater2",
        translation_key="soft_water_quantity_2",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=_realtime("mcountwater2"),
        exists_fn=_realtime_exists("mcountwater2"),
    ),
    GruenbeckSensorDescription(
        key="mcountwatertank",
        translation_key="makeup_water_quantity",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_realtime("mcountwatertank"),
    ),
    GruenbeckSensorDescription(
        key="mrescapa1",
        translation_key="remaining_capacity_volume",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=_realtime("mrescapa1"),
    ),
    GruenbeckSensorDescription(
        key="mresidcap1",
        translation_key="remaining_capacity",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_realtime("mresidcap1"),
    ),
    GruenbeckSensorDescription(
        key="msaltrange",
        translation_key="salt_range",
        native_unit_of_measurement=UnitOfTime.DAYS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_realtime("msaltrange"),
    ),
    GruenbeckSensorDescription(
        key="msaltusage",
        translation_key="salt_usage_total",
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        device_class=SensorDeviceClass.WEIGHT,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=_realtime("msaltusage"),
    ),
    GruenbeckSensorDescription(
        key="mcountreg",
        translation_key="regeneration_counter",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_realtime("mcountreg"),
    ),
    GruenbeckSensorDescription(
        key="mregstatus",
        translation_key="regeneration_step",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_realtime("mregstatus"),
    ),
    GruenbeckSensorDescription(
        key="mregpercent1",
        translation_key="regeneration_progress",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_realtime("mregpercent1"),
    ),
    GruenbeckSensorDescription(
        key="mmaint",
        translation_key="next_maintenance",
        native_unit_of_measurement=UnitOfTime.DAYS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_realtime("mmaint"),
    ),
    GruenbeckSensorDescription(
        key="mhardsoftw",
        translation_key="soft_water_hardness",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="°dH",
        value_fn=_realtime("mhardsoftw"),
    ),
    # --- device information ---
    GruenbeckSensorDescription(
        key="next_regeneration",
        translation_key="next_regeneration",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: _as_timestamp(
            data.device.get("nextRegeneration")
        ),
    ),
    GruenbeckSensorDescription(
        key="startup",
        translation_key="startup_date",
        device_class=SensorDeviceClass.DATE,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: _as_date(data.device.get("startup")),
    ),
    # --- daily measurements ---
    GruenbeckSensorDescription(
        key="salt_daily",
        translation_key="salt_usage_daily",
        native_unit_of_measurement=UnitOfMass.GRAMS,
        device_class=SensorDeviceClass.WEIGHT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_latest_measurement("salt"),
        attributes_fn=lambda data: {"history": data.salt},
    ),
    GruenbeckSensorDescription(
        key="water_daily",
        translation_key="water_usage_daily",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_latest_measurement("water"),
        attributes_fn=lambda data: {"history": data.water},
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GruenbeckConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensors for a config entry."""
    coordinator = entry.runtime_data
    registry = er.async_get(hass)
    async_add_entities(
        GruenbeckSensor(coordinator, description)
        for description in SENSORS
        # Model-dependent entities (second exchanger) are created when the
        # device reports them or when they were registered before.
        if description.exists_fn(coordinator.data)
        or registry.async_get_entity_id(
            SENSOR_DOMAIN,
            DOMAIN,
            f"{coordinator.serial_number}_{description.key}",
        )
    )


class GruenbeckSensor(GruenbeckEntity, SensorEntity):
    """A sensor of the softliQ device."""

    entity_description: GruenbeckSensorDescription

    def __init__(
        self,
        coordinator,
        description: GruenbeckSensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType | datetime | date:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return additional attributes (e.g. measurement history)."""
        return self.entity_description.attributes_fn(self.coordinator.data)
