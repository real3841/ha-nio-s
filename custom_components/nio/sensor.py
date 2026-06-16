"""Sensors for the NIO integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfLength,
    UnitOfPower,
    UnitOfPressure,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .change_sensor import async_setup_entry as async_setup_change_entry
from .const import CONF_ENTRY_TYPE, DOOR_CLOSED, ENTRY_TYPE_VEHICLE
from .coordinator import NioConfigEntry, NioDataUpdateCoordinator
from .entity import NioEntity
from .vehicle_data import (
    BATTERY_PACKS,
    CHARGE_STATES,
    HEAT_LEVELS,
    alerts_as_attributes,
    battery_pack,
    charge_state,
    compute_alerts,
    full_charge_range_km,
    heat_level,
    maintenance_detail,
    meta_root,
    problem_alert_count,
    status_root,
)


def _section(data: dict[str, Any], section: str, key: str) -> Any:
    value = (data.get(section) or {}).get(key)
    return value


def _achievement_rate(data: dict[str, Any]) -> float | None:
    soc = data.get("soc_status") or {}
    cltc = soc.get("remaining_range")
    actual = soc.get("remaining_actual_range")
    if not cltc or actual is None:
        return None
    return round(actual / cltc * 100, 1)


def _full_charge_range(data: dict[str, Any]) -> int | None:
    soc = status_root(data).get("soc_status") or {}
    return full_charge_range_km(soc.get("remaining_range"), soc.get("soc"))


def _battery_pack_type(data: dict[str, Any]) -> str:
    return battery_pack(_full_charge_range(data))


def _checked_in_days(data: dict[str, Any]) -> int | None:
    checked_in = meta_root(data).get("checked_in") or {}
    days = checked_in.get("days")
    return int(days) if days is not None else None


def _heat_max(data: dict[str, Any], *fields: str) -> str:
    heating = status_root(data).get("heating_status") or {}
    level = max(int(heating.get(field) or 0) for field in fields)
    return heat_level(level)


@dataclass(frozen=True, kw_only=True)
class NioSensorDescription(SensorEntityDescription):
    """Sensor description with a value extractor."""

    value_fn: Callable[[dict[str, Any]], Any]


SENSORS: tuple[NioSensorDescription, ...] = (
    # --- parity with the old YAML setup ---
    NioSensorDescription(
        key="battery",
        translation_key="battery",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda d: _section(d, "soc_status", "soc"),
    ),
    NioSensorDescription(
        key="remaining_range",
        translation_key="remaining_range",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        icon="mdi:map-marker-distance",
        value_fn=lambda d: _section(d, "soc_status", "remaining_range"),
    ),
    NioSensorDescription(
        key="remaining_actual_range",
        translation_key="remaining_actual_range",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        icon="mdi:map-marker-distance",
        value_fn=lambda d: _section(d, "soc_status", "remaining_actual_range"),
    ),
    NioSensorDescription(
        key="range_achievement_rate",
        translation_key="range_achievement_rate",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:percent-circle",
        value_fn=_achievement_rate,
    ),
    NioSensorDescription(
        key="vehicle_state",
        translation_key="vehicle_state",
        device_class=SensorDeviceClass.ENUM,
        options=["driving", "parked", "resting", "unknown"],
        value_fn=lambda d: {1: "driving", 2: "parked", 3: "resting"}.get(
            _section(d, "exterior_status", "vehicle_state"), "unknown"
        ),
    ),
    # --- extended: energy / charging ---
    NioSensorDescription(
        key="charging_power",
        translation_key="charging_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        value_fn=lambda d: _section(d, "soc_status", "charging_power"),
    ),
    # --- extended: climate ---
    NioSensorDescription(
        key="inside_temperature",
        translation_key="inside_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda d: _section(d, "hvac_status", "temperature"),
    ),
    NioSensorDescription(
        key="outside_temperature",
        translation_key="outside_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda d: _section(d, "hvac_status", "outside_temperature"),
    ),
    # --- extended: odometer ---
    NioSensorDescription(
        key="mileage",
        translation_key="mileage",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        icon="mdi:counter",
        value_fn=lambda d: _section(d, "exterior_status", "mileage"),
    ),
    # --- extended: tyres (diagnostic) ---
    *(
        NioSensorDescription(
            key=f"tyre_pressure_{corner}",
            translation_key=f"tyre_pressure_{corner}",
            device_class=SensorDeviceClass.PRESSURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfPressure.BAR,
            entity_category=EntityCategory.DIAGNOSTIC,
            icon="mdi:car-tire-alert",
            value_fn=(
                lambda field: lambda d: _section(d, "tyre_status", field)
            )(f"{corner}_wheel_press_bar"),
        )
        for corner in ("front_left", "front_right", "rear_left", "rear_right")
    ),
    # --- extended: firmware (diagnostic) ---
    NioSensorDescription(
        key="fota_version",
        translation_key="fota_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:cellphone-arrow-down",
        value_fn=lambda d: _section(d, "fota_status", "current_version"),
    ),
    # --- dashboard: charging / battery pack ---
    NioSensorDescription(
        key="charge_state",
        translation_key="charge_state",
        device_class=SensorDeviceClass.ENUM,
        options=list(CHARGE_STATES),
        icon="mdi:ev-station",
        value_fn=lambda d: charge_state(_section(status_root(d), "soc_status", "charge_state")),
    ),
    NioSensorDescription(
        key="full_charge_range",
        translation_key="full_charge_range",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        icon="mdi:battery-charging-high",
        value_fn=_full_charge_range,
    ),
    NioSensorDescription(
        key="battery_pack",
        translation_key="battery_pack",
        device_class=SensorDeviceClass.ENUM,
        options=list(BATTERY_PACKS),
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:battery",
        value_fn=_battery_pack_type,
    ),
    NioSensorDescription(
        key="checked_in_days",
        translation_key="checked_in_days",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:calendar-check",
        value_fn=_checked_in_days,
    ),
    # --- dashboard: heating ---
    NioSensorDescription(
        key="steer_wheel_heat",
        translation_key="steer_wheel_heat",
        device_class=SensorDeviceClass.ENUM,
        options=list(HEAT_LEVELS),
        icon="mdi:steering",
        value_fn=lambda d: heat_level(
            _section(status_root(d), "heating_status", "steer_wheel_heat_sts")
        ),
    ),
    NioSensorDescription(
        key="seat_heat_front",
        translation_key="seat_heat_front",
        device_class=SensorDeviceClass.ENUM,
        options=list(HEAT_LEVELS),
        icon="mdi:car-seat-heater",
        value_fn=lambda d: _heat_max(
            d, "seat_heat_frnt_le_sts", "seat_heat_frnt_ri_sts"
        ),
    ),
    NioSensorDescription(
        key="seat_heat_rear",
        translation_key="seat_heat_rear",
        device_class=SensorDeviceClass.ENUM,
        options=list(HEAT_LEVELS),
        icon="mdi:car-seat-heater",
        value_fn=lambda d: _heat_max(d, "seat_heat_re_le_sts", "seat_heat_re_ri_sts"),
    ),
    NioSensorDescription(
        key="seat_ventilation",
        translation_key="seat_ventilation",
        device_class=SensorDeviceClass.ENUM,
        options=list(HEAT_LEVELS),
        icon="mdi:fan",
        value_fn=lambda d: _heat_max(
            d,
            "seat_vent_frnt_le_sts",
            "seat_vent_frnt_ri_sts",
            "seat_vent_re_le_sts",
            "seat_vent_re_ri_sts",
        ),
    ),
    NioSensorDescription(
        key="maintenance",
        translation_key="maintenance",
        icon="mdi:wrench",
        value_fn=maintenance_detail,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NioConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    await async_setup_change_entry(hass, entry, async_add_entities)
    if entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_VEHICLE) != ENTRY_TYPE_VEHICLE:
        return
    coordinator = entry.runtime_data
    async_add_entities(
        [NioAlertsSensor(coordinator)]
        + [NioSensor(coordinator, description) for description in SENSORS]
    )


class NioSensor(NioEntity, SensorEntity):
    """A coordinator-backed NIO sensor."""

    entity_description: NioSensorDescription

    def __init__(
        self,
        coordinator: NioDataUpdateCoordinator,
        description: NioSensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)


class NioAlertsSensor(NioEntity, SensorEntity):
    """Active alert count with the full alert list in attributes."""

    _attr_translation_key = "alerts"
    _attr_icon = "mdi:alert-circle-outline"
    _attr_native_unit_of_measurement = "alerts"

    def __init__(self, coordinator: NioDataUpdateCoordinator) -> None:
        super().__init__(coordinator, "alerts")

    @property
    def native_value(self) -> int:
        return problem_alert_count(compute_alerts(self.coordinator.data))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        alerts = compute_alerts(self.coordinator.data)
        return {
            "items": alerts_as_attributes(alerts),
            "summary": alerts[0].title if len(alerts) == 1 else None,
        }
