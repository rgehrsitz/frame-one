from __future__ import annotations

import unittest

from PIL import Image

from frame_one.displays.waveshare_7in5_v2 import display_image
from frame_one.renderer import PANEL_SIZE


class _FakeEpd:
    def __init__(self) -> None:
        self.calls: list[object] = []

    def init(self) -> None:
        self.calls.append("init")

    def getbuffer(self, image: Image.Image) -> str:
        self.calls.append(("getbuffer", image.size, image.mode))
        return "buffer"

    def display(self, buffer: str) -> None:
        self.calls.append(("display", buffer))

    def sleep(self) -> None:
        self.calls.append("sleep")


class WaveshareDisplayTests(unittest.TestCase):
    def test_performs_one_clean_full_update_then_sleeps(self) -> None:
        fake = _FakeEpd()
        display_image(Image.new("1", PANEL_SIZE, 1), epd_factory=lambda: fake)

        self.assertEqual(
            fake.calls,
            ["init", ("getbuffer", PANEL_SIZE, "1"), ("display", "buffer"), "sleep"],
        )

    def test_rejects_wrong_panel_format_before_hardware_access(self) -> None:
        with self.assertRaises(ValueError):
            display_image(Image.new("RGB", (10, 10)), epd_factory=lambda: _FakeEpd())
