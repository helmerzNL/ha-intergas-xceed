"""Data update coordinator for Intergas XCeed."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
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
class XceedData:
    """Parsed read model for the integration."""

    rooms: list[XceedRoom] = field(default_factory=list)
    scenes: list[XceedScene] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    weather: dict[str, Any] = field(default_factory=dict)
    version: dict[str, Any] = field(default_factory=dict)
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
        raw=payload,
    )


def _as_float(value: Any) -> float | None:
    """Coerce a value to float, returning None on failure."""
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
