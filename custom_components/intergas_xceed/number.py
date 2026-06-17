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
from .coordinator import IntergasXceedDataUpdateCoordinator, XceedDhw, XceedRoom
from .entity import IntergasXceedEntity

DEFAULT_MIN_TEMP = 5.0
DEFAULT_MAX_TEMP = 35.0

# Domestic hot water defaults (used until the wizard read populates bounds).
DEFAULT_DHW_MIN_TEMP = 40.0
DEFAULT_DHW_MAX_TEMP = 65.0
DEFAULT_DHW_STEP = 0.5
DEFAULT_DHW_COMFORT_START = 6.0
DEFAULT_DHW_COMFORT_END = 22.0

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

# Domestic hot water setpoints and comfort-window fields (wizard-backed).
DHW_SETPOINTS: tuple[tuple[str, str], ...] = (
    ("day", "Day setpoint"),
    ("night", "Night setpoint"),
)
DHW_SCHEDULE_FIELDS: tuple[tuple[str, str], ...] = (
    ("start", "comfort start"),
    ("end", "comfort end"),
)
DHW_NAME = "Domestic hot water"


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

    # The domestic hot water setpoints and schedule come from the XpertOnly
    # wizard rather than a room, so they are gated on a DHW circuit existing -
    # not on the (possibly not-yet-loaded) wizard model. They show as
    # unavailable until the first wizard read succeeds.
    if any(room.is_dhw for room in coordinator.data.rooms):
        for kind, label in DHW_SETPOINTS:
            entities.append(IntergasXceedDhwSetpointNumber(coordinator, kind, label))
        for weekday_index, (_weekday_key, weekday_label) in enumerate(WEEKDAYS):
            for field_key, field_label in DHW_SCHEDULE_FIELDS:
                entities.append(
                    IntergasXceedDhwScheduleNumber(
                        coordinator, weekday_index, weekday_label, field_key, field_label
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


class IntergasXceedDhwSetpointNumber(IntergasXceedEntity, NumberEntity):
    """The domestic hot water day or night setpoint (XpertOnly wizard)."""

    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: IntergasXceedDataUpdateCoordinator,
        kind: str,
        label: str,
    ) -> None:
        """Initialise the DHW setpoint entity."""
        super().__init__(coordinator)
        self._kind = kind
        self._attr_unique_id = f"{self._serial}_dhw_setpoint_{kind}"
        self._attr_name = f"{DHW_NAME} {label}"

    @property
    def _dhw(self) -> XceedDhw | None:
        """Return the DHW model from the latest update."""
        return self.coordinator.data.dhw

    @property
    def available(self) -> bool:
        """Return True once the wizard model has loaded."""
        dhw = self._dhw
        return super().available and dhw is not None and dhw.available

    @property
    def native_min_value(self) -> float:
        """Return the minimum settable setpoint."""
        dhw = self._dhw
        if dhw is not None:
            value = dhw.day_min if self._kind == "day" else dhw.night_min
            if value is not None:
                return value
        return DEFAULT_DHW_MIN_TEMP

    @property
    def native_max_value(self) -> float:
        """Return the maximum settable setpoint."""
        dhw = self._dhw
        if dhw is not None:
            value = dhw.day_max if self._kind == "day" else dhw.night_max
            if value is not None:
                return value
        return DEFAULT_DHW_MAX_TEMP

    @property
    def native_step(self) -> float:
        """Return the setpoint resolution."""
        dhw = self._dhw
        if dhw is not None:
            value = dhw.day_step if self._kind == "day" else dhw.night_step
            if value:
                return value
        return DEFAULT_DHW_STEP

    @property
    def native_value(self) -> float | None:
        """Return the current setpoint."""
        dhw = self._dhw
        if dhw is None:
            return None
        return dhw.day_setpoint if self._kind == "day" else dhw.night_setpoint

    async def async_set_native_value(self, value: float) -> None:
        """Write a new DHW setpoint via the wizard."""
        await self.coordinator.api.async_set_dhw_setpoint(self._kind, value)
        await self.coordinator.async_request_refresh()


class IntergasXceedDhwScheduleNumber(IntergasXceedEntity, NumberEntity):
    """The comfort-window start or end hour of a DHW weekday (wizard)."""

    _attr_native_min_value = 0
    _attr_native_max_value = 24
    _attr_native_step = 0.5
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:clock-outline"

    def __init__(
        self,
        coordinator: IntergasXceedDataUpdateCoordinator,
        weekday_index: int,
        weekday_label: str,
        field_key: str,
        field_label: str,
    ) -> None:
        """Initialise the DHW schedule hour entity."""
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

    def _slot(self) -> Any:
        """Return the schedule slot for this weekday, if present."""
        dhw = self._dhw
        if dhw is None:
            return None
        for slot in dhw.schedule:
            if slot.weekday == self._weekday_index:
                return slot
        return None

    @property
    def native_value(self) -> float | None:
        """Return the configured comfort start/end hour, if set."""
        slot = self._slot()
        if slot is None:
            return None
        return slot.start if self._field_key == "start" else slot.end

    async def async_set_native_value(self, value: float) -> None:
        """Write a new comfort start/end hour via the wizard."""
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
