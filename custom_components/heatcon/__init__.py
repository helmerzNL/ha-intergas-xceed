"""The HeatCon integration."""

from __future__ import annotations

import asyncio
from importlib import import_module
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import HeatconApiClient
from .const import DOMAIN, PLATFORMS
from .coordinator import HeatconDataUpdateCoordinator

type HeatconConfigEntry = ConfigEntry[dict[str, Any]]


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the integration from YAML."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: HeatconConfigEntry) -> bool:
    """Set up HeatCon from a config entry."""
    api = HeatconApiClient(
        host=entry.data[CONF_HOST],
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        session=async_get_clientsession(hass),
    )
    coordinator = HeatconDataUpdateCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await _async_preload_platforms(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HeatconConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: HeatconConfigEntry) -> None:
    """Reload the integration when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_preload_platforms(hass: HomeAssistant) -> None:
    """Import platforms in the executor before forwarding them to Home Assistant."""
    await asyncio.gather(
        *(
            hass.async_add_executor_job(import_module, f"{__package__}.{platform.value}")
            for platform in PLATFORMS
        )
    )
