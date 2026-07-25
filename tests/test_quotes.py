from __future__ import annotations

import unittest

from frame_one.providers.quotes import DailyQuoteProvider


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None


class QuoteProviderTests(unittest.TestCase):
    def test_returns_normalized_live_quote(self) -> None:
        provider = DailyQuoteProvider(
            opener=lambda *args, **kwargs: _Response(b'[{"q":"Make it work.","a":"Kent Beck"}]')
        )
        quote = provider.get()

        self.assertIsNotNone(quote)
        self.assertEqual(quote.text, "Make it work.")
        self.assertEqual(quote.as_provider()["data"]["attribution"], "— Kent Beck")

    def test_invalid_or_overlong_response_has_no_fallback(self) -> None:
        too_long = "x" * 89
        provider = DailyQuoteProvider(
            opener=lambda *args, **kwargs: _Response(
                ('[{"q":"' + too_long + '","a":"Author"}]').encode()
            )
        )

        self.assertIsNone(provider.get())

    def test_network_failure_has_no_fallback(self) -> None:
        def unavailable(*args: object, **kwargs: object) -> object:
            raise OSError("offline")

        self.assertIsNone(DailyQuoteProvider(opener=unavailable).get())


if __name__ == "__main__":
    unittest.main()
