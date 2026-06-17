"""Number platform for Intergas XCeed comfort setpoints and schedule."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import IntergasXceedDataUpdateCoordinator, XceedRoom
from .entity import IntergasXceedEntity

DEFAULT_MIN_TEMP = 5.0
DEFAULT_MAX_TEMP = 35.0

# The device stores 7 days x 3 switching slots. Only the first slot of each day
# (the comfort window) is exposed through Home Assistant. Weekday index 0 maps
# to Monday, following the European convention used by the heatapp! app.
SLOTS_PER_DAY = 3
SCHEDULE_LENGTH = 7 * SLOTS_PER_DAY
DEFAULT_DAY_START = 6
DEFAULT_NIGHT_START = 22

WEEKDAYS: tuple[tuple[str, str], ...] = (
    ("monday", "Monday"),
    ("tuesday", "Tuesday"),
    ("wednesday", "Wednesday"),
    ("thursday", "Thursday"),
    ("friday", "Friday"),
    ("saturday", "Saturday"),
    ("sunday", "Sunday"),
)


@dataclass(frozen=True, kw_only=True)
class XceedSetpointDescription:
    """Describes a writable comfort setpoint of a room."""

    key: str
    label: str
    value_fn: Callable[[XceedRoom], float | None]


SETPOINTS: tuple[XceedSetpointDescription, ...] = (
    XceedSetpointDescription(
        key="day",
        label="Day setpoint",
        value_fn=lambda room: room.day_temperature,
    ),
    XceedSetpointDescription(
        key="day2",
        label="Day 2 setpoint",
        value_fn=lambda room: room.day2_temperature,
    ),
    XceedSetpointDescription(
        key="night",
        label="Night setpoint",
        value_fn=lambda room: room.night_temperature,
    ),
)


@dataclass(frozen=True, kw_only=True)
class XceedScheduleField:
    """Describes one editable hour of a weekday comfort window."""

    key: str
    label: str
    slot_key: str
    default: int


SCHEDULE_FIELDS: tuple[XceedScheduleField, ...] = (
    XceedScheduleField(
        key="day_start",
        label="day start",
        slot_key="from",
        default=DEFAULT_DAY_START,
    ),
    XceedScheduleField(
        key="night_start",
        label="night start",
        slot_key="to",
        default=DEFAULT_NIGHT_START,
    ),
)


def _normalized_schedule(room: XceedRoom) -> list[Any]:
    """Return the room schedule padded/truncated to the fixed 21 slots."""
    schedule = list(room.schedule or [])
    if len(schedule) < SCHEDULE_LENGTH:
        schedule.extend([None] * (SCHEDULE_LENGTH - len(schedule)))
    return schedule[:SCHEDULE_LENGTH]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the setpoint number entities."""
    coordinator: IntergasXceedDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[NumberEntity] = []
    for room in coordinator.data.rooms:
        if room.is_dhw:
            continue
        for description in SETPOINTS:
            if description.value_fn(room) is None:
                continue
            entities.append(
                IntergasXceedSetpointNumber(coordinator, room.id, description)
            )
        for weekday_index, (weekday_key, weekday_label) in enumerate(WEEKDAYS):
            for field in SCHEDULE_FIELDS:
                entities.append(
                    IntergasXceedScheduleNumber(
                        coordinator,
                        room.id,
                        weekday_index,
                        weekday_key,
                        weekday_label,
                        field,
                    )
                )
    async_add_entities(entities)


class IntergasXceedSetpointNumber(IntergasXceedEntity, NumberEntity):
    """A writable day/day2/night comfort setpoint for a heating zone."""

    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_step = 0.5
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: IntergasXceedDataUpdateCoordinator,
        room_id: int,
        description: XceedSetpointDescription,
    ) -> None:
        """Initialise the setpoint number entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._room_id = room_id
        self._attr_unique_id = f"{self._serial}_setpoint_{description.key}_{room_id}"
        room = self._room
        room_name = room.name if room else f"Zone {room_id}"
        self._attr_name = f"{room_name} {description.label}"

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

    @property
    def native_min_value(self) -> float:
        """Return the minimum settable setpoint."""
        room = self._room
        if room and room.min_temperature is not None:
            return room.min_temperature
        return DEFAULT_MIN_TEMP

    @property
    def native_max_value(self) -> float:
        """Return the maximum settable setpoint."""
        room = self._room
        if room and room.max_temperature is not None:
            return room.max_temperature
        return DEFAULT_MAX_TEMP

    @property
    def native_value(self) -> float | None:
        """Return the current value of this setpoint."""
        room = self._room
        if room is None:
            return None
        return self.entity_description.value_fn(room)

    async def async_set_native_value(self, value: float) -> None:
        """Write a new value for this setpoint."""
        room = self._room
        if room is None:
            return
        day = room.day_temperature
        day2 = room.day2_temperature
        night = room.night_temperature
        if self.entity_description.key == "day":
            day = value
        elif self.entity_description.key == "day2":
            day2 = value
        else:
            night = value
        if day is None or night is None:
            return
        await self.coordinator.api.async_set_room_setpoints(
            self._room_id,
            room.name,
            day,
            day2,
            night,
        )
        await self.coordinator.async_request_refresh()


class IntergasXceedScheduleNumber(IntergasXceedEntity, NumberEntity):
    """The day-start or night-start hour of a weekday comfort window."""

    _attr_native_min_value = 0
    _attr_native_max_value = 23
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:clock-outline"

    def __init__(
        self,
        coordinator: IntergasXceedDataUpdateCoordinator,
        room_id: int,
        weekday_index: int,
        weekday_key: str,
        weekday_label: str,
        field: XceedScheduleField,
    ) -> None:
        """Initialise the schedule hour entity."""
        super().__init__(coordinator)
        self._room_id = room_id
        self._weekday_index = weekday_index
        self._field = field
        self._attr_unique_id = (
            f"{self._serial}_schedule_{room_id}_{weekday_key}_{field.key}"
        )
        room = self._room
        room_name = room.name if room else f"Zone {room_id}"
        self._attr_name = f"{room_name} {weekday_label} {field.label}"

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

    @property
    def _slot(self) -> dict[str, Any] | None:
        """Return the comfort window slot for this weekday, if any."""
        room = self._room
        if room is None:
            return None
        slot = _normalized_schedule(room)[self._weekday_index * SLOTS_PER_DAY]
        return slot if isinstance(slot, dict) else None

    @property
    def native_value(self) -> float | None:
        """Return the configured hour for this weekday, if set."""
        slot = self._slot
        if slot is None:
            return None
        value = slot.get(self._field.slot_key)
        return float(value) if value is not None else None

    async def async_set_native_value(self, value: float) -> None:
        """Write a new hour for this weekday's comfort window."""
        room = self._room
        if room is None:
            return
        schedule = _normalized_schedule(room)
        index = self._weekday_index * SLOTS_PER_DAY
        current = schedule[index]
        if isinstance(current, dict):
            slot = dict(current)
        else:
            slot = {
                "from": DEFAULT_DAY_START,
                "to": DEFAULT_NIGHT_START,
                "type": "H",
            }
        slot[self._field.slot_key] = int(value)
        slot.setdefault("type", "H")
        schedule[index] = slot
        await self.coordinator.api.async_set_room_schedule(self._room_id, schedule)
        await self.coordinator.async_request_refresh()
