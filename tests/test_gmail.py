from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request

from frame_one.providers.gmail import GmailUnreadProvider


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


class GmailUnreadProviderTests(unittest.TestCase):
    def test_reads_the_inbox_unread_thread_count_not_message_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gmail.token.json"
            path.write_text(json.dumps({"token": "access", "expiry": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}))

            def opener(request: Request, **kwargs: object) -> FakeResponse:
                self.assertEqual(request.full_url, "https://gmail.googleapis.com/gmail/v1/users/me/labels/INBOX")
                self.assertEqual(request.get_header("Authorization"), "Bearer access")
                return FakeResponse({"messagesUnread": 19, "threadsUnread": 15})

            state = GmailUnreadProvider(path, opener=opener).get()

        self.assertEqual(state, {"state": "ok", "data": {"unread": 15}})

    def test_refreshes_expired_access_token_without_logging_mail_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gmail.token.json"
            path.write_text(
                json.dumps(
                    {
                        "token": "expired",
                        "expiry": "2020-01-01T00:00:00+00:00",
                        "refresh_token": "refresh",
                        "client_id": "client",
                        "client_secret": "secret",
                        "token_uri": "https://oauth2.example/token",
                    }
                )
            )

            def opener(request: Request, **kwargs: object) -> FakeResponse:
                if request.full_url == "https://oauth2.example/token":
                    return FakeResponse({"access_token": "fresh", "expires_in": 3600})
                self.assertEqual(request.get_header("Authorization"), "Bearer fresh")
                return FakeResponse({"messagesUnread": 3, "threadsUnread": 2})

            state = GmailUnreadProvider(path, opener=opener).get()
            stored = json.loads(path.read_text())

        self.assertEqual(state, {"state": "ok", "data": {"unread": 2}})
        self.assertEqual(stored["token"], "fresh")

    def test_bad_or_missing_token_is_unavailable(self) -> None:
        self.assertEqual(GmailUnreadProvider(Path("missing.token.json")).get(), {"state": "unavailable", "data": {}})
