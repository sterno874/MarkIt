from __future__ import annotations

from app import format as fmt
from app.ui.pill import _book_line, _tick_marker, pill_text
from app.security import Security


def test_accent_day_performance() -> None:
    assert fmt.accent(1.2) == 0x2ECC71
    assert fmt.accent(-0.5) == 0xE74C3C
    assert fmt.accent(0) == 0x95A5A6


def test_tick_marker() -> None:
    assert "▲" in _tick_marker(101.0, 100.0)
    assert "▼" in _tick_marker(99.0, 100.0)
    assert "=" in _tick_marker(100.0, 100.0)
    assert _tick_marker(100.0, None) == ""


def test_pill_text_live_badge() -> None:
    sec = Security(
        symbol="AAPL",
        yahoo="AAPL",
        quote_type="EQUITY",
        name="Apple",
        last=190.0,
        change=1.5,
        change_pct=0.8,
        currency="USD",
        market_cap=3e12,
        summary="Apple designs phones.",
    )
    sec.bid = 189.9
    sec.ask = 190.1
    sec.bid_size = 2
    sec.ask_size = 4
    collapsed = pill_text(sec, previous_last=189.5, live=True, expanded=False)
    assert "LIVE" in collapsed
    assert "tick ▲" in collapsed
    assert "AAPL" in collapsed
    assert "```ansi" in collapsed
    assert "\u001b[1;32m" in collapsed  # green for up day
    assert "Bid" in collapsed and "Ask" in collapsed
    assert "Apple designs" not in collapsed
    assert "Mkt cap" not in collapsed
    book = _book_line(sec)
    assert book and "Spr" in book and "Mid" in book

    down = Security(
        symbol="XYZ",
        yahoo="XYZ",
        quote_type="EQUITY",
        name="Down Co",
        last=7.86,
        change=-0.17,
        change_pct=-2.12,
        currency="USD",
    )
    down_text = pill_text(down, live=True, expanded=False)
    assert "\u001b[1;31m" in down_text  # red for down day
    assert "7.8600" in down_text
    assert "-0.17" in down_text

    expanded = pill_text(sec, previous_last=189.5, live=True, expanded=True)
    assert "**Apple**" in expanded
    assert "Mkt cap" in expanded
    assert "Apple designs" in expanded
