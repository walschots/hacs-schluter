"""Climate entities for Schluter DITRA-HEAT-E-WiFi thermostats."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SchluterConfigEntry
from .api import SchluterError
from .const import (
    PRESET_MANUAL,
    PRESET_SCHEDULE,
    REGULATION_MODE_SCHEDULE,
)
from .entity import SchluterEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SchluterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        SchluterThermostat(coordinator, serial) for serial in coordinator.data
    )


class SchluterThermostat(SchluterEntity, ClimateEntity):
    """A floor-heating thermostat."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 0.5
    _attr_hvac_modes = [HVACMode.HEAT]
    _attr_hvac_mode = HVACMode.HEAT
    _attr_preset_modes = [PRESET_SCHEDULE, PRESET_MANUAL]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
    )

    def __init__(self, coordinator, serial: str) -> None:
        super().__init__(coordinator, serial)
        # Same unique_id as the built-in integration, so the existing
        # entity ids, names and areas are kept.
        self._attr_unique_id = serial

    @property
    def current_temperature(self) -> float | None:
        return self.thermostat.temperature if self.thermostat else None

    @property
    def target_temperature(self) -> float | None:
        return self.thermostat.set_point_temp if self.thermostat else None

    @property
    def min_temp(self) -> float:
        if self.thermostat and self.thermostat.min_temp is not None:
            return self.thermostat.min_temp
        return 5.0

    @property
    def max_temp(self) -> float:
        if self.thermostat and self.thermostat.max_temp is not None:
            return self.thermostat.max_temp
        return 40.0

    @property
    def hvac_action(self) -> HVACAction | None:
        if not self.thermostat:
            return None
        return HVACAction.HEATING if self.thermostat.is_heating else HVACAction.IDLE

    @property
    def preset_mode(self) -> str | None:
        if not self.thermostat:
            return None
        if self.thermostat.regulation_mode == REGULATION_MODE_SCHEDULE:
            return PRESET_SCHEDULE
        return PRESET_MANUAL

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Only heat is supported; nothing to change."""

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        try:
            await self.coordinator.api.async_set_temperature(self._serial, temperature)
        except SchluterError as err:
            raise HomeAssistantError(f"Schluter: {err}") from err
        await self.coordinator.async_request_refresh()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        try:
            if preset_mode == PRESET_SCHEDULE:
                await self.coordinator.api.async_set_regulation_mode(
                    self._serial, REGULATION_MODE_SCHEDULE
                )
            else:
                # Manual = hold the current target temperature.
                target = self.target_temperature or 21.0
                await self.coordinator.api.async_set_temperature(self._serial, target)
        except SchluterError as err:
            raise HomeAssistantError(f"Schluter: {err}") from err
        await self.coordinator.async_request_refresh()
