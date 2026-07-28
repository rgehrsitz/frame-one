from __future__ import annotations

import json
import subprocess
import unittest

from frame_one.providers.codex import CodexRateLimitProvider


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
        self.assertEqual(state["data"]["window_label"], "5-HOUR")
        self.assertEqual(state["data"]["percent_remaining"], 71)
        self.assertEqual(state["data"]["secondary_label"], "WEEK")
        self.assertEqual(state["data"]["secondary_percent_remaining"], 80)

    def test_command_failure_is_unavailable(self) -> None:
        def runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(args[0], 1, stdout="", stderr="not signed in")

        self.assertEqual(CodexRateLimitProvider(runner=runner).get(), {"state": "unavailable", "data": {}})
