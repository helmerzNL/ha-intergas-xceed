"""Constants for the Intergas XCeed integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "intergas_xceed"
MANUFACTURER: Final = "Intergas"
DEFAULT_PORT: Final = 80
DEFAULT_SCAN_INTERVAL: Final = 30
DEFAULT_DEVICE_NAME: Final = "Home Assistant"
DEFAULT_UDID: Final = "web"
REQUEST_TIMEOUT: Final = 15
DEVICE_TOKEN_IV_B64: Final = "D3GC5NQEFH13is04KD2tOg=="

CONF_SCAN_INTERVAL: Final = "scan_interval"

PLATFORMS: Final[list[Platform]] = [Platform.SENSOR, Platform.BINARY_SENSOR]
MIN_UPDATE_INTERVAL: Final = timedelta(seconds=10)
