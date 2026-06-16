"""Sensors for NIO service-order / battery-swap history."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .change_coordinator import NioChangeConfigEntry, NioChangeDataUpdateCoordinator
from .change_data import ServiceSummary, extract_orders
from .change_entity import NioChangeEntity
from .const import CONF_CHANGE_METHOD, CONF_ENTRY_TYPE, ENTRY_TYPE_CHANGE


def _summary(coordinator: NioChangeDataUpdateCoordinator) -> ServiceSummary | None:
    return coordinator.summary


@dataclass(frozen=True, kw_only=True)
class NioChangeSensorDescription(SensorEntityDescription):
    """Sensor description with a value extractor from ServiceSummary."""

    value_fn: Callable[[ServiceSummary | None], Any]


CHANGE_SENSORS: tuple[NioChangeSensorDescription, ...] = (
    NioChangeSensorDescription(
        key="service_orders_total",
        translation_key="service_orders_total",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:clipboard-list-outline",
        value_fn=lambda s: s.total if s else None,
    ),
    NioChangeSensorDescription(
        key="swap_completed",
        translation_key="swap_completed",
        state_class=SensorStateClass.TOTAL,
        icon="mdi:battery-sync",
        value_fn=lambda s: s.swap_completed if s else None,
    ),
    NioChangeSensorDescription(
        key="swap_cancelled",
        translation_key="swap_cancelled",
        state_class=SensorStateClass.TOTAL,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:battery-off",
        value_fn=lambda s: s.swap_cancelled if s else None,
    ),
    NioChangeSensorDescription(
        key="swap_spent",
        translation_key="swap_spent",
        state_class=SensorStateClass.TOTAL,
        icon="mdi:cash",
        value_fn=lambda s: s.swap_spent if s else None,
    ),
    NioChangeSensorDescription(
        key="swap_avg_spent",
        translation_key="swap_avg_spent",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:cash-multiple",
        value_fn=lambda s: s.swap_avg_spent if s else None,
    ),
    NioChangeSensorDescription(
        key="upgrade_completed",
        translation_key="upgrade_completed",
        state_class=SensorStateClass.TOTAL,
        icon="mdi:battery-arrow-up",
        value_fn=lambda s: s.upgrade_completed if s else None,
    ),
    NioChangeSensorDescription(
        key="upgrade_spent",
        translation_key="upgrade_spent",
        state_class=SensorStateClass.TOTAL,
        icon="mdi:cash-plus",
        value_fn=lambda s: s.upgrade_spent if s else None,
    ),
    NioChangeSensorDescription(
        key="last_service_order",
        translation_key="last_service_order",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-outline",
        value_fn=lambda s: (
            datetime.fromtimestamp(s.last_order_time / 1000, tz=UTC)
            if s and s.last_order_time
            else None
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NioChangeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_CHANGE:
        return
    coordinator = entry.runtime_data
    async_add_entities(
        NioChangeSensor(coordinator, description) for description in CHANGE_SENSORS
    )


class NioChangeSensor(NioChangeEntity, SensorEntity):
    """A coordinator-backed service-order sensor."""

    entity_description: NioChangeSensorDescription

    def __init__(
        self,
        coordinator: NioChangeDataUpdateCoordinator,
        description: NioChangeSensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        if description.key in ("swap_spent", "swap_avg_spent", "upgrade_spent"):
            self._attr_device_class = SensorDeviceClass.MONETARY
            self._attr_native_unit_of_measurement = "CNY"
            self._attr_suggested_display_precision = 2

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(_summary(self.coordinator))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key != "service_orders_total":
            return None
        payload = self.coordinator.data or {}
        orders = extract_orders(payload)
        meta = getattr(self.coordinator.client, "last_meta", {}) or {}
        entry = self.coordinator.config_entry
        return {
            "api_result_code": payload.get("resultCode") or payload.get("result_code"),
            "api_result_desc": payload.get("resultDesc") or payload.get("result_desc"),
            "raw_order_count": len(orders),
            "swap_order_count": sum(
                1 for o in orders if o.get("orderType") == "pe_shaman_change"
            ),
            "http_status": meta.get("http_status"),
            "http_method": meta.get("method")
            or entry.data.get(CONF_CHANGE_METHOD, "POST"),
            "has_result_data": any(
                isinstance(payload.get(key), dict) for key in ("resultData", "result_data")
            ),
        }
