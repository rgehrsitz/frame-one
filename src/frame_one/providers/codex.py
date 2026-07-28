"""Read Codex allowance from its documented local App Server protocol."""

from __future__ import annotations

import json
import subprocess
import threading
from datetime import datetime, timezone
from typing import Any, Callable


DEFAULT_TIMEOUT_SECONDS = 30
_RATE_LIMIT_REQUEST_ID = 2


def _run_app_server(
    command: list[str],
    *,
    input: str,
    stop_id: int,
    timeout: float,
    **_: object,
) -> subprocess.CompletedProcess[str]:
    """Send app-server requests and read the reply before closing stdin.

    The App Server answers ``account/rateLimits/read`` from its backend, which
    takes longer than writing the request.  ``subprocess.run`` closes stdin as
    soon as the request is written, and the server treats that EOF as a
    shutdown, so the reply never arrives.  Hold stdin open until the matching
    response has been read instead.
    """
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    assert process.stdin is not None and process.stdout is not None
    lines: list[str] = []
    answered = False
    watchdog = threading.Timer(timeout, process.kill)
    watchdog.start()
    try:
        process.stdin.write(input)
        process.stdin.flush()
        for line in process.stdout:
            lines.append(line)
            if _is_response_to(line, stop_id):
                answered = True
                break
    except OSError:
        pass
    finally:
        watchdog.cancel()
        for stream in (process.stdin, process.stdout):
            try:
                stream.close()
            except OSError:
                pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    return subprocess.CompletedProcess(command, 0 if answered else 1, stdout="".join(lines), stderr="")


def _is_response_to(line: str, request_id: int) -> bool:
    try:
        return json.loads(line).get("id") == request_id
    except (json.JSONDecodeError, AttributeError):
        return False


def _window_label(minutes: Any) -> str:
    value = int(minutes)
    if value == 7 * 24 * 60:
        return "WEEK"
    if value >= 60 and value % 60 == 0:
        return f"{value // 60}-HOUR"
    return f"{value}-MIN"


def _reset_time(value: Any) -> str:
    return datetime.fromtimestamp(int(value), tz=timezone.utc).astimezone().isoformat()


def _normalise_window(window: dict[str, Any]) -> dict[str, object]:
    used = float(window["usedPercent"])
    return {
        "label": _window_label(window["windowDurationMins"]),
        "percent_remaining": max(0, min(100, round(100 - used))),
        "resets_at": _reset_time(window["resetsAt"]),
    }


class CodexRateLimitProvider:
    """Call ``account/rateLimits/read`` without reading Codex token storage."""

    def __init__(
        self,
        runner: Callable[..., subprocess.CompletedProcess[str]] = _run_app_server,
        *,
        command: str = "codex",
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._runner = runner
        self._command = command
        self._timeout = timeout

    def get(self) -> dict[str, object]:
        messages = "\n".join(
            (
                json.dumps(
                    {
                        "method": "initialize",
                        "id": 1,
                        "params": {
                            "clientInfo": {
                                "name": "frame-one",
                                "title": "Frame One",
                                "version": "0.1.0",
                            }
                        },
                    }
                ),
                json.dumps({"method": "initialized", "params": {}}),
                json.dumps(
                    {"method": "account/rateLimits/read", "id": _RATE_LIMIT_REQUEST_ID, "params": {}}
                ),
            )
        ) + "\n"
        try:
            completed = self._runner(
                [self._command, "app-server"],
                input=messages,
                stop_id=_RATE_LIMIT_REQUEST_ID,
                text=True,
                capture_output=True,
                timeout=self._timeout,
                check=False,
            )
            if completed.returncode:
                raise ValueError("app-server failed")
            for line in completed.stdout.splitlines():
                try:
                    response = json.loads(line)
                except json.JSONDecodeError:
                    # The server interleaves unrelated notifications on stdout.
                    continue
                if response.get("id") == _RATE_LIMIT_REQUEST_ID:
                    if "error" in response:
                        raise ValueError("rate-limit request failed")
                    return self._parse(response["result"])
            raise ValueError("rate-limit response not found")
        except (OSError, TimeoutError, ValueError, TypeError, KeyError, json.JSONDecodeError, subprocess.SubprocessError):
            return {"state": "unavailable", "data": {}}

    @staticmethod
    def _parse(result: Any) -> dict[str, object]:
        if not isinstance(result, dict):
            raise ValueError("invalid rate-limit result")
        limits = result.get("rateLimits")
        if not isinstance(limits, dict):
            raise ValueError("missing rate limits")
        primary = limits.get("primary")
        if not isinstance(primary, dict):
            raise ValueError("missing primary rate limit")
        primary_data = _normalise_window(primary)
        secondary = limits.get("secondary")
        secondary_data = _normalise_window(secondary) if isinstance(secondary, dict) else None
        # Frame One is intentionally a weekly-budget display for Codex. Some
        # plans expose a shorter primary window too; when the App Server also
        # returns an actual weekly secondary window, display that one instead.
        displayed = secondary_data if secondary_data and secondary_data["label"] == "WEEK" else primary_data
        if displayed["label"] != "WEEK":
            raise ValueError("Codex did not provide a weekly rate-limit window")
        data: dict[str, object] = {
            "window_label": displayed["label"],
            "percent_remaining": displayed["percent_remaining"],
            "resets_at": displayed["resets_at"],
        }
        return {"state": "ok", "data": data}
