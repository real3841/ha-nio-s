"""Refresh button for the NIO service-order config entry."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .change_coordinator import NioChangeConfigEntry, NioChangeDataUpdateCoordinator
from .change_entity import NioChangeEntity
from .const import CONF_ENTRY_TYPE, ENTRY_TYPE_CHANGE


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

    async def async_press(self) -> None:
        await self.coordinator.async_request_refresh()
