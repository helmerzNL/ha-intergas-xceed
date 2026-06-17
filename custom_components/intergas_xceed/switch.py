"""Switch platform exposing Intergas XCeed scenes (operating modes)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SCENE_DEFAULT_DURATIONS
from .coordinator import IntergasXceedDataUpdateCoordinator, XceedScene
from .entity import IntergasXceedEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the scene switch entities."""
    coordinator: IntergasXceedDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        IntergasXceedSceneSwitch(coordinator, scene.name)
        for scene in coordinator.data.scenes
    )


class IntergasXceedSceneSwitch(IntergasXceedEntity, SwitchEntity):
    """A switch that activates or deactivates a heatapp! scene."""

    def __init__(
        self, coordinator: IntergasXceedDataUpdateCoordinator, scene_name: str
    ) -> None:
        """Initialise the scene switch."""
        super().__init__(coordinator)
        self._scene_name = scene_name
        self._attr_unique_id = f"{self._serial}_scene_{scene_name.lower()}"
        self._attr_name = f"{scene_name} mode"

    @property
    def _scene(self) -> XceedScene | None:
        for scene in self.coordinator.data.scenes:
            if scene.name == self._scene_name:
                return scene
        return None

    @property
    def available(self) -> bool:
        return super().available and self._scene is not None

    @property
    def is_on(self) -> bool | None:
        scene = self._scene
        return scene.active if scene else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Activate the scene."""
        duration = SCENE_DEFAULT_DURATIONS.get(self._scene_name, 1)
        await self.coordinator.api.async_set_scene(self._scene_name, True, duration)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Deactivate the scene."""
        await self.coordinator.api.async_set_scene(self._scene_name, False, 0)
        await self.coordinator.async_request_refresh()
