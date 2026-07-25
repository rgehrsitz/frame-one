"""Live Quote-of-the-Day adapter.

The adapter deliberately has no bundled quote list, persistent cache, or
fallback quote.  A failed request is represented as unavailable so the caller
can keep the previous display image instead of presenting stale content.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable
from urllib.request import urlopen


ZENQUOTES_TODAY_URL = "https://zenquotes.io/api/today"
MAX_QUOTE_LENGTH = 88
MAX_AUTHOR_LENGTH = 42


@dataclass(frozen=True)
class Quote:
    text: str
    attribution: str

    def as_provider(self) -> dict[str, object]:
        return {
            "state": "ok",
            "data": {
                "text": self.text,
                "attribution": f"— {self.attribution}",
                "source": "ZenQuotes",
            },
        }


class DailyQuoteProvider:
    """Retrieve one suitable live quote from ZenQuotes, without caching it."""

    def __init__(
        self,
        opener: Callable[..., Any] = urlopen,
        *,
        url: str = ZENQUOTES_TODAY_URL,
    ) -> None:
        self._opener = opener
        self._url = url

    def get(self) -> Quote | None:
        try:
            with self._opener(self._url, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, TimeoutError, ValueError, json.JSONDecodeError):
            return None
        return self._parse(payload)

    @staticmethod
    def _parse(payload: Any) -> Quote | None:
        if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
            return None
        raw_quote = payload[0].get("q")
        raw_author = payload[0].get("a")
        if not isinstance(raw_quote, str) or not isinstance(raw_author, str):
            return None
        quote = " ".join(raw_quote.split())
        author = " ".join(raw_author.split())
        if not quote or not author or len(quote) > MAX_QUOTE_LENGTH or len(author) > MAX_AUTHOR_LENGTH:
            return None
        return Quote(text=quote, attribution=author)


def quote_provider_state() -> dict[str, object]:
    """Produce the renderer's normalized quote envelope, never from cache."""
    quote = DailyQuoteProvider().get()
    if quote is None:
        return {"state": "unavailable", "data": {}}
    return quote.as_provider()
