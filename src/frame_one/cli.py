"""Command-line entry point for rendering a Frame One screen."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .displays import display_image
from .providers.claude import claude_provider_state
from .providers.codex import CodexRateLimitProvider
from .providers.gmail import GmailUnreadProvider
from .providers.quotes import quote_provider_state
from .providers.weather import OpenMeteoWeatherProvider, WeatherLocation
from .renderer import render_dashboard


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a Frame One e-paper PNG.")
    parser.add_argument("--input", type=Path, required=True, help="Dashboard state JSON")
    parser.add_argument("--output", type=Path, required=True, help="Output PNG path")
    parser.add_argument(
        "--display",
        choices=("waveshare-7in5-v2",),
        help="Optionally send the rendered image to a supported physical display",
    )
    parser.add_argument(
        "--live-quote",
        action="store_true",
        help="Fetch and render the live Quote of the Day without storing it separately",
    )
    parser.add_argument("--live-weather", action="store_true", help="Fetch current weather from Open-Meteo")
    parser.add_argument("--claude-state", type=Path, help="Manual Claude allowance bridge JSON")
    parser.add_argument("--live-codex", action="store_true", help="Read allowance from the local Codex App Server")
    parser.add_argument("--gmail-token", type=Path, help="Read Gmail INBOX count using this local OAuth token")
    parser.add_argument("--weather-latitude", type=float, help="Explicit weather location latitude")
    parser.add_argument("--weather-longitude", type=float, help="Explicit weather location longitude")
    parser.add_argument(
        "--weather-timezone",
        default="America/New_York",
        help="IANA timezone used for the forecast (default: America/New_York)",
    )
    args = parser.parse_args()

    with args.input.open("r", encoding="utf-8") as state_file:
        state = json.load(state_file)

    if args.live_quote:
        quote_state = quote_provider_state()
        if quote_state["state"] != "ok":
            parser.error("live quote unavailable; existing display was left untouched")
        state["quote"] = quote_state

    if args.live_weather:
        if args.weather_latitude is None or args.weather_longitude is None:
            parser.error("--live-weather requires --weather-latitude and --weather-longitude")
        weather_state = OpenMeteoWeatherProvider(
            WeatherLocation(args.weather_latitude, args.weather_longitude, args.weather_timezone)
        ).get()
        if weather_state["state"] != "ok":
            parser.error("live weather unavailable; existing display was left untouched")
        state["weather"] = weather_state
        # Keep the header's date and update stamp honest when live weather
        # replaces the sample state used as the rest of the dashboard's base.
        state["generated_at"] = weather_state["updated_at"]

    if args.claude_state:
        claude_state = claude_provider_state(args.claude_state)
        if claude_state["state"] != "ok":
            parser.error("Claude bridge unavailable; existing display was left untouched")
        state["claude"] = claude_state

    if args.live_codex:
        codex_state = CodexRateLimitProvider().get()
        if codex_state["state"] != "ok":
            parser.error("Codex allowance unavailable; existing display was left untouched")
        state["codex"] = codex_state

    if args.gmail_token:
        gmail_state = GmailUnreadProvider(args.gmail_token).get()
        if gmail_state["state"] != "ok":
            parser.error("Gmail unread count unavailable; existing display was left untouched")
        state["gmail"] = gmail_state

    args.output.parent.mkdir(parents=True, exist_ok=True)
    image = render_dashboard(state)
    image.save(args.output)
    print(f"Rendered {args.output}")
    if args.display == "waveshare-7in5-v2":
        display_image(image)
        print("Updated Waveshare 7.5-inch V2 display")


if __name__ == "__main__":
    main()
