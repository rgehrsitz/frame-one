from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from frame_one.refresh import (
    APP_SERVER,
    LOCAL_FILE,
    NETWORK,
    RetryPolicy,
    StateCache,
    fetch_with_retry,
    is_due,
    is_quiet_hour,
    resolve,
    stamp,
)


OK = {"state": "ok", "data": {"unread": 3}}
DOWN = {"state": "unavailable", "data": {}}


class FakeClock:
    """A monotonic clock that only advances when the code under test sleeps."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


class FetchWithRetryTests(unittest.TestCase):
    def test_a_first_attempt_that_succeeds_does_not_sleep(self) -> None:
        clock = FakeClock()
        calls = []

        def fetch() -> dict[str, object]:
            calls.append(1)
            return OK

        state = fetch_with_retry(fetch, policy=NETWORK, sleep=clock.sleep, monotonic=clock.monotonic)

        self.assertEqual(state, OK)
        self.assertEqual(len(calls), 1)
        self.assertEqual(clock.slept, [])

    def test_a_transient_failure_is_retried_and_then_succeeds(self) -> None:
        clock = FakeClock()
        replies = [DOWN, DOWN, OK]

        state = fetch_with_retry(
            lambda: replies.pop(0), policy=NETWORK, sleep=clock.sleep, monotonic=clock.monotonic
        )

        self.assertEqual(state, OK)
        self.assertEqual(clock.slept, [2.0, 4.0])  # exponential backoff

    def test_exhausted_attempts_report_unavailable(self) -> None:
        clock = FakeClock()
        calls = []

        def fetch() -> dict[str, object]:
            calls.append(1)
            return DOWN

        state = fetch_with_retry(fetch, policy=NETWORK, sleep=clock.sleep, monotonic=clock.monotonic)

        self.assertEqual(state, {"state": "unavailable", "data": {}})
        self.assertEqual(len(calls), NETWORK.attempts)

    def test_a_local_file_provider_is_not_retried(self) -> None:
        calls = []

        def fetch() -> dict[str, object]:
            calls.append(1)
            return DOWN

        fetch_with_retry(fetch, policy=LOCAL_FILE)

        self.assertEqual(len(calls), 1, "retrying a local file read only burns the round's budget")

    def test_a_raised_exception_is_treated_as_a_failed_attempt(self) -> None:
        clock = FakeClock()
        calls = []

        def fetch() -> dict[str, object]:
            calls.append(1)
            raise RuntimeError("provider leaked an exception")

        state = fetch_with_retry(
            fetch, policy=APP_SERVER, sleep=clock.sleep, monotonic=clock.monotonic
        )

        self.assertEqual(state, {"state": "unavailable", "data": {}})
        self.assertEqual(len(calls), APP_SERVER.attempts)

    def test_the_round_deadline_stops_further_retries(self) -> None:
        clock = FakeClock()
        calls = []

        def fetch() -> dict[str, object]:
            calls.append(1)
            return DOWN

        # Only one attempt fits: the first backoff would run past the deadline.
        state = fetch_with_retry(
            fetch,
            policy=RetryPolicy(attempts=5, backoff_seconds=10.0),
            deadline=clock.monotonic() + 5.0,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )

        self.assertEqual(state, {"state": "unavailable", "data": {}})
        self.assertEqual(len(calls), 1)
        self.assertEqual(clock.slept, [])

    def test_a_slow_provider_cannot_overrun_the_deadline_with_backoff(self) -> None:
        clock = FakeClock()
        state = fetch_with_retry(
            lambda: DOWN,
            policy=RetryPolicy(attempts=6, backoff_seconds=2.0),
            deadline=clock.monotonic() + 7.0,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )

        self.assertEqual(state["state"], "unavailable")
        self.assertLess(sum(clock.slept), 7.0)


class CadenceTests(unittest.TestCase):
    def _at(self, hour: int, minute: int = 0) -> datetime:
        return datetime(2026, 7, 28, hour, minute).astimezone()

    def test_quiet_hours_cover_midnight_to_six(self) -> None:
        self.assertTrue(is_quiet_hour(self._at(0, 0)))
        self.assertTrue(is_quiet_hour(self._at(5, 59)))
        self.assertFalse(is_quiet_hour(self._at(6, 0)))
        self.assertFalse(is_quiet_hour(self._at(13, 0)))

    def test_daytime_ticks_always_render(self) -> None:
        moment = self._at(13, 0)
        self.assertTrue(is_due(moment, moment - timedelta(minutes=5)))

    def test_overnight_ticks_collapse_to_hourly(self) -> None:
        moment = self._at(2, 0)
        self.assertFalse(is_due(moment, moment - timedelta(minutes=5)))
        self.assertFalse(is_due(moment, moment - timedelta(minutes=59)))
        self.assertTrue(is_due(moment, moment - timedelta(minutes=60)))

    def test_a_first_ever_run_is_always_due(self) -> None:
        self.assertTrue(is_due(self._at(3, 0), None))


class LastKnownGoodTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "state.json"
        self.now = datetime(2026, 7, 28, 13, 0).astimezone()

    def test_a_successful_fetch_is_stamped_with_the_documented_envelope(self) -> None:
        stamped = stamp(dict(OK), name="gmail", now=self.now)

        self.assertEqual(stamped["updated_at"], self.now.isoformat())
        self.assertEqual(stamped["stale_after_seconds"], 1800)
        self.assertEqual(stamped["state"], "ok")

    def test_a_failed_fetch_falls_back_to_the_last_good_value(self) -> None:
        cache = StateCache(self.path)
        resolve("gmail", lambda: OK, cache=cache, now=self.now, policy=LOCAL_FILE)

        later = self.now + timedelta(minutes=10)
        state = resolve("gmail", lambda: DOWN, cache=cache, now=later, policy=LOCAL_FILE)

        self.assertEqual(state["state"], "stale")
        self.assertEqual(state["data"], OK["data"])

    def test_a_value_past_its_window_is_dropped_rather_than_shown(self) -> None:
        cache = StateCache(self.path)
        resolve("gmail", lambda: OK, cache=cache, now=self.now, policy=LOCAL_FILE)

        stale = self.now + timedelta(seconds=1801)  # gmail window is 1800s
        state = resolve("gmail", lambda: DOWN, cache=cache, now=stale, policy=LOCAL_FILE)

        self.assertEqual(state, {"state": "unavailable", "data": {}})

    def test_a_fresh_success_replaces_the_cached_value(self) -> None:
        cache = StateCache(self.path)
        resolve("gmail", lambda: OK, cache=cache, now=self.now, policy=LOCAL_FILE)

        newer = {"state": "ok", "data": {"unread": 9}}
        state = resolve("gmail", lambda: newer, cache=cache, now=self.now, policy=LOCAL_FILE)

        self.assertEqual(state["data"], {"unread": 9})
        self.assertEqual(state["state"], "ok")

    def test_the_cache_survives_a_restart(self) -> None:
        first = StateCache(self.path)
        resolve("codex", lambda: OK, cache=first, now=self.now, policy=LOCAL_FILE)
        first.save()

        reloaded = StateCache(self.path)
        state = resolve("codex", lambda: DOWN, cache=reloaded, now=self.now, policy=LOCAL_FILE)

        self.assertEqual(state["state"], "stale")

    def test_a_corrupt_cache_file_is_ignored(self) -> None:
        self.path.write_text("{not json", encoding="utf-8")
        cache = StateCache(self.path)

        state = resolve("gmail", lambda: DOWN, cache=cache, now=self.now, policy=LOCAL_FILE)

        self.assertEqual(state, {"state": "unavailable", "data": {}})

    def test_a_source_specific_window_overrides_the_provider_default(self) -> None:
        cache = StateCache(self.path)

        state = resolve(
            "claude",
            lambda: OK,
            cache=cache,
            now=self.now,
            policy=LOCAL_FILE,
            stale_after_seconds=1800,
        )

        # The status-line default for "claude" is 10800; the OAuth reader polls
        # every round and must not keep showing a half-day-old percentage.
        self.assertEqual(state["stale_after_seconds"], 1800)

        past_window = self.now + timedelta(seconds=1801)
        self.assertEqual(
            resolve("claude", lambda: DOWN, cache=cache, now=past_window, policy=LOCAL_FILE),
            {"state": "unavailable", "data": {}},
        )

    def test_an_unauthorized_provider_is_not_retried(self) -> None:
        calls = []

        def fetch() -> dict[str, object]:
            calls.append(1)
            return {"state": "needs_setup", "data": {}}

        state = fetch_with_retry(fetch, policy=NETWORK)

        self.assertEqual(len(calls), 1, "retrying cannot authorize a device")
        self.assertEqual(state["state"], "needs_setup")

    def test_needs_setup_survives_to_the_operator(self) -> None:
        cache = StateCache(self.path)
        state = resolve(
            "claude",
            lambda: {"state": "needs_setup", "data": {}},
            cache=cache,
            now=self.now,
            policy=NETWORK,
        )

        self.assertEqual(state["state"], "needs_setup")

    def test_nothing_cached_yet_reports_unavailable(self) -> None:
        cache = StateCache(self.path)
        state = resolve("weather", lambda: DOWN, cache=cache, now=self.now, policy=LOCAL_FILE)

        self.assertEqual(state, {"state": "unavailable", "data": {}})
