from __future__ import annotations

from app.security import normalize_symbol
from app.services.markit_nl import parse_local


def test_chart_aapl() -> None:
    intent = parse_local("show me the chart on aapl")
    assert intent is not None
    assert intent.action == "chart"
    assert intent.symbol and "AAPL" in intent.symbol.upper()


def test_apples_volume_week() -> None:
    """Company name + volume + period — the ask that previously became APPLES=X."""
    assert normalize_symbol("apples") == "AAPL"
    assert normalize_symbol("APPLES") == "AAPL"
    intent = parse_local("show me apples volume for the past week")
    assert intent is not None
    assert intent.action == "volume"
    assert intent.symbol == "AAPL"
    assert intent.period == "5d"


def test_apples_not_fx() -> None:
    assert not normalize_symbol("APPLES").endswith("=X")
    assert not normalize_symbol("VOLUME").endswith("=X")


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


def test_filings_and_pill_verbs() -> None:
    filings = parse_local("filings for MSFT")
    assert filings and filings.action == "filings"
    assert filings.symbol == "MSFT"
    pill = parse_local("pill for AAPL")
    assert pill and pill.action == "quote"
    assert pill.symbol == "AAPL"


def test_bid_ask_routes_to_book() -> None:
    intent = parse_local("what's the bid on AAPL")
    assert intent is not None
    assert intent.action == "book"
    assert intent.symbol == "AAPL"
    spr = parse_local("AAPL spread")
    assert spr and spr.action == "book"
