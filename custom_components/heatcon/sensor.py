"""Sensor platform for HeatCon."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HeatconDataUpdateCoordinator, HeatconRoom
from .entity import HeatconEntity


@dataclass(frozen=True, kw_only=True)
class HeatconRoomSensorDescription(SensorEntityDescription):
    """Describes a per-room temperature sensor."""

    value_fn: Callable[[HeatconRoom], float | None]


ROOM_SENSORS: tuple[HeatconRoomSensorDescription, ...] = (
    HeatconRoomSensorDescription(
        key="actual_temperature",
        name="Actual temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda room: room.current_temperature,
    ),
    HeatconRoomSensorDescription(
        key="desired_temperature",
        name="Desired temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda room: room.target_temperature,
    ),
    HeatconRoomSensorDescription(
        key="day_temperature",
        name="Day temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda room: room.day_temperature,
    ),
    HeatconRoomSensorDescription(
        key="day2_temperature",
        name="Day 2 temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda room: room.day2_temperature,
    ),
    HeatconRoomSensorDescription(
        key="night_temperature",
        name="Night temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda room: room.night_temperature,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor entities."""
    coordinator: HeatconDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = [
        HeatconWeatherSensor(coordinator),
        HeatconSystemStatusSensor(coordinator),
        HeatconActiveScenesSensor(coordinator),
    ]
    for room in coordinator.data.rooms:
        for description in ROOM_SENSORS:
            if description.value_fn(room) is None:
                continue
            entities.append(
                HeatconRoomSensor(coordinator, room.id, room.name, description)
            )

    async_add_entities(entities)


class HeatconRoomSensor(HeatconEntity, SensorEntity):
    """A per-room temperature sensor."""

    entity_description: HeatconRoomSensorDescription

    def __init__(
        self,
        coordinator: HeatconDataUpdateCoordinator,
        room_id: int,
        room_name: str,
        description: HeatconRoomSensorDescription,
    ) -> None:
        """Initialise the room sensor."""
        super().__init__(coordinator)
        self._room_id = room_id
        self.entity_description = description
        self._attr_unique_id = f"{self._serial}_{room_id}_{description.key}"
        self._attr_name = f"{room_name} {description.name}"

    @property
    def _room(self) -> HeatconRoom | None:
        for room in self.coordinator.data.rooms:
            if room.id == self._room_id:
                return room
        return None

    @property
    def available(self) -> bool:
        return super().available and self._room is not None

    @property
    def native_value(self) -> float | None:
        room = self._room
        if room is None:
            return None
        return self.entity_description.value_fn(room)


class HeatconWeatherSensor(HeatconEntity, SensorEntity):
    """Outdoor temperature reported by the device."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_name = "Outdoor temperature"

    def __init__(self, coordinator: HeatconDataUpdateCoordinator) -> None:
        """Initialise the outdoor temperature sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._serial}_outdoor_temperature"

    @property
    def native_value(self) -> float | None:
        value = self.coordinator.data.weather.get("temperature")
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        weather = self.coordinator.data.weather
        return {
            "min": weather.get("min"),
            "max": weather.get("max"),
            "location": weather.get("forlocation"),
        }


class HeatconSystemStatusSensor(HeatconEntity, SensorEntity):
    """Aggregated system status / error sensor."""

    _attr_name = "System status"

    def __init__(self, coordinator: HeatconDataUpdateCoordinator) -> None:
        """Initialise the system status sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._serial}_system_status"

    @property
    def native_value(self) -> str:
        errors = self.coordinator.data.errors
        if not errors:
            return "OK"
        first = errors[0]
        return (
            first.get("message")
            or first.get("Fehlertext")
            or str(first.get("code"))
            or "Error"
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        errors = self.coordinator.data.errors
        return {
            "error_count": len(errors),
            "errors": errors,
        }


class HeatconActiveScenesSensor(HeatconEntity, SensorEntity):
    """Sensor listing the currently active scenes (operating modes)."""

    _attr_name = "Active modes"

    def __init__(self, coordinator: HeatconDataUpdateCoordinator) -> None:
        """Initialise the active scenes sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._serial}_active_modes"

    @property
    def native_value(self) -> str:
        active = [scene.name for scene in self.coordinator.data.scenes if scene.active]
        return ", ".join(active) if active else "None"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "active_modes": [
                scene.name for scene in self.coordinator.data.scenes if scene.active
            ],
        }
