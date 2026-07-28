from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from PIL import Image

from frame_one import cli


class DisplayIfChangedTests(unittest.TestCase):
    """A full e-paper refresh flashes the panel, so repeat writes are wasteful."""

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.output = Path(directory.name) / "dashboard.png"

    @staticmethod
    def _image(shade: int) -> Image.Image:
        return Image.new("1", (8, 8), shade)

    def test_the_first_render_always_reaches_the_panel(self) -> None:
        with mock.patch.object(cli, "display_image") as display:
            sent = cli._display_if_changed(self._image(0), self.output, force=False)

        self.assertTrue(sent)
        display.assert_called_once()

    def test_an_identical_rerender_leaves_the_panel_alone(self) -> None:
        with mock.patch.object(cli, "display_image") as display:
            cli._display_if_changed(self._image(0), self.output, force=False)
            sent = cli._display_if_changed(self._image(0), self.output, force=False)

        self.assertFalse(sent)
        self.assertEqual(display.call_count, 1, "unchanged pixels should not flash the panel")

    def test_changed_pixels_reach_the_panel(self) -> None:
        with mock.patch.object(cli, "display_image") as display:
            cli._display_if_changed(self._image(0), self.output, force=False)
            sent = cli._display_if_changed(self._image(1), self.output, force=False)

        self.assertTrue(sent)
        self.assertEqual(display.call_count, 2)

    def test_force_overrides_the_unchanged_check(self) -> None:
        with mock.patch.object(cli, "display_image") as display:
            cli._display_if_changed(self._image(0), self.output, force=False)
            sent = cli._display_if_changed(self._image(0), self.output, force=True)

        self.assertTrue(sent)
        self.assertEqual(display.call_count, 2)


class RenderMarkerTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.marker = Path(directory.name) / ".dashboard.png.last-render"

    def test_a_missing_marker_reads_as_never_rendered(self) -> None:
        self.assertIsNone(cli._last_render(self.marker))

    def test_a_corrupt_marker_reads_as_never_rendered(self) -> None:
        self.marker.write_text("not a timestamp\n", encoding="utf-8")
        self.assertIsNone(cli._last_render(self.marker))

    def test_a_recorded_render_round_trips(self) -> None:
        from datetime import datetime

        moment = datetime(2026, 7, 28, 3, 15).astimezone()
        cli._record_render(self.marker, moment)
        self.assertEqual(cli._last_render(self.marker), moment)
