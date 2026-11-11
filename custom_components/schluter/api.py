"""Self-healing async client for the Schluter DITRA-HEAT-E-WiFi cloud API.

The built-in Home Assistant integration logs in once at startup and never
again, so a single expired session leaves the thermostats unavailable until
the next restart. This client keeps the credentials and transparently logs
in again whenever the cloud answers 401 Unauthorized, then retries the call.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Any

from aiohttp import ClientError, ClientSession

from .const import (
    API_APPLICATION_ID,
    API_AUTH_URL,
    API_THERMOSTAT_URL,
    API_THERMOSTATS_URL,
    MIN_LOGIN_INTERVAL,
    REGULATION_MODE_MANUAL,
    REQUEST_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


class SchluterError(Exception):
    """Generic Schluter API error (network, 5xx, unexpected payload)."""


class SchluterAuthError(SchluterError):
    """The email/password was rejected by the Schluter cloud."""


class _SessionExpired(SchluterError):
    """Internal: the current session id was rejected (HTTP 401)."""


def _temp(value: Any) -> float | None:
    """Convert the API's hundredths of a degree Celsius to °C (0.5 steps)."""
    if value is None:
        return None
    return round((value / 100) * 2) / 2


@dataclass
class Thermostat:
    """Snapshot of one thermostat as reported by the cloud."""

    serial_number: str
    name: str
    group_name: str | None
    temperature: float | None
    set_point_temp: float | None
    min_temp: float | None
    max_temp: float | None
    regulation_mode: int | None
    is_heating: bool
    is_online: bool
    load_measured_watt: int | None
    sw_version: str | None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Thermostat:
        return cls(
            serial_number=str(data["SerialNumber"]),
            name=data.get("Room") or str(data["SerialNumber"]),
            group_name=data.get("GroupName"),
            temperature=_temp(data.get("Temperature")),
            set_point_temp=_temp(data.get("SetPointTemp")),
            min_temp=_temp(data.get("MinTemp")),
            max_temp=_temp(data.get("MaxTemp")),
            regulation_mode=data.get("RegulationMode"),
            is_heating=bool(data.get("Heating")),
            is_online=bool(data.get("Online", True)),
            load_measured_watt=data.get("LoadMeasuredWatt"),
            sw_version=data.get("SWVersion"),
        )


class SchluterApi:
    """Schluter cloud client with automatic re-login."""

    def __init__(self, session: ClientSession, email: str, password: str) -> None:
        self._session = session
        self._email = email
        self._password = password
        self._session_id: str | None = None
        self._last_login: datetime | None = None
        self._login_lock = asyncio.Lock()
        self.login_count = 0

    # ------------------------------------------------------------------ auth

    async def async_login(self) -> None:
        """Log in and store a fresh session id."""
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.post(
                    API_AUTH_URL,
                    json={
                        "Email": self._email,
                        "Password": self._password,
                        "Application": API_APPLICATION_ID,
                    },
                ) as resp:
                    if resp.status == 401:
                        raise SchluterAuthError("Invalid email or password")
                    if resp.status != 200:
                        raise SchluterError(
                            f"Login failed: HTTP {resp.status}"
                        )
                    data = await resp.json(content_type=None)
        except (ClientError, TimeoutError) as err:
            raise SchluterError(f"Cannot reach Schluter cloud: {err}") from err

        session_id = (data or {}).get("SessionId") or ""
        if not session_id:
            code = (data or {}).get("ErrorCode")
            if code in (1, 2):
                raise SchluterAuthError("Invalid email or password")
            raise SchluterError(f"Login returned no session (ErrorCode {code})")

        self._session_id = session_id
        self._last_login = datetime.now(timezone.utc)
        self.login_count += 1
        _LOGGER.debug("Logged in to Schluter cloud (login #%s)", self.login_count)

    async def _async_relogin(self, rejected_session: str | None) -> None:
        """Log in again, unless another task already did, or we just did."""
        async with self._login_lock:
            if self._session_id and self._session_id != rejected_session:
                return  # someone else refreshed the session meanwhile
            if (
                self._last_login is not None
                and datetime.now(timezone.utc) - self._last_login < MIN_LOGIN_INTERVAL
            ):
                # A session we created moments ago is already rejected.
                # Don't hammer the login endpoint; let the next poll retry.
                raise SchluterError(
                    "Schluter rejected a session that was created less than "
                    f"{int(MIN_LOGIN_INTERVAL.total_seconds() // 60)} minutes ago; "
                    "will retry later"
                )
            _LOGGER.info("Schluter session expired; logging in again")
            await self.async_login()

    # --------------------------------------------------------------- requests

    async def _request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        """Make a call, re-logging in once on 401."""
        if self._session_id is None:
            async with self._login_lock:
                if self._session_id is None:
                    await self.async_login()

        for attempt in (1, 2):
            session_id = self._session_id
            try:
                return await self._raw_request(method, url, session_id, params, json)
            except _SessionExpired:
                if attempt == 2:
                    raise SchluterError(
                        "Schluter rejected the new session as well (HTTP 401)"
                    ) from None
                await self._async_relogin(session_id)
        raise SchluterError("unreachable")

    async def _raw_request(
        self,
        method: str,
        url: str,
        session_id: str | None,
        params: dict[str, Any] | None,
        json: dict[str, Any] | None,
    ) -> Any:
        query = {"sessionId": session_id, **(params or {})}
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.request(
                    method, url, params=query, json=json
                ) as resp:
                    if resp.status == 401:
                        raise _SessionExpired()
                    if resp.status != 200:
                        raise SchluterError(f"HTTP {resp.status} from {url}")
                    return await resp.json(content_type=None)
        except (ClientError, TimeoutError) as err:
            raise SchluterError(f"Cannot reach Schluter cloud: {err}") from err

    # ---------------------------------------------------------------- public

    async def async_get_thermostats(self) -> dict[str, Thermostat]:
        data = await self._request("GET", API_THERMOSTATS_URL)
        thermostats: dict[str, Thermostat] = {}
        try:
            for group in data.get("Groups", []):
                for tdata in group.get("Thermostats", []):
                    stat = Thermostat.from_api(tdata)
                    thermostats[stat.serial_number] = stat
        except (AttributeError, KeyError, TypeError) as err:
            raise SchluterError(f"Unexpected thermostat payload: {err}") from err
        return thermostats

    async def async_set_temperature(self, serial: str, temperature: float) -> None:
        """Set a manual target temperature (°C)."""
        data = await self._request(
            "POST",
            API_THERMOSTAT_URL,
            params={"serialnumber": serial},
            json={
                "ManualTemperature": int(round(temperature * 100)),
                "RegulationMode": REGULATION_MODE_MANUAL,
                "VacationEnabled": False,
            },
        )
        if isinstance(data, dict) and data.get("Success") is False:
            raise SchluterError("Schluter refused the temperature change")

    async def async_set_regulation_mode(self, serial: str, mode: int) -> None:
        data = await self._request(
            "POST",
            API_THERMOSTAT_URL,
            params={"serialnumber": serial},
            json={"SerialNumber": serial, "RegulationMode": mode},
        )
        if isinstance(data, dict) and data.get("Success") is False:
            raise SchluterError("Schluter refused the mode change")
