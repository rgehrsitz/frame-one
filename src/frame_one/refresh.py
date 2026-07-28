"""Retry policy and cadence rules for one scheduled refresh round.

A refresh round asks several independent providers for fresh values.  A single
slow or failing source must not consume the whole round's budget, and it must
not stop the other tiles from redrawing, so every attempt runs under one shared
wall-clock deadline and each provider carries its own retry policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time as clock_time, timedelta
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Callable


UNAVAILABLE: dict[str, object] = {"state": "unavailable", "data": {}}

# How long a tile may keep showing its last successful value before the screen
# stops claiming to know.  Each is a little longer than the provider's own
# refresh interval, so an ordinary blip never blanks a tile.
STALE_AFTER_SECONDS: dict[str, int] = {
    "weather": 5400,  # hourly refresh
    "gmail": 1800,  # 15-minute refresh
    "codex": 3600,  # 15-minute refresh
    "claude": 10800,  # status-line capture: only appears while you are working
}

# The OAuth reader is polled every round, so a value older than a few rounds
# means the endpoint is genuinely failing rather than simply idle.  It gets a
# much shorter window than the event-driven status-line capture.
CLAUDE_OAUTH_STALE_SECONDS = 1800

# Overnight the panel is not being read, so it redraws hourly instead of every
# five minutes to spare the e-paper and the Pi's radio.
QUIET_HOURS_START = clock_time(0, 0)
QUIET_HOURS_END = clock_time(6, 0)
QUIET_HOURS_INTERVAL = timedelta(hours=1)


@dataclass(frozen=True)
class RetryPolicy:
    """How hard to try one provider before its tile goes to ``unavailable``.

    ``attempts`` is deliberately per-provider rather than global: a provider
    that reads a local file cannot produce a different answer two seconds
    later, so retrying it only burns the round's deadline.
    """

    attempts: int = 1
    backoff_seconds: float = 2.0

    def delay_before(self, attempt: int) -> float:
        """Seconds to wait before ``attempt`` (1-based); the first is immediate."""
        if attempt <= 1:
            return 0.0
        return self.backoff_seconds * (2 ** (attempt - 2))


# A local file read either works or it does not; a network call deserves a
# second chance, and the App Server occasionally loses a backend round trip.
LOCAL_FILE = RetryPolicy(attempts=1)
NETWORK = RetryPolicy(attempts=3, backoff_seconds=2.0)
APP_SERVER = RetryPolicy(attempts=2, backoff_seconds=3.0)


def fetch_with_retry(
    fetch: Callable[[], dict[str, object]],
    *,
    policy: RetryPolicy = NETWORK,
    deadline: float | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, object]:
    """Return the provider's first ``ok`` envelope, or ``unavailable``.

    ``deadline`` is a ``monotonic()`` timestamp shared by the whole round.  A
    provider that raises is treated exactly like one reporting ``unavailable``:
    the renderer shows an em dash rather than a stale or invented value.
    """
    last: dict[str, object] | None = None
    for attempt in range(1, max(1, policy.attempts) + 1):
        pause = policy.delay_before(attempt)
        if pause and _would_exceed(deadline, monotonic, pause):
            break
        if pause:
            sleep(pause)
        if deadline is not None and monotonic() >= deadline:
            break
        try:
            state = fetch()
        except Exception:
            # Providers are expected to normalize their own failures; treat a
            # leaked exception as one more failed attempt rather than letting
            # it abort every remaining tile in the round.
            state = None
        if isinstance(state, dict):
            last = state
            if state.get("state") == "ok":
                return state
            if state.get("state") == "needs_setup":
                # Terminal: no amount of retrying authorizes a device. Return
                # now so the round's budget goes to sources that might recover.
                return state
    return last if last is not None else dict(UNAVAILABLE)


def _would_exceed(deadline: float | None, monotonic: Callable[[], float], pause: float) -> bool:
    return deadline is not None and monotonic() + pause >= deadline


def stamp(
    state: dict[str, object],
    *,
    name: str,
    now: datetime,
    stale_after_seconds: int | None = None,
) -> dict[str, object]:
    """Attach the documented envelope fields to a successful fetch.

    ``stale_after_seconds`` overrides the per-provider default, because the same
    tile can be fed by sources with very different freshness characteristics.
    """
    if state.get("state") != "ok":
        return state
    stamped = dict(state)
    stamped["updated_at"] = now.isoformat()
    stamped["stale_after_seconds"] = (
        stale_after_seconds if stale_after_seconds is not None else STALE_AFTER_SECONDS.get(name, 3600)
    )
    return stamped


class StateCache:
    """The last successful envelope for each provider.

    Holding a value across a failed refresh is what keeps a momentary Wi-Fi
    blip from blanking a tile for five minutes.  The value is only reused while
    it is younger than its own ``stale_after_seconds``; past that the screen
    stops claiming to know and the tile goes to an em dash.
    """

    def __init__(self, path: Path | None) -> None:
        self._path = path
        self._entries: dict[str, Any] = {}
        if path is not None:
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self._entries = loaded
            except (OSError, ValueError):
                self._entries = {}

    def remember(self, name: str, state: dict[str, object]) -> None:
        self._entries[name] = state

    def recall(self, name: str, now: datetime) -> dict[str, object] | None:
        entry = self._entries.get(name)
        if not isinstance(entry, dict) or entry.get("state") not in ("ok", "stale"):
            return None
        try:
            updated_at = datetime.fromisoformat(str(entry["updated_at"]))
            window = float(entry["stale_after_seconds"])
        except (KeyError, TypeError, ValueError):
            return None
        if updated_at.tzinfo is None or (now - updated_at).total_seconds() >= window:
            return None
        recalled = dict(entry)
        recalled["state"] = "stale"
        return recalled

    def save(self) -> None:
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=self._path.parent, prefix=f".{self._path.name}.", delete=False
            ) as handle:
                json.dump(self._entries, handle, indent=2, sort_keys=True)
                handle.write("\n")
                temporary = Path(handle.name)
            os.replace(temporary, self._path)
        except OSError:
            pass


def resolve(
    name: str,
    fetch: Callable[[], dict[str, object]],
    *,
    cache: StateCache,
    now: datetime,
    policy: RetryPolicy = NETWORK,
    deadline: float | None = None,
    stale_after_seconds: int | None = None,
) -> dict[str, object]:
    """Fetch with retries, else fall back to a last-known-good value."""
    state = fetch_with_retry(fetch, policy=policy, deadline=deadline)
    if state.get("state") == "ok":
        stamped = stamp(state, name=name, now=now, stale_after_seconds=stale_after_seconds)
        cache.remember(name, stamped)
        return stamped
    recalled = cache.recall(name, now)
    if recalled is not None:
        return recalled
    # Nothing cached: keep the provider's own verdict so the operator can tell
    # "never authorized" apart from "the network is down".
    return state if isinstance(state, dict) else dict(UNAVAILABLE)


def is_quiet_hour(moment: datetime) -> bool:
    """True between midnight and 6AM local time."""
    return QUIET_HOURS_START <= moment.time() < QUIET_HOURS_END


def is_due(moment: datetime, last_render: datetime | None) -> bool:
    """Decide whether a timer tick should render.

    The timer fires every five minutes around the clock; this collapses the
    overnight ticks to one an hour so all cadence logic lives in one place
    instead of in two systemd units.
    """
    if last_render is None:
        return True
    if not is_quiet_hour(moment):
        return True
    return moment - last_render >= QUIET_HOURS_INTERVAL
