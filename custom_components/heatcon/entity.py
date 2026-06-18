"""Shared entity helpers for HeatCon."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import HeatconDataUpdateCoordinator


class HeatconEntity(CoordinatorEntity[HeatconDataUpdateCoordinator]):
    """Base entity providing shared device info."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: HeatconDataUpdateCoordinator) -> None:
        """Initialise the base entity."""
        super().__init__(coordinator)

    @property
    def _serial(self) -> str:
        """Return the device serial number or a host fallback."""
        version = self.coordinator.data.version
        return str(
            version.get("sysinfo_serial_number") or self.coordinator.api.host
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return metadata about the Intergas device."""
        version = self.coordinator.data.version
        return DeviceInfo(
            identifiers={(DOMAIN, self._serial)},
            configuration_url=f"http://{self.coordinator.api.host}",
            manufacturer=MANUFACTURER,
            model=version.get("sysinfo_derivat") or "HeatCon",
            name="HeatCon",
            serial_number=version.get("sysinfo_serial_number"),
            sw_version=version.get("server"),
            hw_version=version.get("sysinfo_hw_index"),
        )
