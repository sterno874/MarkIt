from __future__ import annotations

from types import SimpleNamespace

from app.cogs.markit import strip_bot_mentions


def test_strip_bot_mentions() -> None:
    bot = SimpleNamespace(id=12345)
    assert strip_bot_mentions("<@12345> AAPL", bot) == "AAPL"
    assert strip_bot_mentions("<@!12345> chart NVDA", bot) == "chart NVDA"
    assert strip_bot_mentions("@MarkIt apples volume", bot) == "apples volume"
    assert strip_bot_mentions("<@12345>", bot) == ""
