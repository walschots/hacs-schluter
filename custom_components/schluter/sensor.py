"""Power sensor for Schluter floor heating."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SchluterConfigEntry
from .entity import SchluterEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SchluterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(SchluterPowerSensor(coordinator, s) for s in coordinator.data)


class SchluterPowerSensor(SchluterEntity, SensorEntity):
    """Heating power: the measured floor load while heating, else 0 W."""

    _attr_has_entity_name = True
    _attr_translation_key = "heating_power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT

    def __init__(self, coordinator, serial: str) -> None:
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{serial}_heating_power"

    @property
    def native_value(self) -> int | None:
        stat = self.thermostat
        if stat is None:
            return None
        if not stat.is_heating:
            return 0
        return stat.load_measured_watt
