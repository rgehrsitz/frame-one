"""Read automatic Claude Code status-line allowance snapshots."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SNAPSHOT_SOURCE = "claude-code-statusline"


def claude_provider_state(path: Path) -> dict[str, object]:
    """Normalize a snapshot created by Frame One's Claude Code status-line hook.

    The snapshot is deliberately tiny and contains no prompts, transcripts,
    account identifiers, or Claude credentials.  It is not a browser scrape or
    a user-maintained data entry file.
    """
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("source") != SNAPSHOT_SOURCE:
            raise ValueError("not a Frame One Claude Code status-line snapshot")
        rate_limits = value["rate_limits"]
        if not isinstance(rate_limits, dict):
            raise ValueError("rate_limits must be an object")

        five_hour = _window(rate_limits.get("five_hour"))
        seven_day = _window(rate_limits.get("seven_day"))
        if five_hour is None and seven_day is None:
            raise ValueError("snapshot has no usable rate-limit windows")

        return {
            "state": "ok",
            "data": {
                "window_label": "5-HOUR",
                "percent_remaining": five_hour["percent_remaining"] if five_hour else None,
                "resets_at": five_hour["resets_at"] if five_hour else None,
                "secondary_label": "WEEK",
                "secondary_percent_remaining": seven_day["percent_remaining"] if seven_day else None,
                "secondary_resets_at": seven_day["resets_at"] if seven_day else None,
            },
        }
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return {"state": "unavailable", "data": {}}


def _window(value: Any) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    percent_remaining = value.get("percent_remaining")
    resets_at = value.get("resets_at")
    if not isinstance(percent_remaining, (int, float)) or isinstance(percent_remaining, bool):
        return None
    if not 0 <= percent_remaining <= 100:
        return None
    if resets_at is not None and not isinstance(resets_at, str):
        return None
    return {"percent_remaining": round(percent_remaining), "resets_at": resets_at}
