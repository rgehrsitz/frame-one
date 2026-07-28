"""One-time Claude authorization for a standalone Frame One panel.

Run this once on the Pi.  It prints a URL, you open it in a browser on any
machine, approve, and paste the address bar back.  Nothing else in Frame One
prompts for credentials, and no token is ever printed back to the terminal.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .providers.claude_oauth import (
    authorization_code_from,
    authorization_url,
    exchange_authorization_code,
    new_state,
    new_verifier,
)


DEFAULT_CREDENTIALS = Path.home() / ".config" / "frame-one" / "claude-oauth.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Authorize Frame One to read your Claude allowance.")
    parser.add_argument(
        "--credentials",
        type=Path,
        default=DEFAULT_CREDENTIALS,
        help=f"Where to store the OAuth credential (default: {DEFAULT_CREDENTIALS})",
    )
    args = parser.parse_args(argv)

    verifier = new_verifier()
    state = new_state()

    print("\nFrame One — Claude authorization")
    print("=" * 58)
    print("\n1. Open this URL in a browser on any machine:\n")
    print(f"   {authorization_url(verifier=verifier, state=state)}\n")
    print("2. Approve the request.")
    print("3. Your browser will fail to load a localhost page. That is expected.")
    print("   Copy the FULL address from the browser's address bar.\n")

    try:
        callback = input("Paste the callback URL here: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled; nothing was written.")
        return 1

    if not callback:
        print("Nothing pasted; cancelled.")
        return 1

    try:
        code = authorization_code_from(callback, expected_state=state)
    except ValueError as error:
        print(f"Could not use that URL: {error}")
        return 1

    try:
        exchange_authorization_code(
            code, verifier=verifier, state=state, credentials_path=args.credentials
        )
    except Exception as error:  # noqa: BLE001 - report the kind of failure, never the token
        print(f"Token exchange failed: {type(error).__name__}")
        return 1

    print(f"\nAuthorized. Credential written to {args.credentials} (owner-readable only).")
    print("Add this to your render command:\n")
    print(f"   --claude-oauth-credentials {args.credentials}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
