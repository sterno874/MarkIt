from __future__ import annotations

from app.security import _dividend_yield_fraction


def test_prefers_trailing_fraction() -> None:
    info = {
        "dividendYield": 0.3,  # Yahoo percent points (would wrongly show 30%)
        "trailingAnnualDividendYield": 0.002986925,
    }
    y = _dividend_yield_fraction(info)
    assert y is not None
    assert abs(y - 0.002986925) < 1e-9


def test_dividend_yield_percent_points() -> None:
    # No trailing field — scale Yahoo's percent-point dividendYield.
    y = _dividend_yield_fraction({"dividendYield": 0.3})
    assert y is not None
    assert abs(y - 0.003) < 1e-9


def test_compute_from_rate_and_price() -> None:
    y = _dividend_yield_fraction(
        {"dividendYield": 0.3, "dividendRate": 1.08},
        last=356.27,
    )
    assert y is not None
    assert abs(y - (1.08 / 356.27)) < 1e-6


def test_att_style_percent_points() -> None:
    y = _dividend_yield_fraction({"dividendYield": 5.0})
    assert y is not None
    assert abs(y - 0.05) < 1e-9
