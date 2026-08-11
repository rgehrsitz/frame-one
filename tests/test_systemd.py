from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]


class SystemdTimerTests(unittest.TestCase):
    def test_live_refresh_runs_on_ten_minute_boundaries(self) -> None:
        timer = (ROOT / "deploy/systemd/frame-one-refresh.timer").read_text(encoding="utf-8")

        self.assertIn("OnCalendar=*-*-* *:0/10:00", timer)
        self.assertNotIn("OnCalendar=*-*-* *:0/5:00", timer)


if __name__ == "__main__":
    unittest.main()
