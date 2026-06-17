"""Data update coordinator for Intergas XCeed."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import IntergasXceedApiClient
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN, MIN_UPDATE_INTERVAL


class IntergasXceedDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinate polling against the Intergas XCeed device."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: IntergasXceedApiClient,
    ) -> None:
        scan_interval = max(
            entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            int(MIN_UPDATE_INTERVAL.total_seconds()),
        )
        super().__init__(
            hass,
            logger=logging.getLogger(__name__),
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.config_entry = entry
        self.api = api

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch the latest data from the device."""
        return await self.api.async_get_dashboard()
