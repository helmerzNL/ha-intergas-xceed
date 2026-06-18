"""Async HTTP client for the HeatCon / heatapp! local server."""

from __future__ import annotations

import asyncio
from base64 import b64decode
from dataclasses import dataclass
from datetime import time
from hashlib import md5, sha256
import json
import logging
from time import monotonic
from typing import Any

from aiohttp import ClientError, ClientSession
from Cryptodome.Cipher import AES

from .const import (
    DEFAULT_DEVICE_NAME,
    DEFAULT_UDID,
    DEVICE_TOKEN_IV_B64,
    DHW_DAY_SETPOINT_PREFIX,
    DHW_HEATING_MODE_PREFIX,
    DHW_NIGHT_SETPOINT_PREFIX,
    DHW_SWITCHING_ENTRY_MARKER,
    DHW_SWITCHING_PREFIX,
    DHW_WIZARD_ROOT,
    ENDPOINT_CHALLENGE,
    ENDPOINT_RESPONSE,
    ENDPOINT_ROOM_LIST,
    ENDPOINT_ROOM_SET_TEMPERATURE,
    ENDPOINT_ROOM_UPDATE,
    ENDPOINT_SCENE_SET,
    ENDPOINT_SCENE_STATUS,
    ENDPOINT_SWITCHING_TIMES_GET,
    ENDPOINT_SWITCHING_TIMES_SET,
    ENDPOINT_SYSTEM_STATE,
    ENDPOINT_VERSION,
    ENDPOINT_WEATHER,
    ENDPOINT_WIZARD_NEXT,
    ENDPOINT_WIZARD_SAVE,
    ENDPOINT_WIZARD_START,
    ENDPOINT_XPERTONLY_START,
    REQUEST_TIMEOUT,
    TELEMETRY_REFRESH_INTERVAL,
    TELEMETRY_SCREENS,
    WIZARD_MODE_XPERTONLY,
    WIZARD_REFRESH_INTERVAL,
    WIZARD_SAVE_TYPE_PARAMETER,
    WIZARD_SAVE_TYPE_SWITCHINGTIME,
)

_LOGGER = logging.getLogger(__name__)

# Weekday order of the DHW switching-time list (Monday first, European
# convention). Used only to build the human-readable wizard ``optiontext``.
_WIZARD_WEEKDAYS: tuple[str, ...] = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


class HeatconApiError(Exception):
    """Raised when the device API returns an unexpected result."""


class HeatconAuthenticationError(HeatconApiError):
    """Raised when authentication fails."""


class HeatconInvalidAuthError(HeatconAuthenticationError):
    """Raised when the device explicitly rejects the supplied credentials."""


@dataclass
class _Session:
    """Authenticated session state."""

    user_id: str
    device_token: str


def _normalize_number(value: float) -> float | int:
    """Return an int when the value is whole, otherwise a 0.1-rounded float."""
    number = float(value)
    if number.is_integer():
        return int(number)
    return round(number, 1)


def _serialize_switching_times(
    switching_times: list[dict[str, Any] | None],
) -> str:
    """Serialize the read-model schedule into the pipe-delimited wire format.

    Each slot becomes ``"{from}-{to}-{type}"`` or an empty string when there is
    no heating period, and the slots are joined with ``|``.
    """
    slots: list[str] = []
    for slot in switching_times:
        if not slot:
            slots.append("")
            continue
        start = slot.get("from")
        end = slot.get("to")
        slot_type = slot.get("type") or "H"
        if start is None or end is None:
            slots.append("")
            continue
        slots.append(f"{start}-{end}-{slot_type}")
    return "|".join(slots)


def _wizard_entries(response: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return the ``Eintraege`` list from a wizard response, or an empty list."""
    return ((response or {}).get("heatcom") or {}).get("Eintraege") or []


def _strip_literal(value: str | None) -> str | None:
    """Resolve a HeatCon! text field to its literal string.

    Literal values are prefixed with ``:1`` (e.g. ``":160.0 \u00b0C"`` ->
    ``"60.0 \u00b0C"``); other ``:NNNN`` values are controller translation
    keys that we cannot resolve and therefore return unchanged.
    """
    if value is None:
        return None
    return value[2:] if value.startswith(":1") else value


def _parse_wizard_temp(text: str | None) -> float | None:
    """Parse a literal temperature field such as ``":160.0 \u00b0C"`` -> ``60.0``."""
    literal = _strip_literal(text)
    if not literal:
        return None
    token = literal.split()[0].replace(",", ".")
    try:
        return float(token)
    except ValueError:
        return None


def _parse_wizard_time(text: str | None) -> str | None:
    """Parse a literal time field: ``":113:00"`` -> ``"13:00"``; empty -> None."""
    literal = _strip_literal(text)
    if not literal or literal.startswith("--"):
        return None
    return literal


def _parse_setpoint_bounds(detail: dict[str, Any]) -> dict[str, float] | None:
    """Derive min/max/step from the ``Werteliste`` of a setpoint edit detail."""
    werteliste = ((detail.get("Wertebereich") or {}).get("Werteliste")) or []
    values: list[float] = []
    for item in werteliste:
        try:
            values.append(float(item["Value"]))
        except (KeyError, TypeError, ValueError):
            continue
    if not values:
        return None
    values.sort()
    step = 0.5
    if len(values) >= 2:
        step = round(values[1] - values[0], 3) or 0.5
    return {"min": values[0], "max": values[-1], "step": step}


def _snap_setpoint_key(
    werteliste: list[dict[str, Any]], celsius: float
) -> str | None:
    """Return the ``Key`` whose ``Value`` is closest to the requested value."""
    best_key: str | None = None
    best_diff: float | None = None
    for item in werteliste:
        try:
            value = float(item["Value"])
            key = str(item["Key"])
        except (KeyError, TypeError, ValueError):
            continue
        diff = abs(value - celsius)
        if best_diff is None or diff < best_diff:
            best_diff = diff
            best_key = key
    return best_key


def _format_switchtime(from_time: time, to_time: time) -> str:
    """Serialize a comfort window as the wizard ``"FROM-TO"`` value.

    The controller encodes each bound as ``HH.MM`` with literal, zero-padded
    minutes snapped to the 10-minute grid it supports (e.g. ``13:30`` ->
    ``"13.30"``, ``13:00`` -> ``"13.00"``). The digits after the dot are the
    minute count, NOT a decimal-hour fraction: ``"13.5"`` would be read as
    13:05, which is why the old decimal serialization snapped half-hours back
    to the whole hour.
    """
    return f"{_clock_value(from_time)}-{_clock_value(to_time)}"


def _clock_value(value: time) -> str:
    """Render a ``datetime.time`` as ``HH.MM`` snapped to the 10-minute grid."""
    minute = min(int(value.minute / 10 + 0.5), 5) * 10
    return f"{value.hour:02d}.{minute:02d}"


class HeatconApiClient:
    """Thin async client around the reverse-engineered local heatapp! API."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        session: ClientSession,
    ) -> None:
        self._host = host
        self._username = username
        self._password = password
        self._session = session
        self._auth: _Session | None = None
        self._counter = 0
        self._auth_lock = asyncio.Lock()
        # DHW XpertOnly wizard state (serialised by its own lock).
        self._wizard_lock = asyncio.Lock()
        self._wizard_reqcount = 0
        self._wizard_ereqcount = 0
        self._dhw_cache: dict[str, Any] | None = None
        self._dhw_bounds: dict[str, Any] | None = None
        self._dhw_dirty = False
        self._dhw_last_read = 0.0
        # Telemetry (Information-menu) wizard state; read-only, throttled
        # independently of the DHW read but serialised by the same wizard lock.
        self._telemetry_cache: dict[str, str] | None = None
        self._telemetry_last_read = 0.0

    @property
    def host(self) -> str:
        """Return the configured host."""
        return self._host

    # ------------------------------------------------------------------
    # Public high level API
    # ------------------------------------------------------------------
    async def async_test_connection(self) -> dict[str, Any]:
        """Validate credentials and return device version information."""
        try:
            await self._async_authenticate()
            return await self._async_signed_request(ENDPOINT_VERSION)
        except HeatconApiError:
            _LOGGER.exception(
                "HeatCon test connection failed for host %s", self._host
            )
            raise

    async def async_get_data(self) -> dict[str, Any]:
        """Fetch the full read model from the device."""
        await self._async_authenticate()

        version, rooms, scenes, systemstate, weather = await asyncio.gather(
            self._safe_request(ENDPOINT_VERSION),
            self._safe_request(ENDPOINT_ROOM_LIST),
            self._safe_request(ENDPOINT_SCENE_STATUS),
            self._safe_request(ENDPOINT_SYSTEM_STATE),
            self._safe_request(ENDPOINT_WEATHER),
        )

        if rooms is None:
            raise HeatconApiError("Device did not return a room list")

        room_ids: list[int] = []
        for group in rooms.get("groups") or []:
            for room in group.get("rooms") or []:
                if room.get("id") is not None:
                    room_ids.append(int(room["id"]))

        schedule_results = await asyncio.gather(
            *(
                self._safe_request(ENDPOINT_SWITCHING_TIMES_GET, {"roomid": rid})
                for rid in room_ids
            )
        )
        schedules: dict[int, Any] = {}
        for rid, result in zip(room_ids, schedule_results):
            if result and result.get("switchingtimes") is not None:
                schedules[rid] = result["switchingtimes"]

        # The DHW day/night setpoints and schedule live behind the XpertOnly
        # parameter wizard, which forces its own signed session; run it last so
        # the re-auth it performs cannot disturb the gathers above. It never
        # raises - on failure it returns the previous cache (or None).
        dhw = await self._async_get_dhw_cached()

        # Read-only Information-menu telemetry (energy, COP, speeds, flow,
        # pressures, temperatures) via the same wizard; also failure-tolerant.
        telemetry = await self._async_get_telemetry_cached()

        return {
            "version": version or {},
            "rooms": rooms,
            "scenes": scenes or {},
            "systemstate": systemstate or {},
            "weather": weather or {},
            "schedules": schedules,
            "dhw": dhw,
            "telemetry": telemetry,
        }

    async def async_set_room_temperature(
        self, room_id: int, temperature: float, change_mode: int = 0
    ) -> None:
        """Set the desired temperature for a room/zone.

        Heating zones accept ``change_mode=0`` (override until the next
        switch point); the domestic hot water circuit rejects mode 0 with a
        ``heatcom_error`` and requires ``change_mode=1``.
        """
        if float(temperature).is_integer():
            value: float | int = int(temperature)
        else:
            value = round(float(temperature), 1)
        result = await self._async_signed_request(
            ENDPOINT_ROOM_SET_TEMPERATURE,
            {
                "roomid": int(room_id),
                "change_mode": int(change_mode),
                "temperature": value,
            },
        )
        if result.get("success") is False:
            raise HeatconApiError(
                "Setting the temperature failed: "
                f"{result.get('message') or 'unknown error'}"
            )

    async def async_set_scene(
        self, scene: str, active: bool, duration: int = 1
    ) -> None:
        """Activate or deactivate a heatapp! scene (operating mode)."""
        result = await self._async_signed_request(
            ENDPOINT_SCENE_SET,
            {"scene": scene, "active": 1 if active else 0, "duration": int(duration)},
        )
        if result.get("success") is False:
            raise HeatconApiError(
                f"Setting scene {scene} failed: {result.get('message') or 'unknown error'}"
            )

    async def async_set_room_setpoints(
        self,
        room_id: int,
        name: str,
        day: float,
        day2: float | None,
        night: float,
    ) -> None:
        """Update the day/day2/night comfort setpoints for a room/zone.

        The ``/api/room/update`` endpoint requires the room ``name`` (an empty
        value is rejected) and the full set of setpoints, so callers pass the
        current values for any setpoint that is not being changed. ``day2`` is
        omitted for circuits that do not expose a second day setpoint (such as
        domestic hot water).
        """
        payload: dict[str, Any] = {
            "roomid": int(room_id),
            "name": name,
            "desiredTempDay": _normalize_number(day),
            "desiredTempNight": _normalize_number(night),
        }
        if day2 is not None:
            payload["desiredTempDay2"] = _normalize_number(day2)
        result = await self._async_signed_request(ENDPOINT_ROOM_UPDATE, payload)
        if result.get("success") is False:
            raise HeatconApiError(
                "Updating the setpoints failed: "
                f"{result.get('message') or 'unknown error'}"
            )

    async def async_set_room_schedule(
        self, room_id: int, switching_times: list[dict[str, Any] | None]
    ) -> None:
        """Write the weekly switching schedule for a room/zone.

        ``switching_times`` is the read-model list of 21 slots (7 days x 3
        slots) as returned by the coordinator: each slot is ``None`` (no
        heating period) or a mapping with ``from``/``to``/``type`` keys. The
        endpoint expects a single pipe-delimited string instead of JSON.
        """
        result = await self._async_signed_request(
            ENDPOINT_SWITCHING_TIMES_SET,
            {
                "roomid": int(room_id),
                "switchingtimes": _serialize_switching_times(switching_times),
            },
        )
        if result.get("success") is False:
            raise HeatconApiError(
                "Updating the schedule failed: "
                f"{result.get('message') or 'unknown error'}"
            )

    async def async_set_dhw_setpoint(self, kind: str, celsius: float) -> None:
        """Write a domestic hot water setpoint (``"day"`` or ``"night"``).

        Navigates the XpertOnly wizard to the relevant setpoint leaf, snaps the
        requested temperature to the nearest value the controller offers, then
        saves it. The cache is flagged dirty so the next poll reflects it.
        """
        if kind not in ("day", "night"):
            raise HeatconApiError(f"Unknown DHW setpoint kind {kind!r}")
        prefix = (
            DHW_DAY_SETPOINT_PREFIX if kind == "day" else DHW_NIGHT_SETPOINT_PREFIX
        )
        label = "Day" if kind == "day" else "Night"
        async with self._wizard_lock:
            await self._async_enter_wizard()
            lvl2 = _wizard_entries(await self._wizard_next(DHW_WIZARD_ROOT))
            heating_menu = next(
                (
                    entry
                    for entry in lvl2
                    if str(entry.get("Servercode", "")).startswith(
                        DHW_HEATING_MODE_PREFIX
                    )
                ),
                None,
            )
            if not heating_menu:
                raise HeatconApiError("DHW heating-mode menu not found")
            heating = _wizard_entries(
                await self._wizard_next(heating_menu["Servercode"])
            )
            leaf = next(
                (
                    entry
                    for entry in heating
                    if str(entry.get("Servercode", "")).startswith(prefix)
                ),
                None,
            )
            if not leaf:
                raise HeatconApiError(f"DHW {kind} setpoint not found")
            detail = (
                await self._wizard_next(leaf["Servercode"])
            ).get("heatcom") or {}
            save_servercode = detail.get("Servercode")
            werteliste = (
                (detail.get("Wertebereich") or {}).get("Werteliste")
            ) or []
            key = _snap_setpoint_key(werteliste, float(celsius))
            if not save_servercode or key is None:
                raise HeatconApiError(
                    "DHW setpoint edit detail was incomplete"
                )
            optiontext = f"Domestic hot water  <- Heating mode <- {label} setpoint"
            result = await self._wizard_save(
                save_servercode, key, WIZARD_SAVE_TYPE_PARAMETER, optiontext
            )
            if result.get("success") is False:
                raise HeatconApiError(
                    "Updating the DHW setpoint failed: "
                    f"{result.get('message') or 'unknown error'}"
                )
            self._dhw_dirty = True

    async def async_set_dhw_schedule_slot(
        self, weekday_index: int, from_time: time, to_time: time
    ) -> None:
        """Write a domestic hot water comfort window for one weekday.

        ``weekday_index`` is 0=Monday .. 6=Sunday. ``from_time``/``to_time`` are
        ``datetime.time`` values; minutes are snapped to the 10-minute grid the
        controller supports (e.g. ``13:30`` -> ``"13.30"``).
        """
        if not 0 <= int(weekday_index) <= 6:
            raise HeatconApiError(f"Invalid weekday index {weekday_index}")
        weekday_index = int(weekday_index)
        async with self._wizard_lock:
            await self._async_enter_wizard()
            lvl2 = _wizard_entries(await self._wizard_next(DHW_WIZARD_ROOT))
            switching_menu = next(
                (
                    entry
                    for entry in lvl2
                    if str(entry.get("Servercode", "")).startswith(
                        DHW_SWITCHING_PREFIX
                    )
                ),
                None,
            )
            if not switching_menu:
                raise HeatconApiError("DHW switching-times menu not found")
            switching = _wizard_entries(
                await self._wizard_next(switching_menu["Servercode"])
            )
            slots = [
                entry
                for entry in switching
                if str(entry.get("FormatNext", "")).startswith(
                    DHW_SWITCHING_ENTRY_MARKER
                )
            ]
            index = weekday_index * 2
            if index >= len(slots):
                raise HeatconApiError(
                    f"DHW switching slot for weekday {weekday_index} not found"
                )
            detail = (
                await self._wizard_next(slots[index]["Servercode"])
            ).get("heatcom") or {}
            save_servercode = detail.get("Servercode")
            if not save_servercode:
                raise HeatconApiError(
                    "DHW switching-time edit detail was incomplete"
                )
            value = _format_switchtime(from_time, to_time)
            optiontext = (
                "Domestic hot water  <- Switching times <- "
                f"{_WIZARD_WEEKDAYS[weekday_index]}"
            )
            result = await self._wizard_save(
                save_servercode, value, WIZARD_SAVE_TYPE_SWITCHINGTIME, optiontext
            )
            if result.get("success") is False:
                raise HeatconApiError(
                    "Updating the DHW schedule failed: "
                    f"{result.get('message') or 'unknown error'}"
                )
            self._dhw_dirty = True

    async def _safe_request(
        self, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Run a signed request, returning None on a per-endpoint failure."""
        try:
            return await self._async_signed_request(path, payload)
        except HeatconApiError as err:
            _LOGGER.debug("HeatCon request to %s failed: %s", path, err)
            return None

    # ------------------------------------------------------------------
    # XpertOnly parameter wizard (DHW setpoints + schedule)
    # ------------------------------------------------------------------
    async def _async_get_dhw_cached(self) -> dict[str, Any] | None:
        """Return the DHW wizard read model, throttled and failure-tolerant.

        The wizard tree is re-read at most once per ``WIZARD_REFRESH_INTERVAL``
        (or immediately after a write flags the cache dirty). Any failure keeps
        and returns the previous cache so a transient wizard problem never
        breaks the main read model.
        """
        async with self._wizard_lock:
            now = monotonic()
            if (
                not self._dhw_dirty
                and self._dhw_cache is not None
                and now - self._dhw_last_read < WIZARD_REFRESH_INTERVAL
            ):
                return self._dhw_cache
            try:
                await self._async_enter_wizard()
                payload = await self._async_read_dhw_wizard()
            except HeatconApiError as err:
                _LOGGER.debug(
                    "HeatCon DHW wizard read failed, keeping cache: %s", err
                )
                return self._dhw_cache
            self._dhw_cache = payload
            self._dhw_last_read = now
            self._dhw_dirty = False
            return payload

    async def _async_read_dhw_wizard(self) -> dict[str, Any]:
        """Read the DHW day/night setpoints and 7-day schedule via the wizard.

        Assumes a wizard session was just entered. Setpoints and the schedule
        are captured first; the per-setpoint value bounds are read only once
        (best effort) since they require two extra calls per session.
        """
        lvl2 = _wizard_entries(await self._wizard_next(DHW_WIZARD_ROOT))
        heating_menu = next(
            (
                entry
                for entry in lvl2
                if str(entry.get("Servercode", "")).startswith(
                    DHW_HEATING_MODE_PREFIX
                )
            ),
            None,
        )
        switching_menu = next(
            (
                entry
                for entry in lvl2
                if str(entry.get("Servercode", "")).startswith(DHW_SWITCHING_PREFIX)
            ),
            None,
        )

        day_setpoint: float | None = None
        night_setpoint: float | None = None
        day_leaf: str | None = None
        night_leaf: str | None = None
        if heating_menu:
            heating = _wizard_entries(
                await self._wizard_next(heating_menu["Servercode"])
            )
            for entry in heating:
                servercode = str(entry.get("Servercode", ""))
                if servercode.startswith(DHW_DAY_SETPOINT_PREFIX):
                    day_setpoint = _parse_wizard_temp(entry.get("Text3"))
                    day_leaf = servercode
                elif servercode.startswith(DHW_NIGHT_SETPOINT_PREFIX):
                    night_setpoint = _parse_wizard_temp(entry.get("Text3"))
                    night_leaf = servercode

        schedule: list[dict[str, Any]] = []
        if switching_menu:
            switching = _wizard_entries(
                await self._wizard_next(switching_menu["Servercode"])
            )
            slots = [
                entry
                for entry in switching
                if str(entry.get("FormatNext", "")).startswith(
                    DHW_SWITCHING_ENTRY_MARKER
                )
            ]
            for day_index in range(7):
                index = day_index * 2
                slot = slots[index] if index < len(slots) else None
                schedule.append(
                    {
                        "weekday": day_index,
                        "from": _parse_wizard_time(slot.get("Text3"))
                        if slot
                        else None,
                        "to": _parse_wizard_time(slot.get("Text4"))
                        if slot
                        else None,
                    }
                )

        if self._dhw_bounds is None and (day_leaf or night_leaf):
            try:
                bounds: dict[str, Any] = {}
                if day_leaf:
                    detail = (await self._wizard_next(day_leaf)).get("heatcom") or {}
                    bounds["day"] = _parse_setpoint_bounds(detail)
                if night_leaf:
                    detail = (
                        await self._wizard_next(night_leaf)
                    ).get("heatcom") or {}
                    bounds["night"] = _parse_setpoint_bounds(detail)
                self._dhw_bounds = bounds
            except HeatconApiError as err:
                _LOGGER.debug(
                    "HeatCon DHW bounds read failed (will retry): %s", err
                )

        payload: dict[str, Any] = {
            "available": True,
            "day_setpoint": day_setpoint,
            "night_setpoint": night_setpoint,
            "schedule": schedule,
        }
        if self._dhw_bounds:
            payload["day_bounds"] = self._dhw_bounds.get("day")
            payload["night_bounds"] = self._dhw_bounds.get("night")
        return payload

    async def _async_get_telemetry_cached(self) -> dict[str, str] | None:
        """Return the Information-menu telemetry, throttled and failure-tolerant.

        Mirrors :meth:`_async_get_dhw_cached`: the wizard screens are re-read at
        most once per ``TELEMETRY_REFRESH_INTERVAL`` and any failure keeps and
        returns the previous cache so a transient wizard problem never breaks
        the main read model. Serialised with the DHW read by ``_wizard_lock``.
        """
        async with self._wizard_lock:
            now = monotonic()
            if (
                self._telemetry_cache is not None
                and now - self._telemetry_last_read < TELEMETRY_REFRESH_INTERVAL
            ):
                return self._telemetry_cache
            try:
                await self._async_enter_wizard()
                payload = await self._async_read_telemetry()
            except HeatconApiError as err:
                _LOGGER.debug(
                    "HeatCon telemetry wizard read failed, keeping cache: %s", err
                )
                return self._telemetry_cache
            self._telemetry_cache = payload
            self._telemetry_last_read = now
            return payload

    async def _async_read_telemetry(self) -> dict[str, str]:
        """Read every telemetry screen, returning a ``{PID: raw value}`` map.

        Assumes a wizard session was just entered. One ``wizard/next`` per
        screen servercode; the ``Informationswert`` rows from all screens are
        merged by PID. The raw ``Text3`` value string is kept verbatim and
        decoded downstream in the coordinator.
        """
        values: dict[str, str] = {}
        for servercode in TELEMETRY_SCREENS:
            entries = _wizard_entries(await self._wizard_next(servercode))
            for entry in entries:
                if entry.get("FormatNext") != "Informationswert":
                    continue
                pid = entry.get("PID")
                text = entry.get("Text3")
                if pid is None or text is None:
                    continue
                values[str(pid)] = text
        return values

    async def _async_enter_wizard(self) -> None:
        """Establish a fresh signed session and open the XpertOnly wizard.

        The heatapp! server expires a signed session after only a handful of
        calls, so each wizard interaction starts from a clean re-authentication
        (which also resets the request counter) and replays the web client's
        priming sequence before ``wizard/start``.
        """
        await self._async_force_reauth()
        await self._async_signed_request(
            ENDPOINT_SYSTEM_STATE, {"product": "heatapp-server"}
        )
        await self._request_get(ENDPOINT_XPERTONLY_START)
        await self._wizard_start()

    async def _async_force_reauth(self) -> None:
        """Drop the cached session and authenticate again from scratch."""
        async with self._auth_lock:
            self._auth = None
        await self._async_authenticate()

    async def _wizard_start(self) -> dict[str, Any]:
        """Open the wizard root menu, pinning the per-session request counter."""
        if self._auth is None:
            raise HeatconAuthenticationError("Cannot run wizard without a session")
        self._counter += 1
        self._wizard_reqcount = self._counter
        self._wizard_ereqcount = 0
        params = {
            "modus": WIZARD_MODE_XPERTONLY,
            "code": "",
            "udid": DEFAULT_UDID,
            "ereqcount": self._wizard_ereqcount,
            "reqcount": self._wizard_reqcount,
            "userid": self._auth.user_id,
        }
        return await self._wizard_call(ENDPOINT_WIZARD_START, params)

    async def _wizard_next(self, servercode: str) -> dict[str, Any]:
        """Navigate one step deeper into the wizard tree."""
        if self._auth is None:
            raise HeatconAuthenticationError("Cannot run wizard without a session")
        self._wizard_ereqcount += 1
        params = {
            "servercode": servercode,
            "code": "",
            "udid": DEFAULT_UDID,
            "ereqcount": self._wizard_ereqcount,
            "reqcount": self._wizard_reqcount,
            "userid": self._auth.user_id,
        }
        return await self._wizard_call(ENDPOINT_WIZARD_NEXT, params)

    async def _wizard_save(
        self, servercode: str, value: str, type_: str, optiontext: str
    ) -> dict[str, Any]:
        """Persist a single value through the wizard save endpoint."""
        if self._auth is None:
            raise HeatconAuthenticationError("Cannot run wizard without a session")
        self._wizard_ereqcount += 1
        params = {
            "servercode": servercode,
            "value": value,
            "type": type_,
            "code": "",
            "optiontext": optiontext,
            "udid": DEFAULT_UDID,
            "ereqcount": self._wizard_ereqcount,
            "reqcount": self._wizard_reqcount,
            "userid": self._auth.user_id,
        }
        return await self._wizard_call(ENDPOINT_WIZARD_SAVE, params)

    async def _wizard_call(
        self, path: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Sign and POST a wizard request without auto re-authentication.

        Re-authenticating mid-wizard would scramble the request counters, so a
        rejected session is surfaced as an error (and the cached session
        dropped) for the caller to abort cleanly.
        """
        params["request_signature"] = self._create_signature(params)
        response = await self._request_form(path, params)
        if response.get("loginRejected"):
            self._auth = None
            raise HeatconApiError(f"Wizard call to {path} was login-rejected")
        return response

    async def _request_get(self, path: str) -> None:
        """Issue an unsigned GET (used only to prime XpertOnly mode)."""
        url = f"http://{self._host}{path}"
        try:
            async with self._session.get(
                url,
                headers={"X-Requested-With": "XMLHttpRequest"},
                timeout=REQUEST_TIMEOUT,
            ) as response:
                await response.text()
        except (ClientError, asyncio.TimeoutError) as err:
            _LOGGER.debug(
                "HeatCon GET to %s failed: %s", path, err
            )

    async def _async_authenticate(self) -> None:
        """Log in and cache the decrypted device token."""
        async with self._auth_lock:
            if self._auth is not None:
                return

            challenge = await self._request_form(
                ENDPOINT_CHALLENGE, {"udid": DEFAULT_UDID}
            )
            nonce = challenge.get("devicetoken")
            if not nonce:
                _LOGGER.error(
                    "HeatCon host %s returned no challenge nonce: %s",
                    self._host,
                    challenge,
                )
                raise HeatconApiError("Challenge nonce missing from response")

            hashed = md5(
                f"{self._password}{nonce}".encode("utf-8"), usedforsecurity=False
            ).hexdigest()
            login = await self._request_form(
                ENDPOINT_RESPONSE,
                {
                    "login": self._username,
                    "devicename": DEFAULT_DEVICE_NAME,
                    "token": nonce,
                    "hashed": hashed,
                    "udid": DEFAULT_UDID,
                },
            )

            if login.get("loginRejected") or not login.get("success", True):
                _LOGGER.error(
                    "HeatCon host %s rejected login for user %s",
                    self._host,
                    self._username,
                )
                raise HeatconInvalidAuthError(
                    "The device rejected the supplied credentials"
                )

            encrypted = login.get("devicetoken_encrypted")
            user_id = login.get("userid")
            if not encrypted or user_id is None:
                _LOGGER.error(
                    "HeatCon host %s returned an incomplete login response",
                    self._host,
                )
                raise HeatconApiError("Login response is missing token information")

            self._auth = _Session(
                user_id=str(user_id),
                device_token=self._decrypt_device_token(str(encrypted)),
            )
            self._counter = 0
            _LOGGER.debug("Authenticated against HeatCon at %s", self._host)

    async def _async_signed_request(
        self, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Issue a signed request, re-authenticating once on rejection."""
        await self._async_authenticate()
        if self._auth is None:
            raise HeatconAuthenticationError("Authentication state is missing")

        params: dict[str, Any] = {
            "udid": DEFAULT_UDID,
            "reqcount": self._next_counter(),
            "userid": self._auth.user_id,
        }
        if payload:
            params.update(payload)
        params["request_signature"] = self._create_signature(params)

        response = await self._request_form(path, params)
        if response.get("loginRejected"):
            self._auth = None
            await self._async_authenticate()
            return await self._async_signed_request(path, payload)
        return response

    def _next_counter(self) -> int:
        """Return the next request counter value (0-based, like the app)."""
        value = self._counter
        self._counter += 1
        return value

    def _create_signature(self, params: dict[str, Any]) -> str:
        """Create the md5 request signature the API expects."""
        if self._auth is None:
            raise HeatconAuthenticationError("Cannot sign without a session")
        message = "".join(
            f"{key}={_normalize(params[key])}|"
            for key in sorted(params)
            if key != "request_signature"
        )
        return md5(
            f"{message}{self._auth.device_token}".encode("utf-8"),
            usedforsecurity=False,
        ).hexdigest()

    async def _request_form(
        self, path: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Issue a form-encoded POST request and parse the JSON response."""
        url = f"http://{self._host}{path}"
        try:
            async with self._session.post(
                url,
                data={key: _normalize(value) for key, value in payload.items()},
                headers={"X-Requested-With": "XMLHttpRequest"},
                timeout=REQUEST_TIMEOUT,
            ) as response:
                text = await response.text()
        except (ClientError, asyncio.TimeoutError) as err:
            _LOGGER.error(
                "HeatCon request failed for host %s path %s: %s",
                self._host,
                path,
                err,
            )
            raise HeatconApiError(f"Request to {path} failed: {err}") from err

        if response.status >= 400:
            raise HeatconApiError(
                f"Request to {path} failed with HTTP {response.status}"
            )

        try:
            data = json.loads(text)
        except json.JSONDecodeError as err:
            raise HeatconApiError(
                f"Request to {path} did not return valid JSON"
            ) from err

        if not isinstance(data, dict):
            raise HeatconApiError(f"Request to {path} returned a non-object payload")
        return data

    def _decrypt_device_token(self, encrypted_token: str) -> str:
        """Decrypt the AES-256-CBC encrypted device token."""
        key = sha256(self._password.encode("utf-8")).digest()
        iv = b64decode(DEVICE_TOKEN_IV_B64)
        encrypted_bytes = b64decode(encrypted_token)
        decrypted = AES.new(key, AES.MODE_CBC, iv).decrypt(encrypted_bytes)
        padding_length = decrypted[-1]
        if padding_length < 1 or padding_length > AES.block_size:
            raise HeatconAuthenticationError(
                "Received an invalid encrypted device token"
            )
        return decrypted[:-padding_length].decode("utf-8")


def _normalize(value: Any) -> str:
    """Normalise a value for the request body and signature."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
