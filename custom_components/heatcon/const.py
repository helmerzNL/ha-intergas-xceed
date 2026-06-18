"""Constants for the HeatCon integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Final

from homeassistant.const import Platform

DOMAIN: Final = "heatcon"
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
    Platform.TIME,
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

# ---------------------------------------------------------------------------
# Telemetry (Information-menu) read-only sensors
# ---------------------------------------------------------------------------
# The heatapp! app's "Information" screens (energy, COP, pump/compressor speeds,
# volume flow, pressures, all heat-generator temperatures) are served locally
# through the same XpertOnly wizard as the DHW setpoints. After a single
# wizard/start, one wizard/next per screen servercode returns that screen's
# ``Informationswert`` rows. Each row's PID is the stable key, Text3 the value.
# The values are read at most once per this interval (seconds), decoupled from
# the main polling cycle and failure-tolerant (a transient wizard error keeps
# the previous cache).
TELEMETRY_REFRESH_INTERVAL: Final = 120

# Screen servercodes to poll. One wizard/next each; all returned rows are merged
# into a single ``{PID: value}`` map, so the order is irrelevant and a PID that
# appears on two screens simply resolves to the same value.
TELEMETRY_SCREENS: Final[tuple[str, ...]] = (
    "6400030000000000008000C0C6020003000401",  # heat generator (temps/flow/pressure/power/energy)
    "6600030000000000008000C0C6020003000401",  # heat generator status + runtime
    "8D00030000000000008000C0C6020003000401",  # COP total
    "8D0FB10100070A000F0000C0C6030003000601",  # COP daily
    "8D0FB10100080A00100000C0C6030003000601",  # energy monthly (kWh)
    "8D0FB10100060A000E0000C0C6030003000601",  # energy yearly (kWh)
    "3200030000000000008000C0C6020003000401",  # heating buffer
    "C400032900000000000800C0C6030003000401",  # physical sensor inputs (outdoor/DHW tank/room/water pressure)
)

# Firmware ``heatcom`` enum state codes that appear in telemetry value fields.
# A value of ``":2<code>"`` resolves to one of these display strings; the code
# ``557`` ("--") means the value is currently not available.
TELEMETRY_ENUM_STATES: Final[dict[str, str]] = {
    "208": "off",
    "214": "automatic",
    "254": "on",
    "318": "heating",
    "324": "heating circuit",
    "518": "setpoint",
}
TELEMETRY_UNAVAILABLE_CODE: Final = "557"

# Curated catalog of telemetry sensors keyed on the stable firmware PID. ``unit``
# and ``device_class`` are tokens resolved to Home Assistant constants in
# sensor.py; ``kind`` is ``"numeric"`` (literal value parsed to a float) or
# ``"enum"`` (firmware state code mapped via ``TELEMETRY_ENUM_STATES``). Sensors
# flagged ``diagnostic`` land under the device's diagnostics section.
TELEMETRY_SENSORS: Final[tuple[dict[str, Any], ...]] = (
    {"pid": "40450", "name": "Volume flow", "device_class": "volume_flow_rate", "unit": "m3h", "state_class": "measurement", "kind": "numeric"},
    {"pid": "40452", "name": "Ambient temperature", "device_class": "temperature", "unit": "celsius", "state_class": "measurement", "kind": "numeric"},
    {"pid": "40455", "name": "Supply flow temperature", "device_class": "temperature", "unit": "celsius", "state_class": "measurement", "kind": "numeric"},
    {"pid": "40456", "name": "Return flow temperature", "device_class": "temperature", "unit": "celsius", "state_class": "measurement", "kind": "numeric"},
    {"pid": "40453", "name": "Evaporator inlet temperature (T1)", "device_class": "temperature", "unit": "celsius", "state_class": "measurement", "kind": "numeric", "diagnostic": True},
    {"pid": "40454", "name": "Condenser outlet temperature (T4)", "device_class": "temperature", "unit": "celsius", "state_class": "measurement", "kind": "numeric", "diagnostic": True},
    {"pid": "40457", "name": "Suction compressor temperature (T2)", "device_class": "temperature", "unit": "celsius", "state_class": "measurement", "kind": "numeric", "diagnostic": True},
    {"pid": "40458", "name": "Exhaust compressor temperature (T3)", "device_class": "temperature", "unit": "celsius", "state_class": "measurement", "kind": "numeric", "diagnostic": True},
    {"pid": "40459", "name": "High pressure temperature", "device_class": "temperature", "unit": "celsius", "state_class": "measurement", "kind": "numeric", "diagnostic": True},
    {"pid": "40460", "name": "Low pressure temperature", "device_class": "temperature", "unit": "celsius", "state_class": "measurement", "kind": "numeric", "diagnostic": True},
    {"pid": "40469", "name": "Inverter temperature", "device_class": "temperature", "unit": "celsius", "state_class": "measurement", "kind": "numeric", "diagnostic": True},
    {"pid": "40470", "name": "Compressor frequency", "device_class": "frequency", "unit": "hz", "state_class": "measurement", "kind": "numeric"},
    {"pid": "40472", "name": "Fan speed", "device_class": None, "unit": "rpm", "state_class": "measurement", "kind": "numeric"},
    {"pid": "40473", "name": "EEV opening step", "device_class": None, "unit": None, "state_class": "measurement", "kind": "numeric", "diagnostic": True},
    {"pid": "40462", "name": "Power consumption", "device_class": "power", "unit": "kw", "state_class": "measurement", "kind": "numeric"},
    {"pid": "40471", "name": "Compressor input current", "device_class": "current", "unit": "a", "state_class": "measurement", "kind": "numeric", "diagnostic": True},
    {"pid": "40464", "name": "AC input voltage", "device_class": "voltage", "unit": "v", "state_class": "measurement", "kind": "numeric", "diagnostic": True},
    {"pid": "40466", "name": "Heat pump input voltage", "device_class": "voltage", "unit": "v", "state_class": "measurement", "kind": "numeric", "diagnostic": True},
    {"pid": "40467", "name": "Heat pump input current", "device_class": "current", "unit": "a", "state_class": "measurement", "kind": "numeric", "diagnostic": True},
    {"pid": "40475", "name": "Refrigerant low pressure (P3)", "device_class": "pressure", "unit": "bar", "state_class": "measurement", "kind": "numeric"},
    {"pid": "40476", "name": "Refrigerant high pressure (P1)", "device_class": "pressure", "unit": "bar", "state_class": "measurement", "kind": "numeric"},
    {"pid": "37938", "name": "Thermal energy produced", "device_class": "energy", "unit": "kwh", "state_class": "total_increasing", "kind": "numeric"},
    {"pid": "37936", "name": "Thermal output", "device_class": "power", "unit": "kw", "state_class": "measurement", "kind": "numeric"},
    {"pid": "37908", "name": "Heat generator status", "device_class": None, "unit": None, "state_class": None, "kind": "enum"},
    {"pid": "37929", "name": "Heat generator pump", "device_class": None, "unit": None, "state_class": None, "kind": "enum"},
    {"pid": "37911", "name": "Compressor total starts", "device_class": None, "unit": None, "state_class": "total_increasing", "kind": "numeric", "diagnostic": True},
    {"pid": "37913", "name": "Compressor runtime", "device_class": "duration", "unit": "h", "state_class": "total_increasing", "kind": "numeric", "diagnostic": True},
    {"pid": "37912", "name": "Compressor stage 2 starts", "device_class": None, "unit": None, "state_class": "total_increasing", "kind": "numeric", "diagnostic": True},
    {"pid": "37914", "name": "Compressor stage 2 runtime", "device_class": "duration", "unit": "h", "state_class": "total_increasing", "kind": "numeric", "diagnostic": True},
    {"pid": "40990", "name": "COP total", "device_class": None, "unit": None, "state_class": "measurement", "kind": "numeric"},
    {"pid": "40482", "name": "COP today", "device_class": None, "unit": None, "state_class": "measurement", "kind": "numeric"},
    {"pid": "40483", "name": "COP yesterday", "device_class": None, "unit": None, "state_class": "measurement", "kind": "numeric", "diagnostic": True},
    {"pid": "40494", "name": "Energy this month", "device_class": "energy", "unit": "kwh", "state_class": "total_increasing", "kind": "numeric"},
    {"pid": "40530", "name": "Energy this year", "device_class": "energy", "unit": "kwh", "state_class": "total_increasing", "kind": "numeric"},
    {"pid": "38043", "name": "Heating buffer temperature", "device_class": "temperature", "unit": "celsius", "state_class": "measurement", "kind": "numeric"},
    {"pid": "37123", "name": "Outdoor sensor temperature (AF)", "device_class": "temperature", "unit": "celsius", "state_class": "measurement", "kind": "numeric"},
    {"pid": "37125", "name": "DHW storage sensor temperature", "device_class": "temperature", "unit": "celsius", "state_class": "measurement", "kind": "numeric"},
    {"pid": "37173", "name": "Room 1 sensor temperature", "device_class": "temperature", "unit": "celsius", "state_class": "measurement", "kind": "numeric", "diagnostic": True},
    {"pid": "37134", "name": "System water pressure", "device_class": "pressure", "unit": "bar", "state_class": "measurement", "kind": "numeric"},
)

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
