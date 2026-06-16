"""Refresh button for the NIO service-order config entry."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .change_coordinator import NioChangeConfigEntry, NioChangeDataUpdateCoordinator
from .change_data import extract_orders
from .change_entity import NioChangeEntity
from .const import CONF_ENTRY_TYPE, ENTRY_TYPE_CHANGE

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NioChangeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_CHANGE:
        return
    async_add_entities([NioChangeRefreshButton(entry.runtime_data)])


class NioChangeRefreshButton(NioChangeEntity, ButtonEntity):
    """Trigger an immediate poll of the service-order API."""

    _attr_translation_key = "refresh_change"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: NioChangeDataUpdateCoordinator) -> None:
        super().__init__(coordinator, "refresh")
        self._last_press_at: datetime | None = None
        self._last_press_error: str | None = None

    @property
    def available(self) -> bool:
        """Stay pressable after a failed poll so the user can retry manually."""
        return True

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        payload = self.coordinator.data or {}
        orders = extract_orders(payload)
        meta = getattr(self.coordinator.client, "last_meta", {}) or {}
        attrs: dict[str, Any] = {
            "last_press_at": self._last_press_at.isoformat()
            if self._last_press_at
            else None,
            "last_press_error": self._last_press_error,
            "raw_order_count": len(orders),
            "api_result_code": payload.get("resultCode") or payload.get("result_code"),
            "http_status": meta.get("http_status"),
            "http_method": meta.get("method"),
        }
        if self.coordinator.last_update_success is not None:
            attrs["coordinator_last_success"] = self.coordinator.last_update_success
        return attrs

    async def async_press(self) -> None:
        self._last_press_at = dt_util.utcnow()
        self._last_press_error = None
        _LOGGER.info("Manual refresh of NIO service orders requested")
        try:
            # async_refresh() runs immediately; async_request_refresh() is debounced
            # (~10s) and can feel like the button did nothing.
            await self.coordinator.async_refresh()
        except Exception as err:  # noqa: BLE001 — surface failure on the button entity
            self._last_press_error = str(err)
            _LOGGER.warning("NIO service orders refresh failed: %s", err)
            self.async_write_ha_state()
            raise

        payload = self.coordinator.data or {}
        count = len(extract_orders(payload))
        code = payload.get("resultCode") or payload.get("result_code")
        _LOGGER.info(
            "NIO service orders refreshed: %s orders (resultCode=%s)",
            count,
            code,
        )
        self.async_write_ha_state()
