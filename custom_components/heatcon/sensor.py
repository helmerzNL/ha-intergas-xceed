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
from homeassistant.const import (
    REVOLUTIONS_PER_MINUTE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfPressure,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolumeFlowRate,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, TELEMETRY_SENSORS
from .coordinator import HeatconDataUpdateCoordinator, HeatconRoom
from .entity import HeatconEntity


_TELEMETRY_UNITS: dict[str, str] = {
    "celsius": UnitOfTemperature.CELSIUS,
    "bar": UnitOfPressure.BAR,
    "kwh": UnitOfEnergy.KILO_WATT_HOUR,
    "kw": UnitOfPower.KILO_WATT,
    "hz": UnitOfFrequency.HERTZ,
    "v": UnitOfElectricPotential.VOLT,
    "a": UnitOfElectricCurrent.AMPERE,
    "m3h": UnitOfVolumeFlowRate.CUBIC_METERS_PER_HOUR,
    "rpm": REVOLUTIONS_PER_MINUTE,
    "h": UnitOfTime.HOURS,
}
_TELEMETRY_DEVICE_CLASSES: dict[str, SensorDeviceClass] = {
    "temperature": SensorDeviceClass.TEMPERATURE,
    "pressure": SensorDeviceClass.PRESSURE,
    "energy": SensorDeviceClass.ENERGY,
    "power": SensorDeviceClass.POWER,
    "frequency": SensorDeviceClass.FREQUENCY,
    "voltage": SensorDeviceClass.VOLTAGE,
    "current": SensorDeviceClass.CURRENT,
    "volume_flow_rate": SensorDeviceClass.VOLUME_FLOW_RATE,
    "duration": SensorDeviceClass.DURATION,
}
_TELEMETRY_STATE_CLASSES: dict[str, SensorStateClass] = {
    "measurement": SensorStateClass.MEASUREMENT,
    "total_increasing": SensorStateClass.TOTAL_INCREASING,
}


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

    telemetry = coordinator.data.telemetry
    for spec in TELEMETRY_SENSORS:
        if spec["pid"] in telemetry:
            entities.append(HeatconTelemetrySensor(coordinator, spec))

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


class HeatconTelemetrySensor(HeatconEntity, SensorEntity):
    """A read-only Information-menu telemetry sensor keyed on a firmware PID."""

    def __init__(
        self,
        coordinator: HeatconDataUpdateCoordinator,
        spec: dict[str, Any],
    ) -> None:
        """Initialise a telemetry sensor from its catalog spec."""
        super().__init__(coordinator)
        self._pid: str = spec["pid"]
        self._kind: str = spec["kind"]
        self._attr_name = spec["name"]
        self._attr_unique_id = f"{self._serial}_telemetry_{self._pid}"

        device_class = spec.get("device_class")
        if device_class is not None:
            self._attr_device_class = _TELEMETRY_DEVICE_CLASSES.get(device_class)
        unit = spec.get("unit")
        if unit is not None:
            self._attr_native_unit_of_measurement = _TELEMETRY_UNITS.get(unit)
        state_class = spec.get("state_class")
        if state_class is not None:
            self._attr_state_class = _TELEMETRY_STATE_CLASSES.get(state_class)
        if spec.get("diagnostic"):
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self) -> bool:
        # The PID key is present whenever the screen was read, even when the
        # decoded value is currently unavailable ("--"), so keep the entity
        # available as long as the telemetry read itself succeeded.
        return super().available and self._pid in self.coordinator.data.telemetry

    @property
    def native_value(self) -> float | str | None:
        value = self.coordinator.data.telemetry.get(self._pid)
        if self._kind == "numeric":
            return value if isinstance(value, (int, float)) else None
        return value if isinstance(value, str) else None
