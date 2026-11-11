"""Polling coordinator for Schluter thermostats."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SchluterApi, SchluterAuthError, SchluterError, Thermostat
from .const import DOMAIN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)


class SchluterCoordinator(DataUpdateCoordinator[dict[str, Thermostat]]):
    """Fetch all thermostats once a minute; the API client heals sessions."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: SchluterApi) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.api = api

    async def _async_update_data(self) -> dict[str, Thermostat]:
        try:
            return await self.api.async_get_thermostats()
        except SchluterAuthError as err:
            # Password really is wrong/changed: ask the user in the UI.
            raise ConfigEntryAuthFailed(str(err)) from err
        except SchluterError as err:
            raise UpdateFailed(str(err)) from err
