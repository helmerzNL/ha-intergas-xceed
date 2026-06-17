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
    Platform.NUMBER,
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
ENDPOINT_SWITCHING_TIMES_SET: Final = "/api/room/switchingtimes/set"
ENDPOINT_ROOM_UPDATE: Final = "/api/room/update"
ENDPOINT_SCENE_STATUS: Final = "/api/scene/status"
ENDPOINT_SCENE_SET: Final = "/api/scene/set"
ENDPOINT_SYSTEM_STATE: Final = "/api/systemstate"
ENDPOINT_WEATHER: Final = "/api/weather"

# XpertOnly parameter wizard - the only channel that reads/writes the domestic
# hot water (DHW) day/night setpoints and weekly schedule with the exact values
# shown in the boiler menu. The runtime /api/room/* endpoints expose neither.
ENDPOINT_XPERTONLY_START: Final = "/api/xpertonly/start"
ENDPOINT_WIZARD_START: Final = "/api/wizard/start"
ENDPOINT_WIZARD_NEXT: Final = "/api/wizard/next"
ENDPOINT_WIZARD_SAVE: Final = "/api/wizard/save"

WIZARD_MODE_XPERTONLY: Final = "XpertOnly"
WIZARD_SAVE_TYPE_PARAMETER: Final = "parameter"
WIZARD_SAVE_TYPE_SWITCHINGTIME: Final = "switchingtime"

# The DHW wizard tree is read at most once per this interval (seconds); each
# read forces a fresh signed session, so it is deliberately decoupled from the
# main polling cycle. A write flags the cache dirty to force an early re-read.
WIZARD_REFRESH_INTERVAL: Final = 300

# Stable HeatCon! servercodes/prefixes for the domestic hot water sub-tree.
DHW_WIZARD_ROOT: Final = "4600000100000000008000C0C6010002000301"
DHW_HEATING_MODE_PREFIX: Final = "4600F000"
DHW_SWITCHING_PREFIX: Final = "46000400"
DHW_DAY_SETPOINT_PREFIX: Final = "4600F001"
DHW_NIGHT_SETPOINT_PREFIX: Final = "4600F002"
DHW_SWITCHING_ENTRY_MARKER: Final = "Editieren Schaltzeit"

# Custom Home Assistant services.
SERVICE_SET_SCHEDULE: Final = "set_schedule"

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
