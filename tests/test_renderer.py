from __future__ import annotations

import json
import unittest
from pathlib import Path

from frame_one import PANEL_SIZE, render_dashboard


ROOT = Path(__file__).parents[1]


class RendererTests(unittest.TestCase):
    def test_renders_exact_one_bit_panel(self) -> None:
        state = json.loads((ROOT / "samples/dashboard-state.json").read_text())
        image = render_dashboard(state)

        self.assertEqual(image.size, PANEL_SIZE)
        self.assertEqual(image.mode, "1")
        self.assertEqual(set(image.getdata()), {0, 1})

    def test_unavailable_provider_renders_without_error(self) -> None:
        state = json.loads((ROOT / "samples/dashboard-state.json").read_text())
        state["gmail"] = {"state": "needs_setup", "data": {}}
        image = render_dashboard(state)

        self.assertEqual(image.size, PANEL_SIZE)


if __name__ == "__main__":
    unittest.main()
