"""Capture the official Claude Code status-line rate-limit contract.

Claude Code invokes this command with a JSON document on stdin.  Frame One
retains only the documented ``rate_limits`` values and can optionally copy that
small snapshot to the Pi over a pre-configured SSH key.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any
from zoneinfo import ZoneInfo

from .providers.claude import SNAPSHOT_SOURCE


DEFAULT_SYNC_INTERVAL_SECONDS = 15 * 60


def snapshot_from_statusline(
    statusline_input: dict[str, Any], *, timezone: ZoneInfo
) -> dict[str, object] | None:
    """Keep only documented rate-limit fields from a Claude Code status event."""
    rate_limits = statusline_input.get("rate_limits")
    if not isinstance(rate_limits, dict):
        return None

    five_hour = _snapshot_window(rate_limits.get("five_hour"), timezone)
    seven_day = _snapshot_window(rate_limits.get("seven_day"), timezone)
    if five_hour is None and seven_day is None:
        return None

    return {
        "source": SNAPSHOT_SOURCE,
        "captured_at": datetime.now(timezone).isoformat(timespec="seconds"),
        "rate_limits": {
            "five_hour": five_hour,
            "seven_day": seven_day,
        },
    }


def write_snapshot(path: Path, snapshot: dict[str, object]) -> None:
    """Atomically replace a local-only snapshot and keep it owner-readable only."""
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    encoded = json.dumps(snapshot, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as temporary:
        temporary.write(encoded)
        temporary_path = Path(temporary.name)
    try:
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
        os.chmod(path, 0o600)
    finally:
        temporary_path.unlink(missing_ok=True)


def sync_snapshot(
    path: Path,
    target: str,
    *,
    identity_file: Path | None,
    interval_seconds: int,
    now: float | None = None,
) -> bool:
    """Copy a snapshot to the Pi at most once per interval using noninteractive SCP.

    A failed network copy is intentionally silent: Claude Code's status line
    must stay responsive, and the local snapshot remains available for the next
    event-driven attempt.
    """
    marker = path.with_name(f".{path.name}.last-sync")
    current_time = time.time() if now is None else now
    try:
        last_sync = float(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        last_sync = 0.0
    if current_time - last_sync < interval_seconds:
        return False

    command = ["scp", "-q", "-B", "-o", "ConnectTimeout=3"]
    if identity_file is not None:
        command.extend(("-i", str(identity_file)))
    command.extend((str(path), target))
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if completed.returncode != 0:
        return False

    write_snapshot_marker(marker, current_time)
    return True


def write_snapshot_marker(path: Path, timestamp: float) -> None:
    path.write_text(f"{timestamp}\n", encoding="utf-8")
    os.chmod(path, 0o600)


def format_statusline(snapshot: dict[str, object]) -> str:
    """Return a compact status line while avoiding any private session detail."""
    windows = snapshot["rate_limits"]
    assert isinstance(windows, dict)
    values: list[str] = []
    for label, key in (("5H", "five_hour"), ("7D", "seven_day")):
        window = windows.get(key)
        if isinstance(window, dict) and isinstance(window.get("percent_remaining"), int):
            values.append(f"{label} {window['percent_remaining']}%")
    return f"Claude · {' · '.join(values)}" if values else "Claude"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Capture Claude Code rate limits for Frame One.")
    parser.add_argument("--output", type=Path, required=True, help="Local snapshot JSON path")
    parser.add_argument(
        "--timezone",
        default="America/New_York",
        help="IANA timezone used when formatting reset timestamps",
    )
    parser.add_argument(
        "--sync-to",
        help="Optional noninteractive SCP target, for example pi@frame-one.local:~/.config/frame-one/claude-status.json",
    )
    parser.add_argument("--identity-file", type=Path, help="SSH identity used only with --sync-to")
    parser.add_argument(
        "--sync-interval-seconds",
        type=int,
        default=DEFAULT_SYNC_INTERVAL_SECONDS,
        help="Minimum time between successful snapshot copies (default: 900)",
    )
    args = parser.parse_args(argv)

    try:
        statusline_input = json.load(sys.stdin)
        if not isinstance(statusline_input, dict):
            return
        snapshot = snapshot_from_statusline(statusline_input, timezone=ZoneInfo(args.timezone))
    except (json.JSONDecodeError, ValueError):
        return
    if snapshot is None:
        return

    write_snapshot(args.output, snapshot)
    if args.sync_to:
        sync_snapshot(
            args.output,
            args.sync_to,
            identity_file=args.identity_file,
            interval_seconds=max(1, args.sync_interval_seconds),
        )
    print(format_statusline(snapshot))


def _snapshot_window(value: Any, timezone: ZoneInfo) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    used_percentage = value.get("used_percentage")
    resets_at = value.get("resets_at")
    if not isinstance(used_percentage, (int, float)) or isinstance(used_percentage, bool):
        return None
    if not math.isfinite(used_percentage) or not 0 <= used_percentage <= 100:
        return None
    if not isinstance(resets_at, (int, float)) or isinstance(resets_at, bool):
        return None
    if not math.isfinite(resets_at) or resets_at <= 0:
        return None
    return {
        "percent_remaining": round(100 - used_percentage),
        "resets_at": datetime.fromtimestamp(resets_at, timezone).isoformat(timespec="seconds"),
    }


if __name__ == "__main__":
    main()
