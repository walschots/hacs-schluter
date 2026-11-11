"""Login guard: rate-limits and backs off logins to the Schluter cloud.

One guard exists per Schluter account and outlives the API client, so Home
Assistant's own setup retries (which build a fresh client every time, as often
as every 80 seconds) can't bypass it. Its state is persisted, so a restart
doesn't reset it either.

Rules:
- At most one login attempt per backoff window. The window starts at
  5 minutes and grows to 15, 30 and 60 minutes after consecutive failures.
- A failure is a login that errors, or a brand-new session that Schluter
  rejects straight away (a sign of a lockout or a cloud problem).
- After MAX_REJECTIONS rejections in a row, the guard asks for
  re-authentication instead of trying again, so HA stops logging in.
- Any successful data call resets the failure counters.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

BACKOFF_STEPS = (
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(minutes=30),
    timedelta(minutes=60),
)
MAX_REJECTIONS = 4


def _now() -> datetime:
    return datetime.now(timezone.utc)


class LoginGuard:
    """Shared, persistent login throttle for one Schluter account."""

    def __init__(
        self,
        state: dict[str, Any] | None = None,
        on_change: Callable[[], None] | None = None,
        now: Callable[[], datetime] = _now,
    ) -> None:
        state = state or {}
        nxt = state.get("next_allowed")
        self.next_allowed: datetime | None = (
            datetime.fromisoformat(nxt) if nxt else None
        )
        self.failures: int = int(state.get("failures", 0))
        self.rejections: int = int(state.get("rejections", 0))
        self._on_change = on_change
        self._now = now

    # ----------------------------------------------------------- persistence

    def as_dict(self) -> dict[str, Any]:
        return {
            "next_allowed": self.next_allowed.isoformat() if self.next_allowed else None,
            "failures": self.failures,
            "rejections": self.rejections,
        }

    def _changed(self) -> None:
        if self._on_change is not None:
            self._on_change()

    # ----------------------------------------------------------------- query

    def wait_time(self) -> timedelta | None:
        """Time left before the next login is allowed, or None if allowed now."""
        if self.next_allowed is None:
            return None
        left = self.next_allowed - self._now()
        return left if left > timedelta(0) else None

    @property
    def should_reauth(self) -> bool:
        return self.rejections >= MAX_REJECTIONS

    # ---------------------------------------------------------------- record

    def _window(self) -> timedelta:
        return BACKOFF_STEPS[min(self.failures, len(BACKOFF_STEPS) - 1)]

    def login_succeeded(self) -> None:
        """A session was issued. Keep the current window before the next login."""
        self.next_allowed = self._now() + self._window()
        self._changed()

    def login_failed(self, rejected: bool) -> None:
        """A login attempt or a brand-new session failed; widen the window."""
        self.failures += 1
        if rejected:
            self.rejections += 1
        self.next_allowed = self._now() + self._window()
        self._changed()

    def data_succeeded(self) -> None:
        """The cloud answered normally: everything is healthy again."""
        if self.failures or self.rejections:
            self.failures = 0
            self.rejections = 0
            self._changed()

    def reset(self) -> None:
        """Forget all history (after the user re-enters their password)."""
        self.next_allowed = None
        self.failures = 0
        self.rejections = 0
        self._changed()
