"""Water heater platform for the Intergas XCeed domestic hot water circuit."""

from __future__ import annotations

from typing import Any

from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import IntergasXceedDataUpdateCoordinator, XceedRoom
from .entity import IntergasXceedEntity

DEFAULT_MIN_TEMP = 5.0
DEFAULT_MAX_TEMP = 65.0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the water heater entities."""
    coordinator: IntergasXceedDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        IntergasXceedWaterHeater(coordinator, room.id)
        for room in coordinator.data.rooms
        if room.is_dhw
    )


class IntergasXceedWaterHeater(IntergasXceedEntity, WaterHeaterEntity):
    """The domestic hot water circuit exposed as a water heater entity."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = WaterHeaterEntityFeature.TARGET_TEMPERATURE

    def __init__(
        self, coordinator: IntergasXceedDataUpdateCoordinator, room_id: int
    ) -> None:
        """Initialise the water heater entity."""
        super().__init__(coordinator)
        self._room_id = room_id
        self._attr_unique_id = f"{self._serial}_water_heater_{room_id}"
        room = self._room
        self._attr_name = room.name if room else "Domestic hot water"

    @property
    def _room(self) -> XceedRoom | None:
        """Return the backing room from the latest data."""
        for room in self.coordinator.data.rooms:
            if room.id == self._room_id:
                return room
        return None

    @property
    def available(self) -> bool:
        """Return True if the circuit is present in the latest update."""
        return super().available and self._room is not None

    @property
    def current_temperature(self) -> float | None:
        """Return the measured water temperature."""
        room = self._room
        return room.current_temperature if room else None

    @property
    def target_temperature(self) -> float | None:
        """Return the desired water temperature."""
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
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional circuit information."""
        room = self._room
        if room is None:
            return {}
        return {
            "day_temperature": room.day_temperature,
            "night_temperature": room.night_temperature,
            "status": room.status,
            "schedule": room.schedule,
        }

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set a new target water temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        await self.coordinator.api.async_set_room_temperature(
            self._room_id, float(temperature), change_mode=1
        )
        await self.coordinator.async_request_refresh()
