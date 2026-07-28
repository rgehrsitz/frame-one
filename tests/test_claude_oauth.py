from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import stat
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

from frame_one.providers.claude_oauth import (
    CLIENT_ID,
    REDIRECT_URI,
    REFRESH_SKEW_SECONDS,
    ClaudeUsageProvider,
    Credentials,
    authorization_code_from,
    authorization_url,
    challenge_for,
    exchange_authorization_code,
    new_state,
    new_verifier,
    read_credentials,
    write_credentials,
)


USAGE = {
    "five_hour": {"utilization": 23, "resets_at": "2026-07-28T19:00:00Z"},
    "seven_day": {"utilization": 41, "resets_at": "2026-08-02T00:00:00Z"},
}


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class FakeHttp:
    """Records requests and replays scripted responses."""

    def __init__(self, *responses: object) -> None:
        self._responses = list(responses)
        self.requests: list[object] = []

    def __call__(self, request: object, timeout: float | None = None) -> FakeResponse:
        self.requests.append(request)
        reply = self._responses.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return FakeResponse(reply)


class PkceTests(unittest.TestCase):
    def test_the_challenge_is_the_unpadded_s256_of_the_verifier(self) -> None:
        verifier = "a" * 64
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()

        self.assertEqual(challenge_for(verifier), expected)
        self.assertNotIn("=", challenge_for(verifier))

    def test_a_verifier_stays_within_the_rfc_length_limit(self) -> None:
        verifier = new_verifier()

        self.assertLessEqual(len(verifier), 128)
        self.assertGreaterEqual(len(verifier), 43)


class AuthorizationUrlTests(unittest.TestCase):
    def test_the_scope_space_is_percent_encoded(self) -> None:
        url = authorization_url(verifier=new_verifier(), state="xyz")

        # The reference implementation joined params by hand, so the space in
        # "user:inference user:profile" produced a malformed URL.
        self.assertNotIn(" ", url)
        query = parse_qs(urlparse(url).query)
        self.assertEqual(query["scope"], ["user:inference user:profile"])
        self.assertEqual(query["client_id"], [CLIENT_ID])
        self.assertEqual(query["code_challenge_method"], ["S256"])

    def test_the_challenge_in_the_url_matches_the_verifier(self) -> None:
        verifier = new_verifier()
        query = parse_qs(urlparse(authorization_url(verifier=verifier, state="s")).query)

        self.assertEqual(query["code_challenge"], [challenge_for(verifier)])


class CallbackTests(unittest.TestCase):
    def test_a_matching_state_yields_the_code(self) -> None:
        url = "http://localhost:18924/callback?code=abc123&state=expected"

        self.assertEqual(authorization_code_from(url, expected_state="expected"), "abc123")

    def test_a_mismatched_state_is_rejected(self) -> None:
        url = "http://localhost:18924/callback?code=abc123&state=attacker"

        # The reference sent `state` but never checked it coming back.
        with self.assertRaisesRegex(ValueError, "state"):
            authorization_code_from(url, expected_state="expected")

    def test_a_callback_without_a_code_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "code"):
            authorization_code_from("http://localhost:18924/callback?state=s", expected_state="s")


class CredentialFileTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "nested" / "claude-oauth.json"

    def test_credentials_round_trip(self) -> None:
        credentials = Credentials(access_token="at", refresh_token="rt", expires_at=1000.0)
        write_credentials(self.path, credentials)

        self.assertEqual(read_credentials(self.path), credentials)

    def test_the_credential_file_is_owner_only(self) -> None:
        write_credentials(self.path, Credentials("at", "rt", 1000.0))

        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)

    def test_a_refresh_response_may_omit_a_new_refresh_token(self) -> None:
        previous = Credentials("old", "keep-me", 0.0)
        refreshed = Credentials.from_token_response(
            {"access_token": "new", "expires_in": 100}, now=500.0, previous=previous
        )

        self.assertEqual(refreshed.refresh_token, "keep-me")
        self.assertEqual(refreshed.expires_at, 600.0)


class AuthorizationCodeExchangeTests(unittest.TestCase):
    """The one-time interactive path: run once, and confusing when it fails."""

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "claude-oauth.json"

    def test_the_exchange_sends_the_verifier_and_stores_the_credential(self) -> None:
        http = FakeHttp({"access_token": "at", "refresh_token": "rt", "expires_in": 3600})

        exchange_authorization_code(
            "the-code",
            verifier="the-verifier",
            state="the-state",
            credentials_path=self.path,
            opener=http,
            now=lambda: 1000.0,
        )

        body = json.loads(http.requests[0].data.decode("utf-8"))
        self.assertEqual(body["grant_type"], "authorization_code")
        self.assertEqual(body["code"], "the-code")
        # The verifier is sent at exchange time, never the challenge.
        self.assertEqual(body["code_verifier"], "the-verifier")
        self.assertNotIn(challenge_for("the-verifier"), json.dumps(body))
        self.assertEqual(body["client_id"], CLIENT_ID)
        self.assertEqual(body["redirect_uri"], REDIRECT_URI)

        stored = read_credentials(self.path)
        self.assertEqual(stored.access_token, "at")
        self.assertEqual(stored.refresh_token, "rt")
        self.assertEqual(stored.expires_at, 4600.0)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)

    def test_a_response_without_a_refresh_token_is_refused(self) -> None:
        http = FakeHttp({"access_token": "at", "expires_in": 3600})

        with self.assertRaisesRegex(ValueError, "refresh_token"):
            exchange_authorization_code(
                "c", verifier="v", state="s", credentials_path=self.path, opener=http, now=lambda: 0.0
            )

        self.assertFalse(self.path.exists(), "a failed exchange must not leave a partial credential")


class UsageProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "claude-oauth.json"

    def _authorize(self, *, expires_at: float = 10_000.0) -> None:
        write_credentials(self.path, Credentials("access", "refresh", expires_at))

    def test_an_unauthorized_panel_reports_needs_setup(self) -> None:
        provider = ClaudeUsageProvider(self.path, opener=FakeHttp(), now=lambda: 0.0)

        self.assertEqual(provider.get(), {"state": "needs_setup", "data": {}})

    def test_utilization_becomes_percent_remaining(self) -> None:
        self._authorize()
        provider = ClaudeUsageProvider(self.path, opener=FakeHttp(USAGE), now=lambda: 0.0)

        state = provider.get()

        self.assertEqual(state["state"], "ok")
        self.assertEqual(state["data"]["window_label"], "5-HOUR")
        self.assertEqual(state["data"]["percent_remaining"], 77)
        self.assertEqual(state["data"]["secondary_label"], "WEEK")
        self.assertEqual(state["data"]["secondary_percent_remaining"], 59)
        self.assertTrue(str(state["data"]["resets_at"]).startswith("2026-07-28"))

    def test_the_usage_request_carries_the_oauth_headers(self) -> None:
        self._authorize()
        http = FakeHttp(USAGE)

        ClaudeUsageProvider(self.path, opener=http, now=lambda: 0.0).get()

        request = http.requests[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer access")
        self.assertEqual(request.get_header("Anthropic-beta"), "oauth-2025-04-20")

    def test_an_expiring_token_is_refreshed_before_use(self) -> None:
        self._authorize(expires_at=100.0)
        http = FakeHttp({"access_token": "fresh", "expires_in": 3600}, USAGE)

        state = ClaudeUsageProvider(
            self.path, opener=http, now=lambda: 100.0 - REFRESH_SKEW_SECONDS + 1
        ).get()

        self.assertEqual(state["state"], "ok")
        self.assertEqual(len(http.requests), 2, "expected a refresh then a usage call")
        self.assertEqual(read_credentials(self.path).access_token, "fresh")

    def test_a_401_triggers_one_refresh_and_retry(self) -> None:
        self._authorize()
        rejected = HTTPError("https://example", 401, "Unauthorized", {}, None)
        http = FakeHttp(rejected, {"access_token": "fresh", "expires_in": 3600}, USAGE)

        state = ClaudeUsageProvider(self.path, opener=http, now=lambda: 0.0).get()

        self.assertEqual(state["state"], "ok")
        self.assertEqual(len(http.requests), 3)

    def test_a_persistent_401_reports_unavailable(self) -> None:
        self._authorize()
        rejected = HTTPError("https://example", 401, "Unauthorized", {}, None)
        http = FakeHttp(rejected, {"access_token": "fresh", "expires_in": 3600}, rejected)

        state = ClaudeUsageProvider(self.path, opener=http, now=lambda: 0.0).get()

        self.assertEqual(state, {"state": "unavailable", "data": {}})

    def test_an_unexpected_payload_shape_fails_closed(self) -> None:
        self._authorize()
        for payload in ({"five_hour": {"utilization": "lots"}}, {"unexpected": True}, [], {"five_hour": None}):
            with self.subTest(payload=payload):
                provider = ClaudeUsageProvider(self.path, opener=FakeHttp(payload), now=lambda: 0.0)
                self.assertEqual(provider.get(), {"state": "unavailable", "data": {}})

    def test_an_out_of_range_utilization_is_refused(self) -> None:
        self._authorize()
        provider = ClaudeUsageProvider(
            self.path, opener=FakeHttp({"five_hour": {"utilization": 150}}), now=lambda: 0.0
        )

        self.assertEqual(provider.get(), {"state": "unavailable", "data": {}})

    def test_one_usable_window_is_enough(self) -> None:
        self._authorize()
        provider = ClaudeUsageProvider(
            self.path, opener=FakeHttp({"five_hour": {"utilization": 10}}), now=lambda: 0.0
        )

        state = provider.get()

        self.assertEqual(state["state"], "ok")
        self.assertEqual(state["data"]["percent_remaining"], 90)
        self.assertIsNone(state["data"]["secondary_percent_remaining"])

    def test_a_missing_reset_timestamp_does_not_sink_the_window(self) -> None:
        self._authorize()
        provider = ClaudeUsageProvider(
            self.path, opener=FakeHttp({"five_hour": {"utilization": 10, "resets_at": "nonsense"}}), now=lambda: 0.0
        )

        state = provider.get()

        self.assertEqual(state["state"], "ok")
        self.assertIsNone(state["data"]["resets_at"])

    def test_no_token_is_present_in_the_rendered_state(self) -> None:
        self._authorize()
        provider = ClaudeUsageProvider(self.path, opener=FakeHttp(USAGE), now=lambda: 0.0)

        rendered = json.dumps(provider.get())

        self.assertNotIn("access", rendered)
        self.assertNotIn("refresh", rendered)
