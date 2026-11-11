"""Base entity for Schluter thermostats."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Thermostat
from .const import DOMAIN
from .coordinator import SchluterCoordinator


class SchluterEntity(CoordinatorEntity[SchluterCoordinator]):
    """Common device info and availability."""

    def __init__(self, coordinator: SchluterCoordinator, serial: str) -> None:
        super().__init__(coordinator)
        self._serial = serial
        stat = coordinator.data[serial]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial)},
            name=stat.name,
            manufacturer="Schluter Systems",
            model="DITRA-HEAT-E-WiFi",
            serial_number=serial,
            sw_version=stat.sw_version,
            suggested_area=stat.group_name,
        )

    @property
    def thermostat(self) -> Thermostat | None:
        return self.coordinator.data.get(self._serial) if self.coordinator.data else None

    @property
    def available(self) -> bool:
        stat = self.thermostat
        return super().available and stat is not None and stat.is_online
