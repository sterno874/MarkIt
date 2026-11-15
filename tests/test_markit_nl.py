from __future__ import annotations

from app.services.markit_nl import parse_local


def test_chart_aapl() -> None:
    intent = parse_local("show me the chart on aapl")
    assert intent is not None
    assert intent.action == "chart"
    assert intent.symbol and "AAPL" in intent.symbol.upper()


def test_news_nvda() -> None:
    intent = parse_local("news for NVDA")
    assert intent is not None
    assert intent.action == "news"
    assert "NVDA" in (intent.symbol or "").upper()


def test_compare_with_period() -> None:
    intent = parse_local("compare AAPL and MSFT over a year")
    assert intent is not None
    assert intent.action == "compare"
    assert len(intent.symbols) >= 2
    assert intent.period == "1y"


def test_uses_last_ticker() -> None:
    intent = parse_local("show the chart", last_ticker="TSLA")
    assert intent is not None
    assert intent.action == "chart"
    assert intent.symbol == "TSLA"


def test_bare_ticker_quotes() -> None:
    intent = parse_local("BTC")
    assert intent is not None
    assert intent.action == "quote"


def test_fgi() -> None:
    intent = parse_local("fear and greed")
    assert intent is not None
    assert intent.action == "fgi"


def test_period_3m() -> None:
    intent = parse_local("chart AAPL for 3 months")
    assert intent is not None
    assert intent.period == "3m"
