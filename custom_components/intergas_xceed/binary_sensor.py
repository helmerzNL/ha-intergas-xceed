"""Binary sensor platform for Intergas XCeed."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import IntergasXceedDataUpdateCoordinator, XceedRoom
from .entity import IntergasXceedEntity


@dataclass(frozen=True, kw_only=True)
class XceedRoomBinaryDescription(BinarySensorEntityDescription):
    """Describes a per-room binary sensor."""

    value_fn: Callable[[XceedRoom], bool]


ROOM_BINARY_SENSORS: tuple[XceedRoomBinaryDescription, ...] = (
    XceedRoomBinaryDescription(
        key="cooling",
        name="Cooling",
        device_class=BinarySensorDeviceClass.COLD,
        value_fn=lambda room: room.cooling,
    ),
    XceedRoomBinaryDescription(
        key="window_open",
        name="Window",
        device_class=BinarySensorDeviceClass.WINDOW,
        value_fn=lambda room: room.window_open,
    ),
    XceedRoomBinaryDescription(
        key="comfort_mode",
        name="Comfort mode",
        value_fn=lambda room: bool(room.comfort_mode),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensor entities."""
    coordinator: IntergasXceedDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[BinarySensorEntity] = [IntergasXceedProblemSensor(coordinator)]
    for room in coordinator.data.rooms:
        if room.is_dhw:
            continue
        for description in ROOM_BINARY_SENSORS:
            entities.append(
                IntergasXceedRoomBinarySensor(
                    coordinator, room.id, room.name, description
                )
            )

    async_add_entities(entities)


class IntergasXceedProblemSensor(IntergasXceedEntity, BinarySensorEntity):
    """Indicates whether the system currently reports an error."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_name = "System error"

    def __init__(self, coordinator: IntergasXceedDataUpdateCoordinator) -> None:
        """Initialise the problem sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._serial}_system_error"

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.errors)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        return {"errors": self.coordinator.data.errors}


class IntergasXceedRoomBinarySensor(IntergasXceedEntity, BinarySensorEntity):
    """A per-room binary sensor."""

    entity_description: XceedRoomBinaryDescription

    def __init__(
        self,
        coordinator: IntergasXceedDataUpdateCoordinator,
        room_id: int,
        room_name: str,
        description: XceedRoomBinaryDescription,
    ) -> None:
        """Initialise the room binary sensor."""
        super().__init__(coordinator)
        self._room_id = room_id
        self.entity_description = description
        self._attr_unique_id = f"{self._serial}_{room_id}_{description.key}"
        self._attr_name = f"{room_name} {description.name}"

    @property
    def _room(self) -> XceedRoom | None:
        for room in self.coordinator.data.rooms:
            if room.id == self._room_id:
                return room
        return None

    @property
    def available(self) -> bool:
        return super().available and self._room is not None

    @property
    def is_on(self) -> bool | None:
        room = self._room
        if room is None:
            return None
        return self.entity_description.value_fn(room)
