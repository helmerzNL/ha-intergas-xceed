"""Binary sensor platform for Intergas XCeed."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import IntergasXceedDataUpdateCoordinator
from .entity import IntergasXceedCoordinatorEntity, _first_value


@dataclass(frozen=True, kw_only=True)
class IntergasXceedBinarySensorDescription(BinarySensorEntityDescription):
    """Describe an Intergas XCeed binary sensor."""

    value_paths: tuple[tuple[str, ...], ...]


BINARY_SENSORS: tuple[IntergasXceedBinarySensorDescription, ...] = (
    IntergasXceedBinarySensorDescription(
        key="portal_enabled",
        translation_key="portal_enabled",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_paths=(
            ("portal", "enabled"),
            ("portal", "active"),
            ("portal", "portal_enabled"),
        ),
    ),
    IntergasXceedBinarySensorDescription(
        key="wifi_connected",
        translation_key="wifi_connected",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_paths=(
            ("network", "wifi_connected"),
            ("network", "wlan_connected"),
            ("network", "connected"),
        ),
    ),
    IntergasXceedBinarySensorDescription(
        key="parameter_sync_busy",
        translation_key="parameter_sync_busy",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_paths=(
            ("parameter_progress", "busy"),
            ("parameter_progress", "in_progress"),
            ("parameter_progress", "active"),
            ("parameter_progress", "running"),
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensor platform."""
    coordinator: IntergasXceedDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        IntergasXceedBinarySensor(coordinator, entry, description)
        for description in BINARY_SENSORS
    )


class IntergasXceedBinarySensor(IntergasXceedCoordinatorEntity, BinarySensorEntity):
    """Representation of an Intergas XCeed binary sensor."""

    entity_description: IntergasXceedBinarySensorDescription

    def __init__(
        self,
        coordinator: IntergasXceedDataUpdateCoordinator,
        entry: ConfigEntry,
        description: IntergasXceedBinarySensorDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.unique_id or coordinator.api.host}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        """Return whether the entity is currently on."""
        value = _first_value(self.coordinator.data, *self.entity_description.value_paths)
        return _coerce_bool(value)


def _coerce_bool(value: Any) -> bool | None:
    """Convert common API values to booleans."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on", "enabled", "connected", "running", "busy"}:
            return True
        if lowered in {"0", "false", "no", "off", "disabled", "disconnected", "idle"}:
            return False
    return None
