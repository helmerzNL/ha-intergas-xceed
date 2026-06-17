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
REQUEST_TIMEOUT: Final = 20
DEVICE_TOKEN_IV_B64: Final = "D3GC5NQEFH13is04KD2tOg=="

CONF_SCAN_INTERVAL: Final = "scan_interval"

PLATFORMS: Final[list[Platform]] = [
    Platform.CLIMATE,
    Platform.WATER_HEATER,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
]
MIN_UPDATE_INTERVAL: Final = timedelta(seconds=10)

# Reverse-engineered local heatapp! server endpoints.
ENDPOINT_CHALLENGE: Final = "/api/user/token/challenge"
ENDPOINT_RESPONSE: Final = "/api/user/token/response"
ENDPOINT_VERSION: Final = "/api/version"
ENDPOINT_ROOM_LIST: Final = "/api/room/list"
ENDPOINT_ROOM_SET_TEMPERATURE: Final = "/api/room/settemperature"
ENDPOINT_SWITCHING_TIMES_GET: Final = "/api/room/switchingtimes/get"
ENDPOINT_SCENE_STATUS: Final = "/api/scene/status"
ENDPOINT_SCENE_SET: Final = "/api/scene/set"
ENDPOINT_SYSTEM_STATE: Final = "/api/systemstate"
ENDPOINT_WEATHER: Final = "/api/weather"

# Scenes are the heatapp! operating modes (Party, Boost, ...).
SCENE_DEFAULT_DURATIONS: Final[dict[str, int]] = {
    "Party": 4,
    "Boost": 30,
    "Holiday": 1,
    "Shower": 30,
    "Leave": 4,
    "Standby": 1,
    "Towel": 1,
}
