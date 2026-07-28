from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from frame_one.claude_statusline import snapshot_from_statusline, sync_snapshot, write_snapshot
from frame_one.providers.claude import claude_provider_state


class ClaudeStatuslineTests(unittest.TestCase):
    def test_retains_only_documented_allowance_fields(self) -> None:
        timezone = ZoneInfo("America/New_York")
        five_reset = datetime(2026, 7, 28, 14, 15, tzinfo=timezone).timestamp()
        week_reset = datetime(2026, 8, 3, 0, 0, tzinfo=timezone).timestamp()
        snapshot = snapshot_from_statusline(
            {
                "transcript_path": "/private/session.jsonl",
                "workspace": {"repo": "private-project"},
                "rate_limits": {
                    "five_hour": {"used_percentage": 37, "resets_at": five_reset},
                    "seven_day": {"used_percentage": 19, "resets_at": week_reset},
                },
            },
            timezone=timezone,
        )

        assert snapshot is not None
        self.assertEqual(snapshot["source"], "claude-code-statusline")
        self.assertEqual(
            snapshot["rate_limits"],
            {
                "five_hour": {
                    "percent_remaining": 63,
                    "resets_at": "2026-07-28T14:15:00-04:00",
                },
                "seven_day": {
                    "percent_remaining": 81,
                    "resets_at": "2026-08-03T00:00:00-04:00",
                },
            },
        )
        self.assertNotIn("transcript_path", snapshot)
        self.assertNotIn("workspace", snapshot)

    def test_missing_statusline_limits_do_not_replace_a_previous_snapshot(self) -> None:
        self.assertIsNone(snapshot_from_statusline({}, timezone=ZoneInfo("America/New_York")))

    def test_provider_reads_an_automatic_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "claude-status.json"
            path.write_text(
                json.dumps(
                    {
                        "source": "claude-code-statusline",
                        "rate_limits": {
                            "five_hour": {
                                "percent_remaining": 63,
                                "resets_at": "2026-07-28T14:15:00-04:00",
                            },
                            "seven_day": {
                                "percent_remaining": 81,
                                "resets_at": "2026-08-03T00:00:00-04:00",
                            },
                        },
                    }
                )
            )
            state = claude_provider_state(path)

        self.assertEqual(state["state"], "ok")
        self.assertEqual(state["data"]["percent_remaining"], 63)
        self.assertEqual(state["data"]["secondary_percent_remaining"], 81)

    def test_manual_or_missing_file_is_unavailable(self) -> None:
        self.assertEqual(claude_provider_state(Path("missing.json")), {"state": "unavailable", "data": {}})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old-manual-bridge.json"
            path.write_text(json.dumps({"five_hour_percent_remaining": 63}))
            self.assertEqual(claude_provider_state(path), {"state": "unavailable", "data": {}})

    def test_snapshot_is_atomic_and_owner_readable_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "claude-status.json"
            write_snapshot(path, {"source": "claude-code-statusline", "rate_limits": {}})
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    @patch("frame_one.claude_statusline.subprocess.run")
    def test_sync_uses_noninteractive_scp_and_respects_interval(self, run) -> None:
        run.return_value.returncode = 0
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "claude-status.json"
            path.write_text("{}")
            self.assertTrue(
                sync_snapshot(
                    path,
                    "pi@frame-one.local:~/.config/frame-one/claude-status.json",
                    identity_file=Path("/tmp/frame-one-pi"),
                    interval_seconds=900,
                    now=1_000,
                )
            )
            self.assertFalse(
                sync_snapshot(
                    path,
                    "pi@frame-one.local:~/.config/frame-one/claude-status.json",
                    identity_file=Path("/tmp/frame-one-pi"),
                    interval_seconds=900,
                    now=1_100,
                )
            )

        command = run.call_args.args[0]
        self.assertEqual(command[:5], ["scp", "-q", "-B", "-o", "ConnectTimeout=3"])
        self.assertIn("-i", command)
