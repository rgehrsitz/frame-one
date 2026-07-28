from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request

from frame_one.gmail_login import GoogleClient, authorization_url, exchange_code, load_client, write_token


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


class GmailLoginTests(unittest.TestCase):
    def test_loads_downloaded_desktop_client(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "client.json"
            path.write_text(json.dumps({"installed": {"client_id": "id", "client_secret": "secret"}}))
            client = load_client(path)

        self.assertEqual(client, GoogleClient("id", "secret", "https://accounts.google.com/o/oauth2/v2/auth", "https://oauth2.googleapis.com/token"))

    def test_rejects_non_desktop_client_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "client.json"
            path.write_text(json.dumps({"web": {"client_id": "id", "client_secret": "secret"}}))
            with self.assertRaisesRegex(ValueError, "Desktop"):
                load_client(path)

    def test_authorization_requests_readonly_offline_pkce_access(self) -> None:
        client = GoogleClient("id", "secret", "https://accounts.example/auth", "https://accounts.example/token")
        query = parse_qs(urlparse(authorization_url(client, redirect_uri="http://127.0.0.1:8765/", state="state", verifier="v" * 43)).query)

        self.assertEqual(query["scope"], ["https://www.googleapis.com/auth/gmail.readonly"])
        self.assertEqual(query["access_type"], ["offline"])
        self.assertEqual(query["prompt"], ["consent"])
        self.assertEqual(query["state"], ["state"])
        self.assertEqual(query["code_challenge_method"], ["S256"])

    def test_exchanges_code_and_writes_owner_only_refreshable_token(self) -> None:
        client = GoogleClient("id", "secret", "https://accounts.example/auth", "https://accounts.example/token")
        seen: list[Request] = []

        def opener(request: Request, **kwargs: object) -> FakeResponse:
            seen.append(request)
            return FakeResponse({"access_token": "access", "refresh_token": "refresh", "expires_in": 3600})

        moment = datetime(2026, 7, 28, tzinfo=timezone.utc)
        token = exchange_code(
            client,
            code="code",
            redirect_uri="http://127.0.0.1:8765/",
            verifier="verifier",
            opener=opener,
            now=lambda: moment,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gmail.token.json"
            write_token(path, token)
            stored = json.loads(path.read_text())
            mode = path.stat().st_mode & 0o777

        self.assertEqual(seen[0].full_url, "https://accounts.example/token")
        self.assertEqual(stored["refresh_token"], "refresh")
        self.assertEqual(stored["expiry"], "2026-07-28T01:00:00+00:00")
        self.assertEqual(mode, 0o600)


if __name__ == "__main__":
    unittest.main()
