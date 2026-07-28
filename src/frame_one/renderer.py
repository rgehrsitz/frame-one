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
        return self.state == "ok"


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


def _weather_mark(draw: ImageDraw.ImageDraw, x: int, y: int, code: str) -> None:
    """Draw a small weather mark without relying on emoji glyph support."""
    if code in {"clear", "partly_cloudy"}:
        draw.ellipse((x + 5, y, x + 19, y + 14), outline=INK, width=2)
        for dx, dy in ((12, -5), (12, 19), (-1, 7), (25, 7)):
            _line(draw, (x + dx, y + dy, x + dx + (0 if dx == 12 else 3), y + dy + (3 if dx == 12 else 0)))
    if code in {"cloudy", "partly_cloudy", "rain"}:
        draw.arc((x + 7, y + 8, x + 22, y + 23), 180, 360, fill=INK, width=2)
        draw.arc((x + 16, y + 5, x + 31, y + 23), 180, 360, fill=INK, width=2)
        _line(draw, (x + 6, y + 23, x + 33, y + 23))
    if code == "rain":
        for dx in (12, 20, 28):
            _line(draw, (x + dx, y + 27, x + dx - 2, y + 31))


def _render_usage_column(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    title: str,
    provider: Provider,
    *,
    default_window: str = "5-HOUR",
) -> None:
    left, top, right, bottom = box
    width = right - left
    title_font = _fit_font(draw, "display", title, 36, width - 32)
    label_font = _fit_font(draw, "mono", default_window, 18, width - 32)
    value = _percent(_provider_data(provider, "percent_remaining"))
    value_font = _fit_font(draw, "display", value, 90, width - 28)
    support_font = _fit_font(draw, "mono", "RESETS 12:00 PM", 17, width - 32)

    _centered(draw, (left, top + 18, right, top + 62), title, title_font)
    window_label = _provider_data(provider, "window_label", default_window)
    _centered(draw, (left, top + 62, right, top + 88), str(window_label), label_font)
    _centered(draw, (left, top + 82, right, top + 180), value, value_font)

    secondary_label = _provider_data(provider, "secondary_label", "WEEK")
    secondary = _percent(_provider_data(provider, "secondary_percent_remaining"))
    reset = _format_reset(_provider_data(provider, "resets_at"))
    _left(draw, left + 34, bottom - 68, f"{secondary_label}  {secondary}", support_font)
    _left(draw, left + 34, bottom - 37, f"RESETS  {reset}", support_font)


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
    updated_text = f"UPDATED {generated.strftime('%-I:%M %p')}"
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
        f"TODAY  {_provider_data(weather, 'today_high_f', '—')}° / {_provider_data(weather, 'today_low_f', '—')}°",
        f"TONIGHT  {_provider_data(weather, 'tonight_low_f', '—')}° · {_provider_data(weather, 'tonight_rain_percent', '—')}% RAIN",
        f"TOMORROW  {_provider_data(weather, 'tomorrow_high_f', '—')}° / {_provider_data(weather, 'tomorrow_low_f', '—')}° · {_provider_data(weather, 'tomorrow_rain_percent', '—')}% RAIN",
    )
    for index, text in enumerate(forecast_items):
        left, right = COLUMN_BREAKS[index], COLUMN_BREAKS[index + 1]
        font = _fit_font(draw, "mono", text, 18, right - left - 18)
        _centered(draw, (left, HEADER_BOTTOM, right, FORECAST_BOTTOM), text, font)

    _render_usage_column(draw, (0, FORECAST_BOTTOM, 267, STATUS_BOTTOM), "CLAUDE", claude)
    _render_usage_column(draw, (267, FORECAST_BOTTOM, 534, STATUS_BOTTOM), "CODEX", codex)

    gmail_value = str(_provider_data(gmail, "unread", "—"))
    gmail_title = _fit_font(draw, "display", "GMAIL", 36, 235)
    gmail_value_font = _fit_font(draw, "display", gmail_value, 104, 230)
    unread_font = _fit_font(draw, "mono", "UNREAD", 19, 180)
    _centered(draw, (534, FORECAST_BOTTOM + 18, 800, FORECAST_BOTTOM + 62), "GMAIL", gmail_title)
    _centered(draw, (534, FORECAST_BOTTOM + 78, 800, FORECAST_BOTTOM + 182), gmail_value, gmail_value_font)
    _centered(draw, (534, FORECAST_BOTTOM + 186, 800, FORECAST_BOTTOM + 218), "UNREAD", unread_font)

    quote_text = str(_provider_data(quote, "text", "—"))
    attribution = str(_provider_data(quote, "attribution", ""))
    quote_font = _fit_font(draw, "serif", quote_text, 21, 550)
    attribution_font = _fit_font(draw, "mono", attribution, 16, 180)
    _left(draw, 36, 434, quote_text, quote_font)
    _right(draw, 764, 438, attribution, attribution_font)
    return image
