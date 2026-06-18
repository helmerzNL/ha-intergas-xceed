"""Water heater platform for the HeatCon domestic hot water circuit."""

from __future__ import annotations

from datetime import time
from typing import Any

from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import HeatconDataUpdateCoordinator, HeatconDhw, HeatconRoom
from .entity import HeatconEntity

DEFAULT_DHW_MIN_TEMP = 40.0
DEFAULT_DHW_MAX_TEMP = 65.0

DHW_NAME = "Domestic hot water"

# current_operation labels. The domestic hot water circuit follows a single
# daily comfort window: inside it the boiler heats to the day setpoint
# (comfort), outside it to the night setpoint (reduced). Both entities report
# the circuit's current mode so neither shows an "unknown" state.
OPERATION_COMFORT = "comfort"
OPERATION_REDUCED = "reduced"

# (kind, label, carries the schedule attribute)
DHW_KINDS: tuple[tuple[str, str, bool], ...] = (
    ("day", "Day", True),
    ("night", "Night", False),
)

_WEEKDAY_NAMES = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


def _format_time(value: time | None) -> str | None:
    """Format a ``datetime.time`` (``time(13, 30)``) as ``"HH:MM"`` (``"13:30"``)."""
    if value is None:
        return None
    return f"{value.hour:02d}:{value.minute:02d}"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the water heater entities.

    Each domestic hot water circuit is exposed as two water heater entities:
    one for the day (comfort) setpoint and one for the night (reduced)
    setpoint, so both values can be read and adjusted independently.
    """
    coordinator: HeatconDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        HeatconWaterHeater(coordinator, room.id, kind, label, with_schedule)
        for room in coordinator.data.rooms
        if room.is_dhw
        for kind, label, with_schedule in DHW_KINDS
    )


class HeatconWaterHeater(HeatconEntity, WaterHeaterEntity):
    """One domestic hot water setpoint (day or night) as a water heater."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = WaterHeaterEntityFeature.TARGET_TEMPERATURE

    def __init__(
        self,
        coordinator: HeatconDataUpdateCoordinator,
        room_id: int,
        kind: str,
        label: str,
        with_schedule: bool,
    ) -> None:
        """Initialise the water heater entity for one setpoint."""
        super().__init__(coordinator)
        self._room_id = room_id
        self._kind = kind
        self._with_schedule = with_schedule
        self._attr_unique_id = f"{self._serial}_water_heater_{room_id}_{kind}"
        room = self._room
        base = room.name if room else DHW_NAME
        self._attr_name = f"{base} {label}"

    @property
    def _room(self) -> HeatconRoom | None:
        """Return the backing room from the latest data."""
        for room in self.coordinator.data.rooms:
            if room.id == self._room_id:
                return room
        return None

    @property
    def _dhw(self) -> HeatconDhw | None:
        """Return the DHW wizard model from the latest update."""
        return self.coordinator.data.dhw

    @property
    def available(self) -> bool:
        """Return True if the circuit is present in the latest update."""
        return super().available and self._room is not None

    @property
    def current_temperature(self) -> float | None:
        """Return the measured water temperature (shared by both setpoints)."""
        room = self._room
        return room.current_temperature if room else None

    @property
    def target_temperature(self) -> float | None:
        """Return this circuit's day or night setpoint.

        The XpertOnly wizard model matches the boiler menu exactly and is
        preferred; the room-list value is only a fallback until the first
        wizard read completes.
        """
        dhw = self._dhw
        if dhw is not None and dhw.available:
            value = dhw.day_setpoint if self._kind == "day" else dhw.night_setpoint
            if value is not None:
                return value
        room = self._room
        if room is None:
            return None
        return room.day_temperature if self._kind == "day" else room.night_temperature

    @property
    def min_temp(self) -> float:
        """Return the minimum settable temperature."""
        dhw = self._dhw
        if dhw is not None:
            value = dhw.day_min if self._kind == "day" else dhw.night_min
            if value is not None:
                return value
        return DEFAULT_DHW_MIN_TEMP

    @property
    def max_temp(self) -> float:
        """Return the maximum settable temperature."""
        dhw = self._dhw
        if dhw is not None:
            value = dhw.day_max if self._kind == "day" else dhw.night_max
            if value is not None:
                return value
        return DEFAULT_DHW_MAX_TEMP

    @property
    def current_operation(self) -> str:
        """Return whether the circuit is currently in its comfort window.

        Reported on both the day and night entity so neither shows an
        "unknown" state. Until the schedule has been read, the circuit is
        assumed to be in its reduced (night) mode.
        """
        active = self._comfort_active()
        if active is None:
            return OPERATION_REDUCED
        return OPERATION_COMFORT if active else OPERATION_REDUCED

    def _comfort_active(self) -> bool | None:
        """Return True if now falls inside today's comfort window.

        Returns ``None`` when the schedule is not yet available.
        """
        dhw = self._dhw
        if dhw is None or not dhw.schedule:
            return None
        now = dt_util.now()
        weekday = now.weekday()
        now_time = now.time()
        for slot in dhw.schedule:
            if slot.weekday != weekday:
                continue
            if slot.start is None or slot.end is None:
                return None
            if slot.start <= slot.end:
                return slot.start <= now_time < slot.end
            return now_time >= slot.start or now_time < slot.end
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional circuit information.

        Both setpoints are exposed for convenience; the weekly comfort
        schedule is carried on the day entity only.
        """
        room = self._room
        dhw = self._dhw
        attrs: dict[str, Any] = {}
        if room is not None:
            attrs["status"] = room.status
        if dhw is not None and dhw.available:
            attrs["day_temperature"] = dhw.day_setpoint
            attrs["night_temperature"] = dhw.night_setpoint
            if self._with_schedule:
                attrs["schedule"] = [
                    {
                        "weekday": _WEEKDAY_NAMES[slot.weekday]
                        if 0 <= slot.weekday < len(_WEEKDAY_NAMES)
                        else slot.weekday,
                        "from": _format_time(slot.start),
                        "to": _format_time(slot.end),
                    }
                    for slot in dhw.schedule
                ]
        elif room is not None:
            attrs["day_temperature"] = room.day_temperature
            attrs["night_temperature"] = room.night_temperature
            if self._with_schedule:
                attrs["schedule"] = room.schedule
        return attrs

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set a new day or night setpoint via the XpertOnly wizard."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        await self.coordinator.api.async_set_dhw_setpoint(
            self._kind, float(temperature)
        )
        await self.coordinator.async_request_refresh()
