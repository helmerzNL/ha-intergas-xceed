"""Diagnostics support for Intergas XCeed."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import IntergasXceedDataUpdateCoordinator

TO_REDACT = {
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    "sysinfo_serial_number",
    "serial",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: IntergasXceedDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "data": async_redact_data(coordinator.data.raw, TO_REDACT),
    }
