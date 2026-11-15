from __future__ import annotations

from app import format as fmt


def test_pct_frac_always_scales() -> None:
    assert fmt.pct_frac(0.003) == "+0.30%"
    assert fmt.pct_frac(0.05) == "+5.00%"
    # High IV used to display as 1.60% because of the old <=1.5 heuristic.
    assert fmt.pct_frac(1.6) == "+160.00%"
    assert fmt.pct_frac(2.5) == "+250.00%"


def test_pct_points_no_scale() -> None:
    assert fmt.pct_points(0.39) == "+0.39%"
    assert fmt.pct_points(5.8) == "+5.80%"
    assert fmt.pct_points(-1.2) == "-1.20%"


def test_pct_explicit_flags() -> None:
    assert fmt.pct(0.01, already_percent=False) == "+1.00%"
    assert fmt.pct(0.01, already_percent=True) == "+0.01%"
