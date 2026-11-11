"""Schluter DITRA-HEAT-E-WiFi integration (self-healing)."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .api import SchluterApi
from .const import DOMAIN
from .guard import LoginGuard
from .coordinator import SchluterCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.CLIMATE, Platform.SENSOR]

STORAGE_KEY = f"{DOMAIN}.login_guard"
STORAGE_VERSION = 1
SAVE_DELAY = 5

# Accept the old YAML block so existing setups migrate automatically.
CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_USERNAME): cv.string,
                vol.Required(CONF_PASSWORD): cv.string,
            },
            extra=vol.ALLOW_EXTRA,
        )
    },
    extra=vol.ALLOW_EXTRA,
)

type SchluterConfigEntry = ConfigEntry[SchluterCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Import a legacy `schluter:` YAML block into a config entry."""
    if DOMAIN in config:
        conf = config[DOMAIN]
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": SOURCE_IMPORT},
                data={
                    CONF_EMAIL: conf[CONF_USERNAME],
                    CONF_PASSWORD: conf[CONF_PASSWORD],
                },
            )
        )
    return True


async def async_get_guard(hass: HomeAssistant, email: str) -> LoginGuard:
    """Return the account's login guard, shared across setup retries and
    reloads and persisted across restarts."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if "store" not in domain_data:
        store: Store[dict] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        domain_data["store"] = store
        domain_data["states"] = (await store.async_load()) or {}
        domain_data["guards"] = {}
    store = domain_data["store"]
    states: dict = domain_data["states"]
    guards: dict[str, LoginGuard] = domain_data["guards"]
    key = email.strip().lower()
    if key not in guards:

        def _save() -> None:
            states[key] = guards[key].as_dict()
            store.async_delay_save(lambda: states, SAVE_DELAY)

        guards[key] = LoginGuard(states.get(key), on_change=_save)
    return guards[key]


async def async_setup_entry(hass: HomeAssistant, entry: SchluterConfigEntry) -> bool:
    api = SchluterApi(
        async_get_clientsession(hass),
        entry.data[CONF_EMAIL],
        entry.data[CONF_PASSWORD],
        guard=await async_get_guard(hass, entry.data[CONF_EMAIL]),
    )
    coordinator = SchluterCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SchluterConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
