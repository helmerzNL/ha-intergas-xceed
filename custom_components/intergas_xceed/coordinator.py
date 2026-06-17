"""Data update coordinator for Intergas XCeed."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    IntergasXceedApiClient,
    IntergasXceedAuthenticationError,
    IntergasXceedApiError,
)
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN, MIN_UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)


@dataclass
class XceedRoom:
    """A heating zone or domestic hot water circuit."""

    id: int
    name: str
    appid: str | None
    is_dhw: bool
    current_temperature: float | None
    target_temperature: float | None
    day_temperature: float | None
    day2_temperature: float | None
    night_temperature: float | None
    min_temperature: float | None
    max_temperature: float | None
    comfort_mode: bool | None
    cooling: bool
    cooling_enabled: bool
    window_open: bool
    status: str | None
    schedule: list[Any] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class XceedScene:
    """A heatapp! scene (operating mode)."""

    name: str
    active: bool
    min: int | None = None
    max: int | None = None
    step: int | None = None


@dataclass
class XceedDhwSlot:
    """A single domestic hot water comfort window for one weekday."""

    weekday: int
    start: time | None
    end: time | None


@dataclass
class XceedDhw:
    """Domestic hot water setpoints + schedule read via the XpertOnly wizard."""

    available: bool = False
    day_setpoint: float | None = None
    night_setpoint: float | None = None
    day_min: float | None = None
    day_max: float | None = None
    day_step: float | None = None
    night_min: float | None = None
    night_max: float | None = None
    night_step: float | None = None
    schedule: list[XceedDhwSlot] = field(default_factory=list)


@dataclass
class XceedData:
    """Parsed read model for the integration."""

    rooms: list[XceedRoom] = field(default_factory=list)
    scenes: list[XceedScene] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    weather: dict[str, Any] = field(default_factory=dict)
    version: dict[str, Any] = field(default_factory=dict)
    dhw: XceedDhw | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class IntergasXceedDataUpdateCoordinator(DataUpdateCoordinator[XceedData]):
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
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.config_entry = entry
        self.api = api

    async def _async_update_data(self) -> XceedData:
        """Fetch and parse the latest data from the device."""
        try:
            payload = await self.api.async_get_data()
        except IntergasXceedAuthenticationError as err:
            raise UpdateFailed(f"Authentication failed: {err}") from err
        except IntergasXceedApiError as err:
            raise UpdateFailed(f"API error: {err}") from err
        return _parse(payload)


def _parse(payload: dict[str, Any]) -> XceedData:
    """Convert the raw aggregated payload into a typed model."""
    schedules: dict[int, Any] = payload.get("schedules") or {}
    rooms: list[XceedRoom] = []

    for group in (payload.get("rooms") or {}).get("groups") or []:
        group_id = group.get("groupid")
        for raw in group.get("rooms") or []:
            rid = raw.get("id")
            if rid is None:
                continue
            rid = int(rid)
            appid = raw.get("appid")
            is_dhw = (group_id is not None and int(group_id) < 0) or (
                isinstance(appid, str) and appid.startswith("0201")
            )
            rooms.append(
                XceedRoom(
                    id=rid,
                    name=raw.get("name") or f"Room {rid}",
                    appid=appid,
                    is_dhw=is_dhw,
                    current_temperature=_as_float(raw.get("actualTemperature")),
                    target_temperature=_as_float(raw.get("desiredTemperature")),
                    day_temperature=_as_float(raw.get("desiredTempDay")),
                    day2_temperature=_as_float(raw.get("desiredTempDay2")),
                    night_temperature=_as_float(raw.get("desiredTempNight")),
                    min_temperature=_as_float(raw.get("scheduleTempMin")),
                    max_temperature=_as_float(raw.get("scheduleTempMax")),
                    comfort_mode=raw.get("isComfortMode"),
                    cooling=bool(raw.get("cooling")),
                    cooling_enabled=bool(raw.get("coolingEnabled")),
                    window_open=bool(raw.get("windowPosition")),
                    status=raw.get("status"),
                    schedule=schedules.get(rid, []),
                    raw=raw,
                )
            )

    scenes: list[XceedScene] = []
    for raw in (payload.get("scenes") or {}).get("scenes") or []:
        name = raw.get("name")
        if not name:
            continue
        scenes.append(
            XceedScene(
                name=name,
                active=bool(raw.get("isActive")),
                min=raw.get("min"),
                max=raw.get("max"),
                step=raw.get("step"),
            )
        )

    return XceedData(
        rooms=rooms,
        scenes=scenes,
        errors=(payload.get("systemstate") or {}).get("errors") or [],
        weather=payload.get("weather") or {},
        version=payload.get("version") or {},
        dhw=_parse_dhw(payload.get("dhw")),
        raw=payload,
    )


def _parse_dhw(payload: dict[str, Any] | None) -> XceedDhw | None:
    """Convert the raw wizard DHW payload into a typed model."""
    if not payload:
        return None
    day_bounds = payload.get("day_bounds") or {}
    night_bounds = payload.get("night_bounds") or {}
    schedule: list[XceedDhwSlot] = []
    for slot in payload.get("schedule") or []:
        schedule.append(
            XceedDhwSlot(
                weekday=int(slot.get("weekday", 0)),
                start=_hhmm_to_time(slot.get("from")),
                end=_hhmm_to_time(slot.get("to")),
            )
        )
    return XceedDhw(
        available=bool(payload.get("available")),
        day_setpoint=_as_float(payload.get("day_setpoint")),
        night_setpoint=_as_float(payload.get("night_setpoint")),
        day_min=_as_float(day_bounds.get("min")),
        day_max=_as_float(day_bounds.get("max")),
        day_step=_as_float(day_bounds.get("step")),
        night_min=_as_float(night_bounds.get("min")),
        night_max=_as_float(night_bounds.get("max")),
        night_step=_as_float(night_bounds.get("step")),
        schedule=schedule,
    )


def _hhmm_to_time(value: Any) -> time | None:
    """Convert ``"HH:MM"`` to a ``datetime.time`` (``"13:30"`` -> ``time(13, 30)``)."""
    if not value or not isinstance(value, str) or ":" not in value:
        return None
    hours, _, minutes = value.partition(":")
    try:
        return time(hour=int(hours), minute=int(minutes))
    except (ValueError, TypeError):
        return None


def _as_float(value: Any) -> float | None:
    """Coerce a value to float, returning None on failure."""
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
