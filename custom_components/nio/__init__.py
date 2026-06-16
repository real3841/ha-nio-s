"""The NIO integration."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.loader import async_get_integration

from .api import NioApiClient
from .capture import reconstruct_query_v1
from .change_api import NioChangeApiClient
from .change_coordinator import NioChangeConfigEntry, NioChangeDataUpdateCoordinator
from .const import (
    CONF_CHANGE_METHOD,
    CONF_CHANGE_MOBILEINFO,
    CONF_CHANGE_URL,
    CONF_CHANGE_USER_AGENT,
    CONF_COOKIE,
    CONF_ENTRY_TYPE,
    CONF_MODEL,
    CONF_QUERY,
    CONF_TOKEN,
    CONF_VEHICLE_ID,
    DEFAULT_MODEL,
    DOMAIN,
    ENTRY_TYPE_CHANGE,
    ENTRY_TYPE_VEHICLE,
    STATIC_URL_BASE,
)
from .coordinator import NioConfigEntry, NioDataUpdateCoordinator

VEHICLE_PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.DEVICE_TRACKER,
    Platform.SENSOR,
]

CHANGE_PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: NioConfigEntry) -> bool:
    """Set up NIO from a config entry (vehicle or service-order)."""
    entry_type = entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_VEHICLE)
    if entry_type == ENTRY_TYPE_CHANGE:
        return await _async_setup_change_entry(hass, entry)  # type: ignore[arg-type]
    return await _async_setup_vehicle_entry(hass, entry)


async def _async_setup_vehicle_entry(hass: HomeAssistant, entry: NioConfigEntry) -> bool:
    """Set up a vehicle status config entry."""
    if not hass.data.setdefault(DOMAIN, {}).get("static_registered"):
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    STATIC_URL_BASE,
                    str(Path(__file__).parent / "static"),
                    cache_headers=True,
                )
            ]
        )
        integration = await async_get_integration(hass, DOMAIN)
        add_extra_js_url(
            hass, f"{STATIC_URL_BASE}/nio-car-card.js?v={integration.version}"
        )
        hass.data[DOMAIN]["static_registered"] = True

    client = NioApiClient(
        async_get_clientsession(hass),
        token=entry.data[CONF_TOKEN],
        vehicle_id=entry.data[CONF_VEHICLE_ID],
        query=entry.data[CONF_QUERY],
    )
    coordinator = NioDataUpdateCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, VEHICLE_PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_setup_change_entry(
    hass: HomeAssistant, entry: NioChangeConfigEntry
) -> bool:
    """Set up a service-order / battery-swap config entry."""
    client = NioChangeApiClient(
        async_get_clientsession(hass),
        token=entry.data[CONF_TOKEN],
        url=entry.data[CONF_CHANGE_URL],
        method=entry.data.get(CONF_CHANGE_METHOD, "POST"),
        cookie=entry.data.get(CONF_COOKIE),
        user_agent=entry.data.get(CONF_CHANGE_USER_AGENT),
        mobileinfo=entry.data.get(CONF_CHANGE_MOBILEINFO),
    )
    coordinator = NioChangeDataUpdateCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, CHANGE_PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: NioConfigEntry) -> bool:
    """Migrate v1 (per-field) vehicle entries to v2 (verbatim query)."""
    if entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_VEHICLE) != ENTRY_TYPE_VEHICLE:
        return True
    if entry.version == 1:
        old = entry.data
        new = {
            CONF_ENTRY_TYPE: ENTRY_TYPE_VEHICLE,
            CONF_TOKEN: old[CONF_TOKEN],
            CONF_VEHICLE_ID: old[CONF_VEHICLE_ID],
            CONF_QUERY: reconstruct_query_v1(old),
            CONF_MODEL: old.get(CONF_MODEL, DEFAULT_MODEL),
        }
        hass.config_entries.async_update_entry(entry, data=new, version=2)
    elif CONF_ENTRY_TYPE not in entry.data:
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_ENTRY_TYPE: ENTRY_TYPE_VEHICLE},
        )
    return True


async def _async_update_listener(hass: HomeAssistant, entry: NioConfigEntry) -> None:
    """Reload on options change so new intervals apply."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: NioConfigEntry) -> bool:
    """Unload a config entry."""
    entry_type = entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_VEHICLE)
    platforms = CHANGE_PLATFORMS if entry_type == ENTRY_TYPE_CHANGE else VEHICLE_PLATFORMS
    return await hass.config_entries.async_unload_platforms(entry, platforms)
