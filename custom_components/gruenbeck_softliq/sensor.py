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
from .coordinator import GruenbeckConfigEntry, GruenbeckData, hardness_unit
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


# The cloud only publishes a day's consumption once the day is (almost)
# over — there is no live value for the current day on this endpoint.
# These sensors therefore represent the most recent *completed* day; a
# live "today" value can be built with a daily utility_meter helper on
# top of the total counters.


def _daily_entry(data: GruenbeckData, kind: str) -> dict[str, Any] | None:
    """Return the most recent daily measurement entry."""
    entries = getattr(data, kind)
    if not entries:
        return None
    return max(entries, key=lambda entry: str(entry.get("date", "")))


def _daily_measurement(kind: str) -> Callable[[GruenbeckData], StateType]:
    def _value(data: GruenbeckData) -> StateType:
        entry = _daily_entry(data, kind)
        return entry.get("value") if entry else None

    return _value


def _daily_attributes(
    kind: str,
) -> Callable[[GruenbeckData], Mapping[str, Any] | None]:
    def _attributes(data: GruenbeckData) -> Mapping[str, Any] | None:
        entry = _daily_entry(data, kind)
        if entry is None:
            return None
        # Full history since commissioning is huge (years of entries);
        # keep a short window for dashboards.
        return {
            "date": entry.get("date"),
            "history": getattr(data, kind)[-14:],
        }

    return _attributes


def _as_timestamp(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    if (parsed := dt_util.parse_datetime(value)) is None:
        return None
    return dt_util.as_local(parsed)


def _latest_error(data: GruenbeckData) -> dict[str, Any] | None:
    """Return the most recent error entry from the device error list."""
    errors = [
        error
        for error in data.device.get("errors") or []
        if isinstance(error, dict)
    ]
    if not errors:
        return None
    return max(errors, key=lambda error: str(error.get("date", "")))


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
        entity_registry_enabled_default=False,
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
        entity_registry_enabled_default=False,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=_realtime("mcountwater2"),
        exists_fn=_realtime_exists("mcountwater2"),
    ),
    GruenbeckSensorDescription(
        key="mcountwatertank",
        translation_key="makeup_water_quantity",
        entity_registry_enabled_default=False,
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
        entity_registry_enabled_default=False,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_realtime("mcountreg"),
    ),
    GruenbeckSensorDescription(
        key="mregstatus",
        translation_key="regeneration_step",
        entity_registry_enabled_default=False,
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
        key="last_error",
        translation_key="last_error",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: (_latest_error(data) or {}).get("message"),
        attributes_fn=lambda data: (
            {
                "date": error.get("date"),
                "error_code": error.get("errorCode"),
                "type": error.get("type"),
                "is_resolved": error.get("isResolved"),
                "description": error.get("description"),
            }
            if (error := _latest_error(data))
            else None
        ),
    ),
    GruenbeckSensorDescription(
        key="startup",
        translation_key="startup_date",
        device_class=SensorDeviceClass.DATE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _as_date(data.device.get("startup")),
    ),
    GruenbeckSensorDescription(
        key="last_service",
        translation_key="last_service",
        device_class=SensorDeviceClass.DATE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: _as_date(data.device.get("lastService")),
    ),
    # --- daily measurements ---
    GruenbeckSensorDescription(
        key="salt_daily",
        translation_key="salt_usage_daily",
        native_unit_of_measurement=UnitOfMass.GRAMS,
        device_class=SensorDeviceClass.WEIGHT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_daily_measurement("salt"),
        attributes_fn=_daily_attributes("salt"),
    ),
    GruenbeckSensorDescription(
        key="water_daily",
        translation_key="water_usage_daily",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_daily_measurement("water"),
        attributes_fn=_daily_attributes("water"),
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
    added: set[str] = set()

    def _add_available_sensors() -> None:
        # Model-dependent entities (second exchanger) are created when
        # the device reports them — also later via websocket push — or
        # when they were registered before.
        new = [
            description
            for description in SENSORS
            if description.key not in added
            and (
                description.exists_fn(coordinator.data)
                or registry.async_get_entity_id(
                    SENSOR_DOMAIN,
                    DOMAIN,
                    f"{coordinator.serial_number}_{description.key}",
                )
            )
        ]
        if new:
            added.update(description.key for description in new)
            async_add_entities(
                GruenbeckSensor(coordinator, description)
                for description in new
            )

    _add_available_sensors()
    entry.async_on_unload(
        coordinator.async_add_listener(_add_available_sensors)
    )


class GruenbeckSensor(GruenbeckEntity, SensorEntity):
    """A sensor of the softliQ device."""

    entity_description: GruenbeckSensorDescription
    # Keep the measurement history window out of the recorder database.
    _unrecorded_attributes = frozenset({"history"})

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
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit, following the device's hardness unit setting."""
        if self.entity_description.key == "mhardsoftw":
            return hardness_unit(self.coordinator.data)
        return self.entity_description.native_unit_of_measurement

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return additional attributes (e.g. measurement history)."""
        return self.entity_description.attributes_fn(self.coordinator.data)
