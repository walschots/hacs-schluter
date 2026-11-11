"""Self-healing async client for the Schluter DITRA-HEAT-E-WiFi cloud API.

The built-in Home Assistant integration logs in once at startup and never
again, so a single expired session leaves the thermostats unavailable until
the next restart. This client keeps the credentials and transparently logs
in again whenever the cloud answers 401 Unauthorized, then retries the call.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from typing import Any

from aiohttp import ClientError, ClientSession

from .const import (
    API_APPLICATION_ID,
    API_AUTH_URL,
    API_THERMOSTAT_URL,
    API_THERMOSTATS_URL,
    REGULATION_MODE_MANUAL,
    REQUEST_TIMEOUT,
)
from .guard import LoginGuard

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
    """Schluter cloud client with automatic, rate-limited re-login."""

    def __init__(
        self,
        session: ClientSession,
        email: str,
        password: str,
        guard: LoginGuard | None = None,
    ) -> None:
        self._session = session
        self._email = email
        self._password = password
        # No guard = unthrottled (only for a user-initiated login check).
        self._guard = guard
        self._session_id: str | None = None
        self._login_lock = asyncio.Lock()
        self.login_count = 0

    # ------------------------------------------------------------------ auth

    async def async_login(self) -> None:
        """Log in once and store a fresh session id (no throttling here)."""
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
                        raise SchluterError(f"Login failed: HTTP {resp.status}")
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
        self.login_count += 1
        _LOGGER.debug("Logged in to Schluter cloud (login #%s)", self.login_count)

    async def _async_ensure_session(self) -> bool:
        """Make sure we hold a session. Returns True if a new one was created.

        Every login goes through the guard, so no matter how often HA polls or
        retries setup, Schluter sees at most one login per backoff window.
        """
        async with self._login_lock:
            if self._session_id is not None:
                return False  # another task logged in meanwhile
            guard = self._guard
            if guard is not None and (wait := guard.wait_time()) is not None:
                raise SchluterError(
                    "Holding off on Schluter logins to protect the account; "
                    f"next attempt in {max(1, round(wait.total_seconds() / 60))} min"
                )
            _LOGGER.info("Logging in to Schluter cloud")
            try:
                await self.async_login()
            except SchluterAuthError:
                if guard is not None:
                    guard.login_failed(rejected=True)
                raise
            except SchluterError:
                if guard is not None:
                    guard.login_failed(rejected=False)
                raise
            if guard is not None:
                guard.login_succeeded()
            return True

    def _session_rejected(self, fresh: bool) -> None:
        """Handle a 401. Raise if the session was brand new."""
        if not fresh:
            _LOGGER.info("Schluter session expired; will log in again")
            return
        guard = self._guard
        if guard is not None:
            guard.login_failed(rejected=True)
            if guard.should_reauth:
                raise SchluterAuthError(
                    "Schluter keeps rejecting new sessions; stopped logging in "
                    "until you re-enter the password"
                )
            wait = guard.wait_time()
            mins = max(1, round(wait.total_seconds() / 60)) if wait else 0
            raise SchluterError(
                "Schluter rejected a brand-new session (possible outage or "
                f"account lock); next login attempt in {mins} min"
            )
        raise SchluterError("Schluter rejected a brand-new session (HTTP 401)")

    # --------------------------------------------------------------- requests

    async def _request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        """Make a call, logging in (rate-limited) once if the session expired."""
        for _attempt in (1, 2):
            fresh = await self._async_ensure_session()
            session_id = self._session_id
            try:
                result = await self._raw_request(method, url, session_id, params, json)
            except _SessionExpired:
                # Drop the dead session so polls don't keep sending it.
                if self._session_id == session_id:
                    self._session_id = None
                self._session_rejected(fresh)
                continue
            if self._guard is not None:
                self._guard.data_succeeded()
            return result
        raise SchluterError("Schluter rejected the session again (HTTP 401)")

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
