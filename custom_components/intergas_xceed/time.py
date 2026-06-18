"""Time platform for the Intergas XCeed heating and hot water schedules."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import (
    IntergasXceedDataUpdateCoordinator,
    XceedDhw,
    XceedDhwSlot,
    XceedRoom,
)
from .entity import IntergasXceedEntity

DHW_NAME = "Domestic hot water"

# Defaults used when a weekday has no comfort window stored yet.
DEFAULT_DHW_COMFORT_START = time(6, 0)
DEFAULT_DHW_COMFORT_END = time(22, 0)

# The comfort window start/end the integration exposes per weekday.
DHW_SCHEDULE_FIELDS: tuple[tuple[str, str], ...] = (
    ("start", "comfort start"),
    ("end", "comfort end"),
)

WEEKDAYS: tuple[str, ...] = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


def _snap_to_grid(value: time) -> time:
    """Snap a time to the 10-minute grid the controller supports."""
    minute = min(int(value.minute / 10 + 0.5), 5) * 10
    return time(hour=value.hour, minute=minute)


# Heating zones store their comfort window in a flat day-major list of 7 days x
# 3 switching slots; only the first slot of each day (from = day start, to =
# night start) is exposed. Unlike the 10-minute DHW wizard grid, this runtime
# endpoint stores whole hours only, so values are snapped to the nearest hour.
ROOM_SLOTS_PER_DAY = 3
ROOM_SCHEDULE_LENGTH = 7 * ROOM_SLOTS_PER_DAY
DEFAULT_DAY_START_HOUR = 6
DEFAULT_NIGHT_START_HOUR = 22

# The two editable hours per weekday: (field key, label, schedule slot key).
ROOM_SCHEDULE_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("day_start", "day start", "from"),
    ("night_start", "night start", "to"),
)


def _normalized_room_schedule(room: XceedRoom) -> list:
    """Return the room schedule padded/truncated to the fixed 21 slots."""
    schedule = list(room.schedule or [])
    if len(schedule) < ROOM_SCHEDULE_LENGTH:
        schedule.extend([None] * (ROOM_SCHEDULE_LENGTH - len(schedule)))
    return schedule[:ROOM_SCHEDULE_LENGTH]


def _hour_to_time(value: object) -> time | None:
    """Convert a stored whole-hour value to a time, or None if unset/invalid."""
    try:
        hour = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if hour == 24:
        return time(0, 0)
    if 0 <= hour <= 23:
        return time(hour, 0)
    return None


def _snap_to_hour(value: time) -> int:
    """Snap a time to the nearest whole hour the controller supports (0-23)."""
    hour = value.hour + (1 if value.minute >= 30 else 0)
    return min(hour, 23)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the DHW comfort-window time entities."""
    coordinator: IntergasXceedDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[TimeEntity] = []

    # The schedule comes from the XpertOnly wizard rather than a room, so the
    # entities are gated on a DHW circuit existing - not on the (possibly
    # not-yet-loaded) wizard model. They show as unavailable until the first
    # wizard read succeeds.
    if any(room.is_dhw for room in coordinator.data.rooms):
        for weekday_index, weekday_label in enumerate(WEEKDAYS):
            for field_key, field_label in DHW_SCHEDULE_FIELDS:
                entities.append(
                    IntergasXceedDhwScheduleTime(
                        coordinator,
                        weekday_index,
                        weekday_label,
                        field_key,
                        field_label,
                    )
                )

    # Heating-zone comfort windows expose their day-start and night-start hour
    # per weekday as settable time entities (whole-hour granularity).
    for room in coordinator.data.rooms:
        if room.is_dhw:
            continue
        for weekday_index, weekday_label in enumerate(WEEKDAYS):
            for field_key, field_label, slot_key in ROOM_SCHEDULE_FIELDS:
                entities.append(
                    IntergasXceedRoomScheduleTime(
                        coordinator,
                        room.id,
                        weekday_index,
                        weekday_label,
                        field_key,
                        field_label,
                        slot_key,
                    )
                )

    async_add_entities(entities)


class IntergasXceedDhwScheduleTime(IntergasXceedEntity, TimeEntity):
    """The comfort-window start or end time of a DHW weekday (wizard)."""

    _attr_icon = "mdi:clock-outline"

    def __init__(
        self,
        coordinator: IntergasXceedDataUpdateCoordinator,
        weekday_index: int,
        weekday_label: str,
        field_key: str,
        field_label: str,
    ) -> None:
        """Initialise the DHW schedule time entity."""
        super().__init__(coordinator)
        self._weekday_index = weekday_index
        self._field_key = field_key
        self._attr_unique_id = (
            f"{self._serial}_dhw_schedule_{weekday_index}_{field_key}"
        )
        self._attr_name = f"{DHW_NAME} {weekday_label} {field_label}"

    @property
    def _dhw(self) -> XceedDhw | None:
        """Return the DHW model from the latest update."""
        return self.coordinator.data.dhw

    @property
    def available(self) -> bool:
        """Return True once the wizard model has loaded."""
        dhw = self._dhw
        return super().available and dhw is not None and dhw.available

    def _slot(self) -> XceedDhwSlot | None:
        """Return the schedule slot for this weekday, if present."""
        dhw = self._dhw
        if dhw is None:
            return None
        for slot in dhw.schedule:
            if slot.weekday == self._weekday_index:
                return slot
        return None

    @property
    def native_value(self) -> time | None:
        """Return the configured comfort start/end time, if set."""
        slot = self._slot()
        if slot is None:
            return None
        return slot.start if self._field_key == "start" else slot.end

    async def async_set_value(self, value: time) -> None:
        """Write a new comfort start/end time via the wizard."""
        value = _snap_to_grid(value)
        slot = self._slot()
        start = slot.start if slot and slot.start is not None else DEFAULT_DHW_COMFORT_START
        end = slot.end if slot and slot.end is not None else DEFAULT_DHW_COMFORT_END
        if self._field_key == "start":
            start = value
        else:
            end = value
        await self.coordinator.api.async_set_dhw_schedule_slot(
            self._weekday_index, start, end
        )
        await self.coordinator.async_request_refresh()


class IntergasXceedRoomScheduleTime(IntergasXceedEntity, TimeEntity):
    """The day-start or night-start hour of a heating zone weekday window.

    The runtime schedule endpoint stores whole hours only, so a value set here
    is snapped to the nearest hour before it is written.
    """

    _attr_icon = "mdi:clock-outline"

    def __init__(
        self,
        coordinator: IntergasXceedDataUpdateCoordinator,
        room_id: int,
        weekday_index: int,
        weekday_label: str,
        field_key: str,
        field_label: str,
        slot_key: str,
    ) -> None:
        """Initialise the heating-zone schedule time entity."""
        super().__init__(coordinator)
        self._room_id = room_id
        self._weekday_index = weekday_index
        self._slot_key = slot_key
        self._attr_unique_id = (
            f"{self._serial}_schedule_{room_id}_{weekday_index}_{field_key}"
        )
        room = self._room
        room_name = room.name if room else f"Zone {room_id}"
        self._attr_name = f"{room_name} {weekday_label} {field_label}"

    @property
    def _room(self) -> XceedRoom | None:
        """Return the backing room from the latest data."""
        for room in self.coordinator.data.rooms:
            if room.id == self._room_id:
                return room
        return None

    @property
    def available(self) -> bool:
        """Return True if the zone is present in the latest update."""
        return super().available and self._room is not None

    def _slot(self) -> dict | None:
        """Return the comfort window slot for this weekday, if any."""
        room = self._room
        if room is None:
            return None
        slot = _normalized_room_schedule(room)[
            self._weekday_index * ROOM_SLOTS_PER_DAY
        ]
        return slot if isinstance(slot, dict) else None

    @property
    def native_value(self) -> time | None:
        """Return the configured hour for this weekday, if set."""
        slot = self._slot()
        if slot is None:
            return None
        return _hour_to_time(slot.get(self._slot_key))

    async def async_set_value(self, value: time) -> None:
        """Write a new hour for this weekday's comfort window."""
        room = self._room
        if room is None:
            return
        schedule = _normalized_room_schedule(room)
        index = self._weekday_index * ROOM_SLOTS_PER_DAY
        current = schedule[index]
        if isinstance(current, dict):
            slot = dict(current)
        else:
            slot = {
                "from": DEFAULT_DAY_START_HOUR,
                "to": DEFAULT_NIGHT_START_HOUR,
                "type": "H",
            }
        slot[self._slot_key] = _snap_to_hour(value)
        slot.setdefault("type", "H")
        schedule[index] = slot
        await self.coordinator.api.async_set_room_schedule(self._room_id, schedule)
        await self.coordinator.async_request_refresh()
