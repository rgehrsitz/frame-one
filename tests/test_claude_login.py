from __future__ import annotations

import threading
import unittest
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import urlopen

from frame_one.claude_login import capture_authorization_code
from frame_one.providers.claude_oauth import REDIRECT_URI


REDIRECT = urlparse(REDIRECT_URI)
BASE = f"http://{REDIRECT.hostname}:{REDIRECT.port}"


def visit(path: str) -> int:
    """Fetch a path on the waiting listener and report the status code."""
    try:
        with urlopen(f"{BASE}{path}", timeout=5) as response:
            return response.status
    except HTTPError as error:
        return error.code


class CallbackListenerTests(unittest.TestCase):
    """The redirect has to arrive by itself, and only the right one may count."""

    def _capture(self, *paths: str, expected_state: str = "the-state") -> object:
        """Run the listener, drive the given requests at it, return its outcome."""
        outcome: dict[str, object] = {}

        def run() -> None:
            try:
                outcome["code"] = capture_authorization_code(
                    expected_state=expected_state, timeout_seconds=10
                )
            except Exception as error:  # noqa: BLE001 - the outcome under test
                outcome["error"] = error

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        for path in paths:
            for _ in range(50):
                try:
                    outcome.setdefault("statuses", []).append(visit(path))  # type: ignore[union-attr]
                    break
                except OSError:
                    threading.Event().wait(0.05)
        worker.join(timeout=15)
        return outcome

    def test_an_approved_redirect_is_captured_without_any_pasting(self) -> None:
        outcome = self._capture("/callback?code=the-code&state=the-state")

        self.assertEqual(outcome.get("code"), "the-code")

    def test_a_mismatched_state_is_refused(self) -> None:
        outcome = self._capture("/callback?code=the-code&state=someone-elses")

        self.assertIsInstance(outcome.get("error"), ValueError)
        self.assertIn("state", str(outcome["error"]))

    def test_a_declined_authorization_is_reported(self) -> None:
        outcome = self._capture("/callback?error=access_denied&state=the-state")

        self.assertIsInstance(outcome.get("error"), ValueError)
        self.assertIn("declined", str(outcome["error"]))

    def test_a_redirect_without_a_code_is_refused(self) -> None:
        outcome = self._capture("/callback?state=the-state")

        self.assertIsInstance(outcome.get("error"), ValueError)

    def test_an_unrelated_request_does_not_end_the_wait(self) -> None:
        outcome = self._capture("/favicon.ico", "/callback?code=the-code&state=the-state")

        self.assertEqual(outcome.get("code"), "the-code")
        self.assertEqual(outcome.get("statuses"), [404, 200])

    def test_the_listener_only_binds_loopback(self) -> None:
        self.assertIn(REDIRECT.hostname, ("localhost", "127.0.0.1"))

    def test_waiting_for_nobody_times_out_rather_than_hanging(self) -> None:
        clock = iter([0.0, 0.0, 99.0])

        with self.assertRaises(TimeoutError):
            capture_authorization_code(
                expected_state="the-state", timeout_seconds=5, monotonic=lambda: next(clock)
            )


if __name__ == "__main__":
    unittest.main()
