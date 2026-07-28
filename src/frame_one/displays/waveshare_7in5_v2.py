"""Output adapter for the Waveshare 7.5-inch V2 black-and-white panel."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from frame_one.renderer import PANEL_SIZE

DEFAULT_WAVESHARE_LIB = Path.home() / "waveshare-e-paper/RaspberryPi_JetsonNano/python/lib"


def _load_epd_factory() -> Callable[[], Any]:
    """Load Waveshare's official driver lazily, so rendering stays hardware-free."""
    library_path = Path(os.environ.get("FRAME_ONE_WAVESHARE_LIB", DEFAULT_WAVESHARE_LIB))
    if library_path.is_dir() and str(library_path) not in sys.path:
        sys.path.insert(0, str(library_path))
    try:
        from waveshare_epd import epd7in5_V2
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "Waveshare's V2 library was not found. Clone waveshareteam/e-Paper to "
            "~/waveshare-e-paper or set FRAME_ONE_WAVESHARE_LIB."
        ) from error
    return epd7in5_V2.EPD


def display_image(image: Image.Image, *, epd_factory: Callable[[], Any] | None = None) -> None:
    """Perform one full, clean update and put the panel to sleep afterward."""
    if image.size != PANEL_SIZE or image.mode != "1":
        raise ValueError("Waveshare 7.5-inch V2 requires an 800 x 480, 1-bit image")

    epd = (epd_factory or _load_epd_factory())()
    initialized = False
    try:
        epd.init()
        initialized = True
        epd.display(epd.getbuffer(image))
    finally:
        if initialized:
            epd.sleep()
