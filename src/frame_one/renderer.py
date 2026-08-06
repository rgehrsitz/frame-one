"""Strict 1-bit renderer for the Frame One 800 × 480 e-paper panel."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from PIL import Image, ImageDraw, ImageFont

PANEL_SIZE = (800, 480)
INK = 0
PAPER = 1

HEADER_BOTTOM = 92
FORECAST_BOTTOM = 140
STATUS_BOTTOM = 410
COLUMN_BREAKS = (0, 267, 534, 800)
ASSET_FONT_DIR = Path(__file__).parent / "assets" / "fonts"

# These are deliberately fixed across all forecast cells.  The longest item
# needs enough headroom for Pillow/FreeType metric differences between macOS
# and the Raspberry Pi, so do not increase them without checking that margin.
FORECAST_LABEL_SIZE = 20
FORECAST_VALUE_SIZE = 13
FORECAST_GAP = 6
FORECAST_HORIZONTAL_PADDING = 18

# Each status tile uses the same compact hierarchy: a heading, a short label,
# then the primary metric.  Keep these shared so Gmail cannot gradually drift
# away from the allowance columns.
STATUS_TITLE_BOX = (18, 62)
STATUS_PRIMARY_LABEL_BOX = (62, 88)
STATUS_PRIMARY_VALUE_BOX = (84, 160)
STATUS_TITLE_SIZE = 36
STATUS_PRIMARY_LABEL_SIZE = 24
STATUS_PRIMARY_VALUE_SIZE = 80


@dataclass(frozen=True)
class Provider:
    state: str
    data: Mapping[str, Any]

    @classmethod
    def from_state(cls, value: Mapping[str, Any] | None) -> "Provider":
        value = value or {}
        return cls(state=str(value.get("state", "needs_setup")), data=value.get("data", {}))

    @property
    def available(self) -> bool:
        # A "stale" provider is a value that was true at its last successful
        # refresh and has not yet aged past its stale_after_seconds.  Showing it
        # is not inventing a value; hiding it would blank a tile over a blip.
        return self.state in ("ok", "stale")


def _font_candidates(kind: str) -> list[Path]:
    """Return local fonts used for development and sensible Pi fallbacks.

    Production deployment should set FRAME_ONE_DISPLAY_FONT,
    FRAME_ONE_MONO_FONT, and FRAME_ONE_SERIF_FONT to bundled fonts.
    """

    env_name = f"FRAME_ONE_{kind.upper()}_FONT"
    env_path = os.getenv(env_name)
    candidates = [Path(env_path)] if env_path else []
    candidates.extend(
        {
            "display": [
                ASSET_FONT_DIR / "BarlowCondensed-SemiBold.ttf",
                Path("/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf"),
                Path("/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf"),
            ],
            "mono": [
                ASSET_FONT_DIR / "IBMPlexMono-Medium.ttf",
                Path("/System/Library/Fonts/SFNSMono.ttf"),
                Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
            ],
            "serif": [
                ASSET_FONT_DIR / "IBMPlexSerif-Italic.ttf",
                Path("/System/Library/Fonts/Supplemental/PTSerif.ttc"),
                Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf"),
            ],
        }[kind]
    )
    return candidates


def _font(kind: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in _font_candidates(kind):
        if candidate.exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    return int(draw.textbbox((0, 0), text, font=font)[2])


def _fit_font(
    draw: ImageDraw.ImageDraw, kind: str, text: str, preferred_size: int, max_width: int
) -> ImageFont.ImageFont:
    for size in range(preferred_size, 7, -1):
        font = _font(kind, size)
        if _text_width(draw, text, font) <= max_width:
            return font
    return _font(kind, 7)


def _centered(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    font: ImageFont.ImageFont,
    *,
    anchor_y: int | None = None,
) -> None:
    left, top, right, bottom = box
    text_box = draw.textbbox((0, 0), text, font=font)
    text_width = text_box[2] - text_box[0]
    text_height = text_box[3] - text_box[1]
    x = left + (right - left - text_width) // 2
    y = anchor_y if anchor_y is not None else top + (bottom - top - text_height) // 2
    draw.text((x, y), text, fill=INK, font=font)


def _left(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, font: ImageFont.ImageFont) -> None:
    draw.text((x, y), text, fill=INK, font=font)


def _right(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, font: ImageFont.ImageFont) -> None:
    text_box = draw.textbbox((0, 0), text, font=font)
    draw.text((x - (text_box[2] - text_box[0]), y), text, fill=INK, font=font)


def _line(draw: ImageDraw.ImageDraw, points: tuple[int, int, int, int]) -> None:
    draw.line(points, fill=INK, width=1)


def _provider_data(provider: Provider, key: str, default: Any = None) -> Any:
    return provider.data.get(key, default) if provider.available else default


def _percent(value: Any) -> str:
    return "—" if value is None else f"{round(float(value))}%"


def _format_reset(value: Any) -> str:
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(str(value)).strftime("%-I:%M %p")
    except ValueError:
        return str(value)


def _format_reset_date_time(value: Any) -> str:
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(str(value)).strftime("%a, %b %-d · %-I:%M %p").upper()
    except ValueError:
        return str(value)


def _weather_mark(draw: ImageDraw.ImageDraw, x: int, y: int, code: str) -> None:
    """Draw Frame One's compact, 1-bit weather instrument marks.

    They are deliberately drawn here, rather than imported as emoji or a font,
    so their stroke weight remains clear and consistent on the e-paper panel.
    """

    def cloud(cloud_y: int) -> None:
        """One silhouette, avoiding fussy overlapping curves at this scale."""
        draw.ellipse((x + 4, cloud_y + 9, x + 18, cloud_y + 22), fill=INK)
        draw.ellipse((x + 11, cloud_y + 3, x + 27, cloud_y + 22), fill=INK)
        draw.ellipse((x + 23, cloud_y + 10, x + 35, cloud_y + 22), fill=INK)
        draw.rectangle((x + 10, cloud_y + 15, x + 29, cloud_y + 22), fill=INK)

    if code == "clear":
        draw.ellipse((x + 11, y + 7, x + 23, y + 19), outline=INK, width=2)
        _line(draw, (x + 17, y + 1, x + 17, y + 4))
        _line(draw, (x + 17, y + 22, x + 17, y + 25))
        _line(draw, (x + 5, y + 13, x + 8, y + 13))
        _line(draw, (x + 26, y + 13, x + 29, y + 13))
    elif code == "partly_cloudy":
        # The sun is deliberately rayless here: at 28 px, rays compete with
        # the cloud and make the mark harder to parse at a glance.
        draw.ellipse((x + 7, y + 3, x + 19, y + 15), outline=INK, width=2)
        cloud(y + 5)
    elif code == "alert":
        draw.polygon(((x + 17, y + 2), (x + 2, y + 30), (x + 32, y + 30)), outline=INK)
        draw.rectangle((x + 16, y + 11, x + 18, y + 21), fill=INK)
        draw.rectangle((x + 16, y + 25, x + 18, y + 27), fill=INK)
    else:
        cloud(y + 3)
    if code in ("rain", "storm"):
        for dx in (11, 19, 27):
            _line(draw, (x + dx, y + 27, x + dx - 2, y + 31))
    if code in ("snow", "mixed"):
        for dx in (12, 22, 32):
            _line(draw, (x + dx - 2, y + 28, x + dx + 2, y + 32))
            _line(draw, (x + dx + 2, y + 28, x + dx - 2, y + 32))
    if code in ("sleet", "ice", "mixed"):
        for dx in (11, 21, 31):
            draw.ellipse((x + dx - 1, y + 28, x + dx + 1, y + 30), fill=INK)
    if code == "storm":
        draw.polygon(((x + 20, y + 23), (x + 15, y + 31), (x + 20, y + 30), (x + 16, y + 36)), fill=INK)


def _render_forecast_item(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    label: str,
    value: str,
) -> None:
    """Render a forecast label/value pair without shrinking one column's type."""
    left, top, right, bottom = box
    label_font = _font("display", FORECAST_LABEL_SIZE)
    value_font = _font("mono", FORECAST_VALUE_SIZE)
    label_width = _text_width(draw, label, label_font)
    value_width = _text_width(draw, value, value_font)
    content_width = label_width + FORECAST_GAP + value_width
    if content_width > right - left - FORECAST_HORIZONTAL_PADDING:
        raise ValueError(f"Forecast item is too wide for its column: {label} {value}")
    x = left + (right - left - content_width) // 2
    label_box = draw.textbbox((0, 0), label, font=label_font)
    value_box = draw.textbbox((0, 0), value, font=value_font)
    label_height = label_box[3] - label_box[1]
    value_height = value_box[3] - value_box[1]
    label_y = top + (bottom - top - label_height) // 2
    value_y = top + (bottom - top - value_height) // 2
    _left(draw, x, label_y, label, label_font)
    _left(draw, x + label_width + FORECAST_GAP, value_y, value, value_font)


def _render_claude_column(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    provider: Provider,
) -> None:
    """Render Claude's two deliberate, independently-resetting allowances."""
    left, top, right, bottom = box
    width = right - left
    title_font = _fit_font(draw, "display", "CLAUDE", STATUS_TITLE_SIZE, width - 32)
    window_font = _fit_font(draw, "display", "5-HOUR LEFT", STATUS_PRIMARY_LABEL_SIZE, width - 32)
    value = _percent(_provider_data(provider, "percent_remaining"))
    value_font = _fit_font(draw, "display", value, STATUS_PRIMARY_VALUE_SIZE, width - 28)
    detail_label_font = _fit_font(draw, "display", "5-HOUR RESETS", 16, width - 52)
    detail_value_font = _fit_font(draw, "mono", "12:00 AM", 14, width - 52)
    weekly_reset_font = _fit_font(draw, "display", "RESETS MON, AUG 3 · 12:00 AM", 18, width - 28)
    secondary = _percent(_provider_data(provider, "secondary_percent_remaining"))
    primary_reset = _format_reset(_provider_data(provider, "resets_at"))
    secondary_reset_at = _provider_data(provider, "secondary_resets_at")
    secondary_reset = _format_reset_date_time(secondary_reset_at)

    _centered(draw, (left, top + STATUS_TITLE_BOX[0], right, top + STATUS_TITLE_BOX[1]), "CLAUDE", title_font)
    _centered(
        draw,
        (left, top + STATUS_PRIMARY_LABEL_BOX[0], right, top + STATUS_PRIMARY_LABEL_BOX[1]),
        "5-HOUR LEFT",
        window_font,
    )
    _centered(
        draw,
        (left, top + STATUS_PRIMARY_VALUE_BOX[0], right, top + STATUS_PRIMARY_VALUE_BOX[1]),
        value,
        value_font,
    )
    _left(draw, left + 26, bottom - 92, "5-HOUR RESETS", detail_label_font)
    _right(draw, right - 26, bottom - 92, primary_reset, detail_value_font)
    _left(draw, left + 26, bottom - 61, "WEEK LEFT", detail_label_font)
    _right(draw, right - 26, bottom - 61, secondary, detail_value_font)
    _centered(draw, (left, bottom - 34, right, bottom - 10), f"RESETS {secondary_reset}", weekly_reset_font)


def _render_codex_column(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    provider: Provider,
) -> None:
    """Render the one weekly Codex allowance the dashboard is meant to track."""
    left, top, right, bottom = box
    width = right - left
    title_font = _fit_font(draw, "display", "CODEX", STATUS_TITLE_SIZE, width - 32)
    label_font = _fit_font(draw, "display", "WEEK LEFT", STATUS_PRIMARY_LABEL_SIZE, width - 32)
    value = _percent(_provider_data(provider, "percent_remaining"))
    value_font = _fit_font(draw, "display", value, STATUS_PRIMARY_VALUE_SIZE, width - 28)
    reset_font = _fit_font(draw, "display", "RESETS MON, AUG 3 · 12:00 AM", 18, width - 28)
    reset = _format_reset_date_time(_provider_data(provider, "resets_at"))

    _centered(draw, (left, top + STATUS_TITLE_BOX[0], right, top + STATUS_TITLE_BOX[1]), "CODEX", title_font)
    _centered(
        draw,
        (left, top + STATUS_PRIMARY_LABEL_BOX[0], right, top + STATUS_PRIMARY_LABEL_BOX[1]),
        "WEEK LEFT",
        label_font,
    )
    _centered(
        draw,
        (left, top + STATUS_PRIMARY_VALUE_BOX[0], right, top + STATUS_PRIMARY_VALUE_BOX[1]),
        value,
        value_font,
    )
    _centered(draw, (left, bottom - 62, right, bottom - 34), f"RESETS {reset}", reset_font)


def render_dashboard(state: Mapping[str, Any]) -> Image.Image:
    """Render one normalized dashboard state as an 800 × 480, 1-bit image."""
    image = Image.new("1", PANEL_SIZE, PAPER)
    draw = ImageDraw.Draw(image)

    weather = Provider.from_state(state.get("weather"))
    claude = Provider.from_state(state.get("claude"))
    codex = Provider.from_state(state.get("codex"))
    gmail = Provider.from_state(state.get("gmail"))
    quote = Provider.from_state(state.get("quote"))

    generated = datetime.fromisoformat(str(state.get("generated_at", datetime.now().astimezone().isoformat())))
    date_text = generated.strftime("%a · %b %-d").upper()
    active_alert = _provider_data(weather, "active_alert")
    updated_text = str(active_alert or f"UPDATED {generated.strftime('%-I:%M %p')}")
    header_font = _fit_font(draw, "display", date_text, 28, 190)
    updated_font = _fit_font(draw, "mono", updated_text, 18, 235)
    current_temp = _provider_data(weather, "current_temperature_f")
    condition = str(_provider_data(weather, "current_condition", "unknown"))
    now_text = "NOW —" if current_temp is None else f"NOW {round(float(current_temp))}°"
    now_font = _fit_font(draw, "display", now_text, 28, 135)
    _left(draw, 36, 31, date_text, header_font)
    _centered(draw, (245, 24, 555, 68), updated_text, updated_font)
    _right(draw, 742, 31, now_text, now_font)
    if weather.available:
        _weather_mark(draw, 748, 34, condition)

    _line(draw, (0, HEADER_BOTTOM, 800, HEADER_BOTTOM))
    _line(draw, (0, FORECAST_BOTTOM, 800, FORECAST_BOTTOM))
    for x in COLUMN_BREAKS[1:-1]:
        _line(draw, (x, HEADER_BOTTOM, x, STATUS_BOTTOM))
    _line(draw, (0, STATUS_BOTTOM, 800, STATUS_BOTTOM))

    forecast_items = (
        ("TODAY", f"{_provider_data(weather, 'today_high_f', '—')}°/{_provider_data(weather, 'today_low_f', '—')}°"),
        ("TONIGHT", f"{_provider_data(weather, 'tonight_low_f', '—')}° · {_provider_data(weather, 'tonight_precipitation_type', 'RAIN')} {_provider_data(weather, 'tonight_rain_percent', '—')}%"),
        ("TOMORROW", f"{_provider_data(weather, 'tomorrow_high_f', '—')}°/{_provider_data(weather, 'tomorrow_low_f', '—')}° · {_provider_data(weather, 'tomorrow_precipitation_type', 'RAIN')} {_provider_data(weather, 'tomorrow_rain_percent', '—')}%"),
    )
    for index, (label, value) in enumerate(forecast_items):
        left, right = COLUMN_BREAKS[index], COLUMN_BREAKS[index + 1]
        _render_forecast_item(
            draw,
            (left, HEADER_BOTTOM, right, FORECAST_BOTTOM),
            label,
            value,
        )

    _render_claude_column(draw, (0, FORECAST_BOTTOM, 267, STATUS_BOTTOM), claude)
    _render_codex_column(draw, (267, FORECAST_BOTTOM, 534, STATUS_BOTTOM), codex)

    gmail_value = str(_provider_data(gmail, "unread", "—"))
    gmail_width = COLUMN_BREAKS[3] - COLUMN_BREAKS[2]
    gmail_title = _fit_font(draw, "display", "GMAIL", STATUS_TITLE_SIZE, gmail_width - 32)
    unread_font = _fit_font(draw, "display", "UNREAD", STATUS_PRIMARY_LABEL_SIZE, gmail_width - 32)
    gmail_value_font = _fit_font(draw, "display", gmail_value, STATUS_PRIMARY_VALUE_SIZE, gmail_width - 28)
    _centered(
        draw,
        (534, FORECAST_BOTTOM + STATUS_TITLE_BOX[0], 800, FORECAST_BOTTOM + STATUS_TITLE_BOX[1]),
        "GMAIL",
        gmail_title,
    )
    _centered(
        draw,
        (534, FORECAST_BOTTOM + STATUS_PRIMARY_LABEL_BOX[0], 800, FORECAST_BOTTOM + STATUS_PRIMARY_LABEL_BOX[1]),
        "UNREAD",
        unread_font,
    )
    _centered(
        draw,
        (534, FORECAST_BOTTOM + STATUS_PRIMARY_VALUE_BOX[0], 800, FORECAST_BOTTOM + STATUS_PRIMARY_VALUE_BOX[1]),
        gmail_value,
        gmail_value_font,
    )

    quote_text = str(_provider_data(quote, "text", "—"))
    attribution = str(_provider_data(quote, "attribution", ""))
    quote_font = _fit_font(draw, "serif", quote_text, 21, 550)
    attribution_font = _fit_font(draw, "mono", attribution, 16, 180)
    _left(draw, 36, 434, quote_text, quote_font)
    _right(draw, 764, 438, attribution, attribution_font)
    return image
