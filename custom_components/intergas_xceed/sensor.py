"""Sensor platform for Intergas XCeed."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, PERCENTAGE, SIGNAL_STRENGTH_DECIBELS_MILLIWATT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import IntergasXceedDataUpdateCoordinator
from .entity import IntergasXceedCoordinatorEntity, _first_value


@dataclass(frozen=True, kw_only=True)
class IntergasXceedSensorDescription(SensorEntityDescription):
    """Describe an Intergas XCeed sensor."""

    value_paths: tuple[tuple[str, ...], ...]
    value_transform: Callable[[Any], Any] | None = None


SENSORS: tuple[IntergasXceedSensorDescription, ...] = (
    IntergasXceedSensorDescription(
        key="controller_time",
        translation_key="controller_time",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_paths=(
            ("datetime", "datetime"),
            ("datetime", "date_time"),
            ("datetime", "current_time"),
        ),
    ),
    IntergasXceedSensorDescription(
        key="lan_ip_address",
        translation_key="lan_ip_address",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_paths=(
            ("network", "ip"),
            ("network", "ip_address"),
            ("network", "lan_ip"),
        ),
    ),
    IntergasXceedSensorDescription(
        key="wifi_ssid",
        translation_key="wifi_ssid",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_paths=(
            ("network", "ssid"),
            ("network", "wlan_ssid"),
        ),
    ),
    IntergasXceedSensorDescription(
        key="wifi_signal",
        translation_key="wifi_signal",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        value_paths=(
            ("network", "rssi"),
            ("network", "wlan_rssi"),
            ("network", "signal_strength"),
        ),
        value_transform=_coerce_float,
    ),
    IntergasXceedSensorDescription(
        key="portal_hostname",
        translation_key="portal_hostname",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_paths=(
            ("portal", "hostname"),
            ("portal", "url"),
            ("portal", "server"),
        ),
    ),
    IntergasXceedSensorDescription(
        key="parameter_sync_progress",
        translation_key="parameter_sync_progress",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=PERCENTAGE,
        value_paths=(
            ("parameter_progress", "progress"),
            ("parameter_progress", "percentage"),
            ("parameter_progress", "percent"),
        ),
        value_transform=_coerce_float,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    coordinator: IntergasXceedDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        IntergasXceedSensor(coordinator, entry, description) for description in SENSORS
    )


class IntergasXceedSensor(IntergasXceedCoordinatorEntity, SensorEntity):
    """Representation of an Intergas XCeed sensor."""

    entity_description: IntergasXceedSensorDescription

    def __init__(
        self,
        coordinator: IntergasXceedDataUpdateCoordinator,
        entry: ConfigEntry,
        description: IntergasXceedSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.unique_id or coordinator.api.host}_{description.key}"

    @property
    def native_value(self) -> Any:
        """Return the current value."""
        value = _first_value(self.coordinator.data, *self.entity_description.value_paths)
        if value is None or self.entity_description.value_transform is None:
            return value
        return self.entity_description.value_transform(value)


def _coerce_float(value: Any) -> float | None:
    """Convert numeric strings to floats."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
