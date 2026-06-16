"""Base entity for the NIO service-order / battery-swap config entry."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .change_capture import change_unique_id
from .change_coordinator import NioChangeDataUpdateCoordinator
from .const import CONF_CHANGE_NAME, CONF_CHANGE_URL, DOMAIN, ENTRY_TYPE_CHANGE


class NioChangeEntity(CoordinatorEntity[NioChangeDataUpdateCoordinator]):
    """Couples an entity to the service-order device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: NioChangeDataUpdateCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        uid = change_unique_id(entry.data[CONF_CHANGE_URL])
        name = entry.data.get(CONF_CHANGE_NAME) or "NIO Service Orders"
        self._attr_unique_id = f"{uid}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, ENTRY_TYPE_CHANGE, uid)},
            manufacturer="NIO",
            model="Service Orders",
            name=name,
        )
