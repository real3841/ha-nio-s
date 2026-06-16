"""DataUpdateCoordinator for NIO service-order / battery-swap polling."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .change_api import NioChangeApiClient, NioChangeApiError, NioChangeAuthError
from .change_data import ServiceSummary, analyze_service_orders
from .const import DEFAULT_CHANGE_INTERVAL, DOMAIN, OPT_CHANGE_INTERVAL

_LOGGER = logging.getLogger(__name__)

type NioChangeConfigEntry = ConfigEntry[NioChangeDataUpdateCoordinator]


class NioChangeDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls service-order API on a fixed interval."""

    config_entry: NioChangeConfigEntry
    summary: ServiceSummary | None = None

    def __init__(
        self,
        hass: HomeAssistant,
        entry: NioChangeConfigEntry,
        client: NioChangeApiClient,
    ) -> None:
        minutes = int(entry.options.get(OPT_CHANGE_INTERVAL, DEFAULT_CHANGE_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_change",
            update_interval=timedelta(minutes=minutes),
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            data = await self.client.async_get_orders()
        except NioChangeAuthError as err:
            raise ConfigEntryAuthFailed(
                "NIO service-order token rejected — re-sniff a fresh token"
            ) from err
        except NioChangeApiError as err:
            raise UpdateFailed(str(err)) from err

        self.summary = analyze_service_orders(data)
        minutes = int(
            self.config_entry.options.get(OPT_CHANGE_INTERVAL, DEFAULT_CHANGE_INTERVAL)
        )
        self.update_interval = timedelta(minutes=minutes)
        return data
