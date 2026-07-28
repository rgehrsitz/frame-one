"""Command-line entry point for rendering a Frame One screen."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .displays import display_image
from .providers.quotes import quote_provider_state
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
    args = parser.parse_args()

    with args.input.open("r", encoding="utf-8") as state_file:
        state = json.load(state_file)

    if args.live_quote:
        quote_state = quote_provider_state()
        if quote_state["state"] != "ok":
            parser.error("live quote unavailable; existing display was left untouched")
        state["quote"] = quote_state

    args.output.parent.mkdir(parents=True, exist_ok=True)
    image = render_dashboard(state)
    image.save(args.output)
    print(f"Rendered {args.output}")
    if args.display == "waveshare-7in5-v2":
        display_image(image)
        print("Updated Waveshare 7.5-inch V2 display")


if __name__ == "__main__":
    main()
