"""One-time Claude authorization for a standalone Frame One panel.

Run this on the Pi.  It prints a URL, you approve it in a browser on any
machine, and the authorization lands back here by itself: the command serves
the redirect it asked for on loopback, so there is nothing to copy by hand.

A headless Pi has no browser of its own, so the browser that approves the
request is usually on another machine.  Forward the port when you connect and
the redirect still reaches the Pi, which keeps the credential on the panel
rather than routing it through a laptop:

    ssh -L 18924:localhost:18924 you@frame-one.local

``--paste`` keeps the original flow for anywhere that cannot be forwarded.
No token is ever printed back to the terminal.
"""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import sys
import time
from urllib.parse import parse_qs, urlparse

from .providers.claude_oauth import (
    REDIRECT_URI,
    authorization_code_from,
    authorization_url,
    exchange_authorization_code,
    new_state,
    new_verifier,
)


DEFAULT_CREDENTIALS = Path.home() / ".config" / "frame-one" / "claude-oauth.json"
DEFAULT_TIMEOUT_SECONDS = 300

# Longest a single accepted connection may hold the server before it is dropped.
# Generous for a real redirect, short enough that a silent one costs little.
CONNECTION_READ_TIMEOUT = 10.0

_PAGE = """<!doctype html>
<html lang="en"><meta charset="utf-8"><title>Frame One</title>
<body style="font:16px system-ui;margin:4rem auto;max-width:28rem;text-align:center">
<h1 style="font-size:1.25rem">{heading}</h1><p>{detail}</p></body></html>
"""


class _CallbackServer(HTTPServer):
    """A one-shot loopback server that cannot be stalled by a silent caller.

    ``HTTPServer.timeout`` bounds only the wait for a connection.  Once one is
    accepted, the handler's reads block with no timeout of their own, so a
    browser preconnect -- a socket opened speculatively and left silent -- would
    hold this single-threaded server forever: the deadline would never be
    rechecked, and the connection carrying the real redirect would never be
    accepted.  Capping each accepted connection by whatever is left of the
    authorization deadline keeps control coming back to the loop.
    """

    def __init__(self, address: tuple[str, int], handler: type, *, deadline_in: object) -> None:
        super().__init__(address, handler)
        self._deadline_in = deadline_in

    def finish_request(self, request: object, client_address: object) -> None:
        remaining = self._deadline_in()  # type: ignore[operator]
        request.settimeout(max(0.1, min(CONNECTION_READ_TIMEOUT, remaining)))  # type: ignore[attr-defined]
        super().finish_request(request, client_address)  # type: ignore[arg-type]


class _CallbackHandler(BaseHTTPRequestHandler):
    """Accept exactly the one redirect this run asked for, and nothing else."""

    def do_GET(self) -> None:  # noqa: N802 - name fixed by BaseHTTPRequestHandler
        request = urlparse(self.path)
        if request.path != urlparse(REDIRECT_URI).path:
            # Browsers ask for /favicon.ico and friends; they are not the answer.
            self.send_response(404)
            self.end_headers()
            return

        query = parse_qs(request.query)
        returned_state = (query.get("state") or [None])[0]
        error = (query.get("error") or [None])[0]
        code = (query.get("code") or [None])[0]

        if error:
            self._finish(400, "Authorization declined", "Nothing was written. You can close this tab.")
            self.server.failure = f"the authorization was declined ({error})"  # type: ignore[attr-defined]
        elif returned_state != self.server.expected_state:  # type: ignore[attr-defined]
            # This is what ties the redirect to the authorization this process
            # started, so a mismatch is refused rather than merely noted.
            self._finish(400, "Mismatched request", "Nothing was written. You can close this tab.")
            self.server.failure = "callback state does not match this authorization attempt"  # type: ignore[attr-defined]
        elif not code:
            self._finish(400, "No authorization code", "Nothing was written. You can close this tab.")
            self.server.failure = "callback URL contains no authorization code"  # type: ignore[attr-defined]
        else:
            self._finish(200, "Frame One is authorized", "You can close this tab and return to the terminal.")
            self.server.captured = code  # type: ignore[attr-defined]

    def _finish(self, status: int, heading: str, detail: str) -> None:
        body = _PAGE.format(heading=heading, detail=detail).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        """Stay silent: the request line carries the authorization code."""


def capture_authorization_code(
    *,
    expected_state: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    monotonic: object = time.monotonic,
) -> str:
    """Serve the redirect on loopback and return the code the browser brings.

    Binding loopback rather than every interface keeps the one-time code off
    the network: only this machine, or a tunnel someone deliberately opened to
    it, can deliver the redirect.
    """
    redirect = urlparse(REDIRECT_URI)
    deadline = monotonic() + timeout_seconds  # type: ignore[operator]
    server = _CallbackServer(
        (redirect.hostname or "127.0.0.1", redirect.port or 80),
        _CallbackHandler,
        deadline_in=lambda: deadline - monotonic(),  # type: ignore[operator]
    )
    server.timeout = 1
    server.expected_state = expected_state  # type: ignore[attr-defined]
    server.captured = None  # type: ignore[attr-defined]
    server.failure = None  # type: ignore[attr-defined]

    try:
        while server.captured is None and server.failure is None:  # type: ignore[attr-defined]
            if monotonic() >= deadline:  # type: ignore[operator]
                raise TimeoutError(f"no authorization arrived within {timeout_seconds} seconds")
            server.handle_request()
    finally:
        server.server_close()

    if server.failure is not None:  # type: ignore[attr-defined]
        raise ValueError(server.failure)  # type: ignore[attr-defined]
    return server.captured  # type: ignore[attr-defined,return-value]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Authorize Frame One to read your Claude allowance.")
    parser.add_argument(
        "--credentials",
        type=Path,
        default=DEFAULT_CREDENTIALS,
        help=f"Where to store the OAuth credential (default: {DEFAULT_CREDENTIALS})",
    )
    parser.add_argument(
        "--paste",
        action="store_true",
        help="Paste the callback URL by hand instead of serving the redirect",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"How long to wait for the browser (default: {DEFAULT_TIMEOUT_SECONDS})",
    )
    args = parser.parse_args(argv)

    verifier = new_verifier()
    state = new_state()

    print("\nFrame One — Claude authorization")
    print("=" * 58)
    print("\n1. Open this URL in a browser on any machine:\n")
    print(f"   {authorization_url(verifier=verifier, state=state)}\n")
    print("2. Approve the request.")

    try:
        code = _paste(state) if args.paste else _listen(state, args.timeout_seconds)
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled; nothing was written.")
        return 1
    except (OSError, TimeoutError, ValueError) as error:
        print(f"\nDid not get an authorization: {error}")
        return 1
    if code is None:
        return 1

    try:
        exchange_authorization_code(
            code, verifier=verifier, state=state, credentials_path=args.credentials
        )
    except Exception as error:  # noqa: BLE001 - report the kind of failure, never the token
        print(f"Token exchange failed: {type(error).__name__}")
        return 1

    print(f"\nAuthorized. Credential written to {args.credentials} (owner-readable only).")
    print("The panel picks it up on its next refresh.\n")
    return 0


def _listen(state: str, timeout_seconds: int) -> str:
    redirect = urlparse(REDIRECT_URI)
    print(f"3. Waiting for the approval to come back on {REDIRECT_URI} ...")
    print("   (headless box? reconnect with")
    print(f"    ssh -L {redirect.port}:localhost:{redirect.port} you@this-host )\n")
    try:
        return capture_authorization_code(expected_state=state, timeout_seconds=timeout_seconds)
    except TimeoutError:
        # TimeoutError subclasses OSError, and nobody waiting for a browser that
        # never came wants to land on a blocking input() prompt instead.
        raise
    except OSError as error:
        # Something already holds the port, so the redirect cannot be served
        # here.  Hand the person the flow that needs no listener at all.
        print(f"   Could not serve the redirect ({error.strerror or error}).")
        print("   Falling back to pasting the URL by hand.\n")
        return _paste(state)


def _paste(state: str) -> str:
    print("3. Your browser will fail to load a localhost page. That is expected.")
    print("   Copy the FULL address from the browser's address bar.\n")
    callback = input("Paste the callback URL here: ").strip()
    if not callback:
        raise ValueError("nothing pasted")
    return authorization_code_from(callback, expected_state=state)


if __name__ == "__main__":
    sys.exit(main())
