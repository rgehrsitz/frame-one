"""Read Claude subscription allowance from the account's own OAuth session.

This is the only method that works without a second machine, so it is the
default for a standalone panel.  The usage endpoint is not part of Anthropic's
published API surface and carries no compatibility promise, so every field is
validated and anything unexpected reports ``unavailable`` rather than a guess.

Only the meter is read: allowance percentages and reset timestamps.  No
conversation, prompt, or project data is requested, and tokens are never
logged, printed, or written anywhere except the credential file.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import tempfile
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen


CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
REDIRECT_URI = "http://localhost:18924/callback"
SCOPES = "user:inference user:profile"
USER_AGENT = "claude-code/2.0.32"
OAUTH_BETA = "oauth-2025-04-20"

# Refresh early rather than discovering expiry mid-round.
REFRESH_SKEW_SECONDS = 600
DEFAULT_EXPIRES_IN = 28800


# --------------------------------------------------------------------------
# One-time authorization
# --------------------------------------------------------------------------


def new_verifier() -> str:
    """Return a fresh PKCE code verifier."""
    return secrets.token_urlsafe(64)[:128]


def new_state() -> str:
    return secrets.token_urlsafe(32)


def challenge_for(verifier: str) -> str:
    """Derive the S256 PKCE challenge for ``verifier``."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def authorization_url(*, verifier: str, state: str) -> str:
    """Build the browser URL the account owner opens to authorize this device."""
    return (
        AUTHORIZE_URL
        + "?"
        + urlencode(
            {
                "response_type": "code",
                "client_id": CLIENT_ID,
                "redirect_uri": REDIRECT_URI,
                "scope": SCOPES,
                "state": state,
                "code_challenge": challenge_for(verifier),
                "code_challenge_method": "S256",
            }
        )
    )


def authorization_code_from(callback_url: str, *, expected_state: str) -> str:
    """Pull the one-time code out of the pasted callback URL.

    The ``state`` value is verified rather than merely sent: it is what ties the
    pasted URL back to the authorization this process actually started.
    """
    query = parse_qs(urlparse(callback_url.strip()).query)
    returned_state = (query.get("state") or [None])[0]
    if returned_state != expected_state:
        raise ValueError("callback state does not match this authorization attempt")
    code = (query.get("code") or [None])[0]
    if not code:
        raise ValueError("callback URL contains no authorization code")
    return code


# --------------------------------------------------------------------------
# Credentials
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Credentials:
    access_token: str
    refresh_token: str
    expires_at: float  # epoch seconds

    def expiring(self, now: float) -> bool:
        return self.expires_at - now <= REFRESH_SKEW_SECONDS

    def as_json(self) -> dict[str, object]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_json(cls, value: Any) -> "Credentials":
        if not isinstance(value, dict):
            raise ValueError("credentials must be an object")
        access = value.get("access_token")
        refresh = value.get("refresh_token")
        expires = value.get("expires_at")
        if not isinstance(access, str) or not access:
            raise ValueError("missing access_token")
        if not isinstance(refresh, str) or not refresh:
            raise ValueError("missing refresh_token")
        if not isinstance(expires, (int, float)) or isinstance(expires, bool):
            raise ValueError("missing expires_at")
        return cls(access_token=access, refresh_token=refresh, expires_at=float(expires))

    @classmethod
    def from_token_response(cls, payload: Any, *, now: float, previous: "Credentials | None" = None) -> "Credentials":
        if not isinstance(payload, dict):
            raise ValueError("token response must be an object")
        access = payload.get("access_token")
        if not isinstance(access, str) or not access:
            raise ValueError("token response has no access_token")
        refresh = payload.get("refresh_token")
        if not isinstance(refresh, str) or not refresh:
            # A refresh response may legitimately omit a new refresh token.
            if previous is None:
                raise ValueError("token response has no refresh_token")
            refresh = previous.refresh_token
        expires_in = payload.get("expires_in")
        if not isinstance(expires_in, (int, float)) or isinstance(expires_in, bool) or expires_in <= 0:
            expires_in = DEFAULT_EXPIRES_IN
        return cls(access_token=access, refresh_token=refresh, expires_at=now + float(expires_in))


def write_credentials(path: Path, credentials: Credentials) -> None:
    """Replace the credential file atomically, owner-readable only."""
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    encoded = json.dumps(credentials.as_json(), indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        handle.write(encoded)
        temporary = Path(handle.name)
    try:
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


def read_credentials(path: Path) -> Credentials:
    return Credentials.from_json(json.loads(path.read_text(encoding="utf-8")))


def post_json(url: str, body: dict[str, object], *, opener: Callable[..., Any] = urlopen) -> Any:
    request = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    with opener(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def exchange_authorization_code(
    code: str,
    *,
    verifier: str,
    state: str,
    credentials_path: Path,
    opener: Callable[..., Any] = urlopen,
    now: Callable[[], float] = time.time,
) -> Credentials:
    """Trade a one-time authorization code for a stored credential."""
    payload = post_json(
        TOKEN_URL,
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
            "state": state,
        },
        opener=opener,
    )
    credentials = Credentials.from_token_response(payload, now=now())
    write_credentials(credentials_path, credentials)
    return credentials


# --------------------------------------------------------------------------
# Provider
# --------------------------------------------------------------------------


def _reset_timestamp(value: Any) -> str | None:
    """Normalize a reset marker to a local ISO string, or None if unusable."""
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone().isoformat(timespec="seconds")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return datetime.fromtimestamp(float(value), timezone.utc).astimezone().isoformat(timespec="seconds")
    return None


def _window(value: Any) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    utilization = value.get("utilization")
    if not isinstance(utilization, (int, float)) or isinstance(utilization, bool):
        return None
    if not 0 <= utilization <= 100:
        return None
    return {
        "percent_remaining": max(0, min(100, round(100 - utilization))),
        "resets_at": _reset_timestamp(value.get("resets_at")),
    }


class ClaudeUsageProvider:
    """Fetch the five-hour and seven-day allowance for the signed-in account."""

    def __init__(
        self,
        credentials_path: Path,
        *,
        opener: Callable[..., Any] = urlopen,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._path = credentials_path
        self._opener = opener
        self._now = now

    def get(self) -> dict[str, object]:
        try:
            credentials = read_credentials(self._path)
        except (OSError, ValueError, json.JSONDecodeError):
            # Nothing authorized yet: the panel shows an em dash and the setup
            # step is a person's job, not something to retry into.
            return {"state": "needs_setup", "data": {}}

        try:
            if credentials.expiring(self._now()):
                credentials = self._refresh(credentials)
            try:
                payload = self._usage(credentials)
            except HTTPError as error:
                if error.code != 401:
                    raise
                # The token was rejected earlier than its stated expiry.
                credentials = self._refresh(credentials)
                payload = self._usage(credentials)
            return self._parse(payload)
        except (OSError, URLError, TimeoutError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return {"state": "unavailable", "data": {}}

    def _refresh(self, credentials: Credentials) -> Credentials:
        payload = self._post(
            TOKEN_URL,
            {
                "grant_type": "refresh_token",
                "refresh_token": credentials.refresh_token,
                "client_id": CLIENT_ID,
            },
        )
        refreshed = Credentials.from_token_response(payload, now=self._now(), previous=credentials)
        write_credentials(self._path, refreshed)
        return refreshed

    def _post(self, url: str, body: dict[str, object]) -> Any:
        return post_json(url, body, opener=self._opener)

    def _usage(self, credentials: Credentials) -> Any:
        request = Request(
            USAGE_URL,
            headers={
                "Authorization": f"Bearer {credentials.access_token}",
                "anthropic-beta": OAUTH_BETA,
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        with self._opener(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _parse(payload: Any) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("usage response must be an object")
        five_hour = _window(payload.get("five_hour"))
        seven_day = _window(payload.get("seven_day"))
        if five_hour is None and seven_day is None:
            raise ValueError("usage response has no usable window")
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
