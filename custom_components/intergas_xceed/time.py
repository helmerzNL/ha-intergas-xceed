"""Time platform for the Intergas XCeed domestic hot water schedule."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import IntergasXceedDataUpdateCoordinator, XceedDhw, XceedDhwSlot
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
