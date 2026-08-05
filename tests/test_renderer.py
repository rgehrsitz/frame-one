from __future__ import annotations

import json
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from frame_one import PANEL_SIZE, render_dashboard
from frame_one.renderer import (
    COLUMN_BREAKS,
    FORECAST_GAP,
    FORECAST_HORIZONTAL_PADDING,
    FORECAST_LABEL_SIZE,
    FORECAST_VALUE_SIZE,
    FORECAST_BOTTOM,
    STATUS_PRIMARY_LABEL_BOX,
    STATUS_PRIMARY_LABEL_SIZE,
    STATUS_PRIMARY_VALUE_BOX,
    STATUS_PRIMARY_VALUE_SIZE,
    _font,
    _text_width,
    _weather_mark,
)


ROOT = Path(__file__).parents[1]


class RendererTests(unittest.TestCase):
    def test_renders_exact_one_bit_panel(self) -> None:
        state = json.loads((ROOT / "samples/dashboard-state.json").read_text())
        image = render_dashboard(state)

        self.assertEqual(image.size, PANEL_SIZE)
        self.assertEqual(image.mode, "1")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            pixels = set(image.getdata())
        self.assertEqual(pixels, {0, 1})

    def test_unavailable_provider_renders_without_error(self) -> None:
        state = json.loads((ROOT / "samples/dashboard-state.json").read_text())
        state["gmail"] = {"state": "needs_setup", "data": {}}
        image = render_dashboard(state)

        self.assertEqual(image.size, PANEL_SIZE)

    def test_gmail_primary_metric_uses_the_shared_allowance_geometry(self) -> None:
        state = json.loads((ROOT / "samples/dashboard-state.json").read_text())
        state["gmail"] = {"state": "ok", "data": {"unread": 15}}

        with patch("frame_one.renderer._centered") as centered:
            render_dashboard(state)

        unread_label = next(call for call in centered.call_args_list if call.args[2] == "UNREAD")
        unread_value = next(call for call in centered.call_args_list if call.args[2] == "15")
        self.assertEqual(
            unread_label.args[1],
            (534, FORECAST_BOTTOM + STATUS_PRIMARY_LABEL_BOX[0], 800, FORECAST_BOTTOM + STATUS_PRIMARY_LABEL_BOX[1]),
        )
        self.assertEqual(unread_label.args[3].size, STATUS_PRIMARY_LABEL_SIZE)
        self.assertEqual(
            unread_value.args[1],
            (534, FORECAST_BOTTOM + STATUS_PRIMARY_VALUE_BOX[0], 800, FORECAST_BOTTOM + STATUS_PRIMARY_VALUE_BOX[1]),
        )
        self.assertEqual(unread_value.args[3].size, STATUS_PRIMARY_VALUE_SIZE)

    def test_longest_forecast_item_has_cross_platform_headroom(self) -> None:
        """Keep the fixed forecast type scale clear of the narrowest column."""
        draw = ImageDraw.Draw(Image.new("1", PANEL_SIZE, 1))
        content_width = (
            _text_width(draw, "TOMORROW", _font("display", FORECAST_LABEL_SIZE))
            + FORECAST_GAP
            + _text_width(draw, "80°/66° · RAIN 40%", _font("mono", FORECAST_VALUE_SIZE))
        )
        available_width = COLUMN_BREAKS[1] - COLUMN_BREAKS[0] - FORECAST_HORIZONTAL_PADDING

        # The previous 15 px value font left only one pixel locally, which
        # failed on the Pi.  Preserve a meaningful buffer, not just a fit.
        self.assertLessEqual(content_width, available_width - 18)

    def test_weather_marks_draw_crisp_ink_for_each_supported_condition(self) -> None:
        for condition in ("clear", "partly_cloudy", "cloudy", "rain", "storm", "alert"):
            image = Image.new("1", (48, 48), 1)
            _weather_mark(ImageDraw.Draw(image), 4, 4, condition)
            self.assertIn(0, image.getdata(), condition)

    def test_active_weather_alert_replaces_the_routine_update_label(self) -> None:
        state = json.loads((ROOT / "samples/dashboard-state.json").read_text())
        state["weather"]["data"]["active_alert"] = "FLASH FLOOD WARNING"
        state["weather"]["data"]["current_condition"] = "storm"

        with patch("frame_one.renderer._centered") as centered:
            render_dashboard(state)

        self.assertTrue(any(call.args[2] == "FLASH FLOOD WARNING" for call in centered.call_args_list))


if __name__ == "__main__":
    unittest.main()
