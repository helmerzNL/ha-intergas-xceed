"""Shared entity helpers for Intergas XCeed."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import IntergasXceedDataUpdateCoordinator


class IntergasXceedCoordinatorEntity(CoordinatorEntity[IntergasXceedDataUpdateCoordinator]):
    """Base entity for the integration."""

    _attr_has_entity_name = True

    @property
    def device_info(self) -> DeviceInfo:
        """Return metadata about the Intergas device."""
        system_information = self.coordinator.data.get("system_information", {})
        model = _first_value(
            system_information,
            ("model",),
            ("product",),
            ("device_type",),
            ("type",),
        )
        serial_number = _first_value(
            system_information,
            ("serial",),
            ("serialnumber",),
            ("serial_number",),
            ("mac",),
        )
        sw_version = _first_value(
            system_information,
            ("firmware",),
            ("firmware_version",),
            ("version",),
            ("swversion",),
        )

        identifier = serial_number or self.coordinator.api.host
        return DeviceInfo(
            identifiers={(DOMAIN, str(identifier))},
            configuration_url=f"http://{self.coordinator.api.host}",
            manufacturer=MANUFACTURER,
            model=str(model) if model else "XCeed",
            name=f"Intergas XCeed ({self.coordinator.api.host})",
            serial_number=str(serial_number) if serial_number else None,
            sw_version=str(sw_version) if sw_version else None,
        )


def _first_value(payload: dict[str, Any], *paths: tuple[str, ...]) -> Any | None:
    """Return the first available nested value for the provided paths."""
    for path in paths:
        value = _nested_value(payload, path)
        if value not in (None, ""):
            return value
    return None


def _nested_value(payload: dict[str, Any], path: tuple[str, ...]) -> Any | None:
    """Look up a nested value by path."""
    current: Any = payload
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current
