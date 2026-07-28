from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from frame_one.providers.codex import CodexRateLimitProvider


# A stand-in App Server: it answers the rate-limit request from a worker thread
# and exits the moment stdin reaches EOF, exactly as the real one does.  A
# client that closes stdin as soon as the request is written therefore never
# sees the reply.
FAKE_APP_SERVER = '''
import json, sys, threading, time

DELAY = float(sys.argv[1])

def reply(request_id):
    time.sleep(DELAY)
    print(json.dumps({"id": request_id, "result": {"rateLimits": {
        "primary": {"usedPercent": 18, "windowDurationMins": 10080, "resetsAt": 1785855790},
        "secondary": None,
    }}}), flush=True)

for line in sys.stdin:
    try:
        message = json.loads(line)
    except ValueError:
        continue
    if message.get("method") == "initialize":
        print(json.dumps({"id": message["id"], "result": {}}), flush=True)
    elif message.get("method") == "account/rateLimits/read":
        threading.Thread(target=reply, args=(message["id"],), daemon=True).start()
'''


class CodexRateLimitProviderTests(unittest.TestCase):
    def test_maps_documented_rate_limit_windows(self) -> None:
        response = {
            "id": 2,
            "result": {
                "rateLimits": {
                    "primary": {"usedPercent": 29, "windowDurationMins": 300, "resetsAt": 1785355200},
                    "secondary": {"usedPercent": 19.6, "windowDurationMins": 10080, "resetsAt": 1785945600},
                }
            },
        }

        def runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            sent = str(kwargs["input"])
            self.assertIn('"method": "initialize"', sent)
            self.assertIn('"method": "account/rateLimits/read"', sent)
            return subprocess.CompletedProcess(args[0], 0, stdout=json.dumps(response) + "\n", stderr="")

        state = CodexRateLimitProvider(runner=runner).get()

        self.assertEqual(state["state"], "ok")
        self.assertEqual(state["data"]["window_label"], "WEEK")
        self.assertEqual(state["data"]["percent_remaining"], 80)
        self.assertNotIn("secondary_percent_remaining", state["data"])

    def test_command_failure_is_unavailable(self) -> None:
        def runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(args[0], 1, stdout="", stderr="not signed in")

        self.assertEqual(CodexRateLimitProvider(runner=runner).get(), {"state": "unavailable", "data": {}})

    def test_short_codex_window_is_not_mislabelled_as_weekly(self) -> None:
        result = {
            "rateLimits": {
                "primary": {"usedPercent": 29, "windowDurationMins": 300, "resetsAt": 1785355200},
                "secondary": None,
            }
        }

        with self.assertRaisesRegex(ValueError, "weekly"):
            CodexRateLimitProvider._parse(result)


class CodexAppServerTransportTests(unittest.TestCase):
    """Exercise the real transport against a stand-in App Server."""

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self._script = Path(directory.name) / "fake_app_server.py"
        self._script.write_text(FAKE_APP_SERVER, encoding="utf-8")

    def test_waits_for_a_reply_that_arrives_after_the_request_is_written(self) -> None:
        from frame_one.providers.codex import _run_app_server

        requests = (
            json.dumps({"method": "initialize", "id": 1, "params": {}})
            + "\n"
            + json.dumps({"method": "account/rateLimits/read", "id": 2, "params": {}})
            + "\n"
        )
        completed = _run_app_server(
            [sys.executable, str(self._script), "0.5"],
            input=requests,
            stop_id=2,
            timeout=20,
        )

        self.assertEqual(completed.returncode, 0)
        ids = [json.loads(line)["id"] for line in completed.stdout.splitlines()]
        self.assertIn(2, ids)

    def test_a_server_that_never_replies_is_reported_as_failed(self) -> None:
        from frame_one.providers.codex import _run_app_server

        completed = _run_app_server(
            [sys.executable, str(self._script), "30"],
            input=json.dumps({"method": "account/rateLimits/read", "id": 2, "params": {}}) + "\n",
            stop_id=2,
            timeout=1,
        )

        self.assertEqual(completed.returncode, 1)
