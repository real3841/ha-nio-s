"""Binary sensors for the NIO integration.

Door/window are aggregate checks across all openings — fixes the silently
broken YAML templates that referenced non-existent ``door_front_left_status``
fields (live API returns ``door_ajar_front_left_status``).

Field semantics (field-tested 2026-06-06 — all 5 openings cycled one by one,
12-step sequence matched 1:1 against raw API captures):
- ``*_ajar_status``: 1 = closed, 0 = open
- ``vehicle_lock_status``: 1 = locked, 0 = unlocked
- ``win_*_posn``: 0 = closed, >0 = open position (carried over from the
  legacy YAML templates; field names unchanged)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOOR_AJAR_FIELDS, DOOR_CLOSED, LOCK_LOCKED, WINDOW_POSN_FIELDS
from .const import CONF_ENTRY_TYPE, ENTRY_TYPE_VEHICLE
from .coordinator import NioConfigEntry, NioDataUpdateCoordinator
from .entity import NioEntity
from .vehicle_data import has_problem_alert, meta_root, mode_active, status_root


def _any_door_open(data: dict[str, Any]) -> bool | None:
    doors = data.get("door_status") or {}
    values = [doors.get(f) for f in DOOR_AJAR_FIELDS]
    if all(v is None for v in values):
        return None
    # 0 = open (field-tested); anything that isn't "closed" counts as open.
    return any(v is not None and v != DOOR_CLOSED for v in values)


def _any_window_open(data: dict[str, Any]) -> bool | None:
    windows = data.get("window_status") or {}
    values = [windows.get(f) for f in WINDOW_POSN_FIELDS]
    if all(v is None for v in values):
        return None
    return any(v not in (None, 0) for v in values)


def _is_driving(data: dict[str, Any]) -> bool | None:
    state = (data.get("exterior_status") or {}).get("vehicle_state")
    return None if state is None else state == 1


def _is_sleeping(data: dict[str, Any]) -> bool | None:
    exterior = data.get("exterior_status") or {}
    state = exterior.get("vehicle_state")
    if state is None:
        return None
    return state != 1 and exterior.get("comf_ena", 0) != 1


def _is_unlocked(data: dict[str, Any]) -> bool | None:
    lock = (data.get("door_status") or {}).get("vehicle_lock_status")
    # device_class LOCK: on = unlocked
    return None if lock is None else lock != LOCK_LOCKED


def _is_charging(data: dict[str, Any]) -> bool | None:
    state = (data.get("soc_status") or {}).get("charge_state")
    return None if state is None else state != 0


def _is_connected(data: dict[str, Any]) -> bool | None:
    return (data.get("connection_status") or {}).get("connected")


def _is_adc_offline(data: dict[str, Any]) -> bool | None:
    adc = (status_root(data).get("connection_status") or {}).get("adc_connected")
    return None if adc is None else not adc


def _is_cdc_connected(data: dict[str, Any]) -> bool | None:
    return (status_root(data).get("connection_status") or {}).get("cdc_connected")


def _battery_critical(data: dict[str, Any]) -> bool | None:
    soc = (status_root(data).get("soc_status") or {}).get("soc")
    return None if soc is None else float(soc) < 10


def _battery_low(data: dict[str, Any]) -> bool | None:
    soc = (status_root(data).get("soc_status") or {}).get("soc")
    if soc is None:
        return None
    soc_f = float(soc)
    return 10 <= soc_f < 20


def _maintenance_due(data: dict[str, Any]) -> bool | None:
    maintain = status_root(data).get("maintain_status") or {}
    status = maintain.get("maintain_status")
    if status is None:
        return None
    items = maintain.get("current_maintenance_list") or []
    return int(status) >= 1 and bool(items)


def _server_alarm(data: dict[str, Any]) -> bool | None:
    alarm = meta_root(data).get("alarm")
    if alarm is None:
        return None
    return bool(isinstance(alarm, list) and len(alarm) > 0)


def _air_conditioner_on(data: dict[str, Any]) -> bool | None:
    return (status_root(data).get("hvac_status") or {}).get("air_conditioner_on")


def _door_open(data: dict[str, Any], field: str) -> bool | None:
    value = (status_root(data).get("door_status") or {}).get(field)
    if value is None:
        return None
    return value != DOOR_CLOSED


def _offcar_mode(data: dict[str, Any], field: str, *, defender: bool = False) -> bool | None:
    value = (status_root(data).get("offcar_mode_status") or {}).get(field)
    if value is None:
        return None
    if defender:
        return int(value) >= 2
    return mode_active(value)


@dataclass(frozen=True, kw_only=True)
class NioBinarySensorDescription(BinarySensorEntityDescription):
    """Binary sensor description with a value extractor."""

    value_fn: Callable[[dict[str, Any]], bool | None]


BINARY_SENSORS: tuple[NioBinarySensorDescription, ...] = (
    NioBinarySensorDescription(
        key="driving",
        translation_key="driving",
        device_class=BinarySensorDeviceClass.MOVING,
        value_fn=_is_driving,
    ),
    NioBinarySensorDescription(
        key="sleeping",
        translation_key="sleeping",
        icon="mdi:sleep",
        value_fn=_is_sleeping,
    ),
    NioBinarySensorDescription(
        key="door",
        translation_key="door",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=_any_door_open,
    ),
    NioBinarySensorDescription(
        key="window",
        translation_key="window",
        device_class=BinarySensorDeviceClass.WINDOW,
        value_fn=_any_window_open,
    ),
    NioBinarySensorDescription(
        key="lock",
        translation_key="lock",
        device_class=BinarySensorDeviceClass.LOCK,
        value_fn=_is_unlocked,
    ),
    NioBinarySensorDescription(
        key="charging",
        translation_key="charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        value_fn=_is_charging,
    ),
    NioBinarySensorDescription(
        key="connected",
        translation_key="connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_is_connected,
    ),
    NioBinarySensorDescription(
        key="alert_active",
        translation_key="alert_active",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:alert",
        value_fn=has_problem_alert,
    ),
    NioBinarySensorDescription(
        key="battery_critical",
        translation_key="battery_critical",
        device_class=BinarySensorDeviceClass.BATTERY,
        icon="mdi:battery-alert",
        value_fn=_battery_critical,
    ),
    NioBinarySensorDescription(
        key="battery_low",
        translation_key="battery_low",
        device_class=BinarySensorDeviceClass.BATTERY,
        icon="mdi:battery-low",
        value_fn=_battery_low,
    ),
    NioBinarySensorDescription(
        key="adc_offline",
        translation_key="adc_offline",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:car-connected",
        value_fn=_is_adc_offline,
    ),
    NioBinarySensorDescription(
        key="cdc_connected",
        translation_key="cdc_connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_is_cdc_connected,
    ),
    NioBinarySensorDescription(
        key="maintenance_due",
        translation_key="maintenance_due",
        icon="mdi:wrench-clock",
        value_fn=_maintenance_due,
    ),
    NioBinarySensorDescription(
        key="server_alarm",
        translation_key="server_alarm",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:bell-alert",
        value_fn=_server_alarm,
    ),
    NioBinarySensorDescription(
        key="air_conditioner",
        translation_key="air_conditioner",
        icon="mdi:air-conditioner",
        value_fn=_air_conditioner_on,
    ),
    NioBinarySensorDescription(
        key="hood",
        translation_key="hood",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=lambda d: _door_open(d, "engine_hood_ajar_status"),
    ),
    NioBinarySensorDescription(
        key="tailgate",
        translation_key="tailgate",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=lambda d: _door_open(d, "tailgate_ajar_status"),
    ),
    NioBinarySensorDescription(
        key="charge_port",
        translation_key="charge_port",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=lambda d: _door_open(d, "second_charge_port_ajar_status"),
    ),
    NioBinarySensorDescription(
        key="pet_mode",
        translation_key="pet_mode",
        icon="mdi:dog",
        value_fn=lambda d: _offcar_mode(d, "pet_mode"),
    ),
    NioBinarySensorDescription(
        key="power_hold_mode",
        translation_key="power_hold_mode",
        icon="mdi:power-plug",
        value_fn=lambda d: _offcar_mode(d, "power_hold_mode"),
    ),
    NioBinarySensorDescription(
        key="camping_mode",
        translation_key="camping_mode",
        icon="mdi:tent",
        value_fn=lambda d: _offcar_mode(d, "camping_mode"),
    ),
    NioBinarySensorDescription(
        key="defender_mode",
        translation_key="defender_mode",
        icon="mdi:shield-car",
        value_fn=lambda d: _offcar_mode(d, "defender_mode", defender=True),
    ),
    NioBinarySensorDescription(
        key="remote_video",
        translation_key="remote_video",
        icon="mdi:video",
        value_fn=lambda d: _offcar_mode(d, "remote_video"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NioConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    if entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_VEHICLE) != ENTRY_TYPE_VEHICLE:
        return
    coordinator = entry.runtime_data
    async_add_entities(
        NioBinarySensor(coordinator, description)
        for description in BINARY_SENSORS
    )


class NioBinarySensor(NioEntity, BinarySensorEntity):
    """A coordinator-backed NIO binary sensor."""

    entity_description: NioBinarySensorDescription

    def __init__(
        self,
        coordinator: NioDataUpdateCoordinator,
        description: NioBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.coordinator.data)
