"""Deliberate local bridge for Claude consumer-plan usage information."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def claude_provider_state(path: Path) -> dict[str, object]:
    """Normalize a user-maintained bridge file; never inspect Claude sessions."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Claude bridge must be an object")
        return {
            "state": "ok",
            "data": {
                "window_label": "5-HOUR",
                "percent_remaining": value["five_hour_percent_remaining"],
                "resets_at": value["five_hour_resets_at"],
                "secondary_label": "WEEK",
                "secondary_percent_remaining": value.get("week_percent_remaining"),
                "secondary_resets_at": value.get("week_resets_at"),
            },
        }
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return {"state": "unavailable", "data": {}}
