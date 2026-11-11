"""Config flow for Schluter DITRA-HEAT-E-WiFi."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SchluterApi, SchluterAuthError, SchluterError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {vol.Required(CONF_EMAIL): str, vol.Required(CONF_PASSWORD): str}
)


class SchluterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up with the same email/password as the Schluter app."""

    VERSION = 1

    async def _async_validate(self, email: str, password: str) -> str | None:
        api = SchluterApi(async_get_clientsession(self.hass), email, password)
        try:
            await api.async_login()
            await api.async_get_thermostats()
        except SchluterAuthError:
            return "invalid_auth"
        except SchluterError as err:
            _LOGGER.warning("Schluter validation failed: %s", err)
            return "cannot_connect"
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error validating Schluter login")
            return "unknown"
        # The user just proved the login works: clear any backoff so the
        # integration can start straight away.
        from . import async_get_guard  # noqa: PLC0415

        (await async_get_guard(self.hass, email)).reset()
        return None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            await self.async_set_unique_id(email.lower())
            self._abort_if_unique_id_configured()
            if (error := await self._async_validate(email, user_input[CONF_PASSWORD])) is None:
                return self.async_create_entry(
                    title=email,
                    data={CONF_EMAIL: email, CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )
            errors["base"] = error
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_import(self, import_data: dict[str, Any]) -> ConfigFlowResult:
        """Migrate the legacy `schluter:` YAML block (no validation, so a
        temporary cloud outage doesn't block the migration)."""
        email = import_data[CONF_EMAIL].strip()
        await self.async_set_unique_id(email.lower())
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=email,
            data={CONF_EMAIL: email, CONF_PASSWORD: import_data[CONF_PASSWORD]},
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            error = await self._async_validate(
                entry.data[CONF_EMAIL], user_input[CONF_PASSWORD]
            )
            if error is None:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
            errors["base"] = error
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={"email": entry.data[CONF_EMAIL]},
            errors=errors,
        )
