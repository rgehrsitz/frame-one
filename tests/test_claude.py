from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from frame_one.providers.claude import claude_provider_state


class ClaudeBridgeTests(unittest.TestCase):
    def test_normalizes_deliberate_manual_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "claude.json"
            path.write_text(
                json.dumps(
                    {
                        "five_hour_percent_remaining": 63,
                        "five_hour_resets_at": "2026-07-28T14:15:00-04:00",
                        "week_percent_remaining": 81,
                        "week_resets_at": "2026-08-03T00:00:00-04:00",
                    }
                )
            )
            state = claude_provider_state(path)

        self.assertEqual(state["state"], "ok")
        self.assertEqual(state["data"]["percent_remaining"], 63)
        self.assertEqual(state["data"]["secondary_percent_remaining"], 81)

    def test_invalid_or_missing_bridge_is_unavailable(self) -> None:
        self.assertEqual(claude_provider_state(Path("missing.json")), {"state": "unavailable", "data": {}})
