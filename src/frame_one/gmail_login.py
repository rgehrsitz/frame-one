"""Authorize one local Gmail read-only token for Frame One.

The command runs on the Pi, while the browser can run on a computer connected
over an SSH loopback tunnel.  It writes only the refreshable token envelope the
Gmail unread provider needs; no message data is requested or stored.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import tempfile
import time
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from .providers.claude_oauth import challenge_for, new_verifier


GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
DEFAULT_AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"
DEFAULT_CALLBACK_PORT = 8765
DEFAULT_TOKEN_PATH = Path.home() / ".config" / "frame-one" / "gmail.token.json"


@dataclass(frozen=True)
class GoogleClient:
    client_id: str
    client_secret: str
    auth_uri: str
    token_uri: str


def load_client(path: Path) -> GoogleClient:
    """Load the downloaded credentials for a Google Desktop OAuth client."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("installed"), dict):
        raise ValueError("client secrets must be a Google Desktop client JSON file")
    installed = payload["installed"]
    client_id = installed.get("client_id")
    client_secret = installed.get("client_secret")
    if not isinstance(client_id, str) or not client_id or not isinstance(client_secret, str) or not client_secret:
        raise ValueError("client secrets are missing client_id or client_secret")
    auth_uri = installed.get("auth_uri", DEFAULT_AUTH_URI)
    token_uri = installed.get("token_uri", DEFAULT_TOKEN_URI)
    if not isinstance(auth_uri, str) or not auth_uri or not isinstance(token_uri, str) or not token_uri:
        raise ValueError("client secrets contain an invalid OAuth endpoint")
    return GoogleClient(client_id, client_secret, auth_uri, token_uri)


def authorization_url(client: GoogleClient, *, redirect_uri: str, state: str, verifier: str) -> str:
    """Build a Gmail read-only authorization request with PKCE."""
    return client.auth_uri + "?" + urlencode(
        {
            "client_id": client.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": GMAIL_READONLY_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
            "code_challenge": challenge_for(verifier),
            "code_challenge_method": "S256",
        }
    )


def exchange_code(
    client: GoogleClient,
    *,
    code: str,
    redirect_uri: str,
    verifier: str,
    opener: Callable[..., Any] = urlopen,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict[str, object]:
    """Exchange the one-time code for exactly the refreshable token envelope."""
    body = urlencode(
        {
            "code": code,
            "client_id": client.client_id,
            "client_secret": client.client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": verifier,
        }
    ).encode("utf-8")
    request = Request(client.token_uri, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    with opener(request, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("token response must be an object")
    token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    expires_in = payload.get("expires_in")
    if not isinstance(token, str) or not token or not isinstance(refresh_token, str) or not refresh_token:
        raise ValueError("token response has no refreshable credential")
    if not isinstance(expires_in, (int, float)) or isinstance(expires_in, bool) or expires_in <= 0:
        raise ValueError("token response has invalid expiry")
    return {
        "token": token,
        "expiry": (now() + timedelta(seconds=float(expires_in))).isoformat(),
        "refresh_token": refresh_token,
        "client_id": client.client_id,
        "client_secret": client.client_secret,
        "token_uri": client.token_uri,
    }


def write_token(path: Path, token: dict[str, object]) -> None:
    """Atomically store a credential readable only by the dashboard account."""
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    encoded = json.dumps(token, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        handle.write(encoded)
        temporary = Path(handle.name)
    try:
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


class CallbackServer(HTTPServer):
    code: str | None = None
    error: str | None = None
    expected_state: str


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        query = parse_qs(urlparse(self.path).query)
        server = self.server
        assert isinstance(server, CallbackServer)
        returned_state = (query.get("state") or [None])[0]
        if returned_state != server.expected_state:
            server.error = "callback state did not match"
            message = "Authorization could not be verified. Return to Frame One."
        else:
            server.error = (query.get("error") or [None])[0]
            server.code = (query.get("code") or [None])[0]
            message = "Frame One is authorized. You can close this page."
        body = f"<!doctype html><title>Frame One</title><p>{message}</p>".encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003 - stdlib API
        return


def wait_for_callback(*, port: int, state: str, timeout_seconds: float) -> str:
    """Listen on Pi loopback until the browser reaches it through SSH."""
    with CallbackServer(("127.0.0.1", port), CallbackHandler) as server:
        server.expected_state = state
        server.timeout = 1
        deadline = time.monotonic() + timeout_seconds
        while server.code is None and server.error is None and time.monotonic() < deadline:
            server.handle_request()
        if server.code:
            return server.code
        if server.error:
            raise ValueError(f"Google authorization failed: {server.error}")
    raise TimeoutError("authorization timed out")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Authorize Frame One to read the Gmail INBOX unread count.")
    parser.add_argument("--client-secrets", type=Path, required=True, help="Downloaded Google Desktop OAuth client JSON")
    parser.add_argument("--token", type=Path, default=DEFAULT_TOKEN_PATH, help=f"Credential output (default: {DEFAULT_TOKEN_PATH})")
    parser.add_argument("--callback-port", type=int, default=DEFAULT_CALLBACK_PORT, help="Pi loopback port to receive OAuth callback")
    parser.add_argument("--timeout-seconds", type=float, default=300, help="How long to wait for browser authorization")
    args = parser.parse_args(argv)
    if not 1 <= args.callback_port <= 65535:
        parser.error("--callback-port must be between 1 and 65535")

    try:
        client = load_client(args.client_secrets)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Could not read Google client secrets: {error}")
        return 1

    verifier = new_verifier()
    state = secrets.token_urlsafe(32)
    redirect_uri = f"http://127.0.0.1:{args.callback_port}/"
    print("\nFrame One — Gmail authorization")
    print("=" * 58)
    print("\n1. Forward the Pi callback port from the computer with your browser:")
    print(f"   ssh -N -L {args.callback_port}:127.0.0.1:{args.callback_port} YOUR_PI_USER@frame-one.local")
    print("2. Open this URL in that computer's browser and approve read-only Gmail access:\n")
    print(f"   {authorization_url(client, redirect_uri=redirect_uri, state=state, verifier=verifier)}\n")
    print("Waiting for the browser callback...")

    try:
        code = wait_for_callback(port=args.callback_port, state=state, timeout_seconds=max(1, args.timeout_seconds))
        token = exchange_code(client, code=code, redirect_uri=redirect_uri, verifier=verifier)
        write_token(args.token, token)
    except (OSError, TimeoutError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"Authorization failed: {type(error).__name__}")
        return 1

    print(f"Authorized. Credential written to {args.token} (owner-readable only).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
