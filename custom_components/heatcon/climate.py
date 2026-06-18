"""Climate platform for HeatCon heating zones."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
import voluptuous as vol

from .const import DOMAIN, SERVICE_SET_SCHEDULE
from .coordinator import HeatconDataUpdateCoordinator, HeatconRoom
from .entity import HeatconEntity

DEFAULT_MIN_TEMP = 5.0
DEFAULT_MAX_TEMP = 35.0

SCHEDULE_SLOT_SCHEMA = vol.Any(
    None,
    {
        vol.Required("from"): vol.Coerce(int),
        vol.Required("to"): vol.Coerce(int),
        vol.Optional("type", default="H"): cv.string,
    },
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the climate entities."""
    coordinator: HeatconDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_SET_SCHEDULE,
        {
            vol.Required("switchingtimes"): vol.All(
                cv.ensure_list, [SCHEDULE_SLOT_SCHEMA]
            )
        },
        "async_set_schedule",
    )

    async_add_entities(
        HeatconClimate(coordinator, room.id)
        for room in coordinator.data.rooms
        if not room.is_dhw
    )


class HeatconClimate(HeatconEntity, ClimateEntity):
    """A heating zone exposed as a climate entity."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_target_temperature_step = 0.5
    _attr_hvac_modes = [HVACMode.HEAT]
    _attr_hvac_mode = HVACMode.HEAT

    def __init__(
        self, coordinator: HeatconDataUpdateCoordinator, room_id: int
    ) -> None:
        """Initialise the climate entity."""
        super().__init__(coordinator)
        self._room_id = room_id
        self._attr_unique_id = f"{self._serial}_climate_{room_id}"
        room = self._room
        self._attr_name = room.name if room else f"Zone {room_id}"

    @property
    def _room(self) -> HeatconRoom | None:
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
    def current_temperature(self) -> float | None:
        """Return the measured temperature."""
        room = self._room
        return room.current_temperature if room else None

    @property
    def target_temperature(self) -> float | None:
        """Return the desired temperature."""
        room = self._room
        return room.target_temperature if room else None

    @property
    def min_temp(self) -> float:
        """Return the minimum settable temperature."""
        room = self._room
        if room and room.min_temperature is not None:
            return room.min_temperature
        return DEFAULT_MIN_TEMP

    @property
    def max_temp(self) -> float:
        """Return the maximum settable temperature."""
        room = self._room
        if room and room.max_temperature is not None:
            return room.max_temperature
        return DEFAULT_MAX_TEMP

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return what the zone is currently doing."""
        room = self._room
        if room is None:
            return None
        if room.cooling:
            return HVACAction.COOLING
        return HVACAction.HEATING

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional zone information."""
        room = self._room
        if room is None:
            return {}
        return {
            "day_temperature": room.day_temperature,
            "day2_temperature": room.day2_temperature,
            "night_temperature": room.night_temperature,
            "comfort_mode": room.comfort_mode,
            "cooling_enabled": room.cooling_enabled,
            "window_open": room.window_open,
            "status": room.status,
            "schedule": room.schedule,
        }

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set a new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        await self.coordinator.api.async_set_room_temperature(
            self._room_id, float(temperature)
        )
        await self.coordinator.async_request_refresh()

    async def async_set_schedule(
        self, switchingtimes: list[dict[str, Any] | None]
    ) -> None:
        """Write the weekly switching schedule for this zone.

        ``switchingtimes`` is the flat 21-slot list (7 days x 3 slots) matching
        the ``schedule`` state attribute: each slot is ``None`` or a mapping
        with ``from``/``to``/``type`` keys.
        """
        await self.coordinator.api.async_set_room_schedule(
            self._room_id, switchingtimes
        )
        await self.coordinator.async_request_refresh()
