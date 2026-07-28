"""Read the Gmail INBOX unread count from label metadata only."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen


GMAIL_INBOX_URL = "https://gmail.googleapis.com/gmail/v1/users/me/labels/INBOX"
EXPIRY_SKEW = timedelta(minutes=5)


def _expires_soon(credentials: dict[str, Any]) -> bool:
    expiry = credentials.get("expiry")
    if not isinstance(expiry, str):
        return True
    try:
        parsed = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed <= datetime.now(timezone.utc) + EXPIRY_SKEW
    except ValueError:
        return True


class GmailUnreadProvider:
    """Use an existing read-only OAuth token; never fetch email messages."""

    def __init__(self, token_path: Path, opener: Callable[..., Any] = urlopen) -> None:
        self._token_path = token_path
        self._opener = opener

    def get(self) -> dict[str, object]:
        try:
            credentials = json.loads(self._token_path.read_text(encoding="utf-8"))
            if not isinstance(credentials, dict):
                raise ValueError("token must be an object")
            token = self._access_token(credentials)
            request = Request(GMAIL_INBOX_URL, headers={"Authorization": f"Bearer {token}"})
            with self._opener(request, timeout=10) as response:
                label = json.loads(response.read().decode("utf-8"))
            unread = label["messagesUnread"]
            if isinstance(unread, bool) or int(unread) < 0:
                raise ValueError("invalid unread count")
            return {"state": "ok", "data": {"unread": int(unread)}}
        except (OSError, TimeoutError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return {"state": "unavailable", "data": {}}

    def _access_token(self, credentials: dict[str, Any]) -> str:
        token = credentials.get("token")
        if isinstance(token, str) and token and not _expires_soon(credentials):
            return token
        refresh_token = credentials.get("refresh_token")
        client_id = credentials.get("client_id")
        client_secret = credentials.get("client_secret")
        token_uri = credentials.get("token_uri", "https://oauth2.googleapis.com/token")
        if not all(isinstance(value, str) and value for value in (refresh_token, client_id, client_secret, token_uri)):
            raise ValueError("refreshable OAuth credentials required")
        body = urlencode(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            }
        ).encode("utf-8")
        request = Request(str(token_uri), data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
        with self._opener(request, timeout=10) as response:
            refreshed = json.loads(response.read().decode("utf-8"))
        fresh_token = refreshed.get("access_token")
        expires_in = refreshed.get("expires_in")
        if not isinstance(fresh_token, str) or not fresh_token:
            raise ValueError("refresh did not provide an access token")
        credentials["token"] = fresh_token
        credentials["expiry"] = (datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))).isoformat()
        self._token_path.write_text(json.dumps(credentials, indent=2) + "\n", encoding="utf-8")
        self._token_path.chmod(0o600)
        return fresh_token
