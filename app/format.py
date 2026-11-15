from __future__ import annotations

from datetime import date, datetime
from typing import Any


def money(value: Any, currency: str | None = "USD", digits: int = 2) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    sign = "-" if number < 0 else ""
    number = abs(number)
    prefix = "$" if (currency or "USD").upper() in {"USD", "USDT"} else ""
    suffix = "" if prefix else f" {(currency or '').upper()}".rstrip()
    if number >= 1_000_000_000_000:
        body = f"{number / 1_000_000_000_000:.2f}T"
    elif number >= 1_000_000_000:
        body = f"{number / 1_000_000_000:.2f}B"
    elif number >= 1_000_000:
        body = f"{number / 1_000_000:.2f}M"
    elif number >= 10_000:
        body = f"{number:,.0f}"
    else:
        body = f"{number:,.{digits}f}"
    return f"{sign}{prefix}{body}{suffix}"


def compact(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    sign = "-" if number < 0 else ""
    number = abs(number)
    if number >= 1_000_000_000_000:
        return f"{sign}{number / 1_000_000_000_000:.{digits}f}T"
    if number >= 1_000_000_000:
        return f"{sign}{number / 1_000_000_000:.{digits}f}B"
    if number >= 1_000_000:
        return f"{sign}{number / 1_000_000:.{digits}f}M"
    if number >= 1_000:
        return f"{sign}{number / 1_000:.{digits}f}K"
    return f"{sign}{number:.{digits}f}"


def pct(value: Any, already_percent: bool = False, digits: int = 2) -> str:
    """Format a percentage.

    Args:
        value: Either a fraction (0.05 = 5%) when ``already_percent=False``,
            or percent points (5.0 = 5%) when ``already_percent=True``.
        already_percent: If False, always multiply by 100. Do not guess —
            Yahoo mixes both conventions and a 1.5 heuristic hid 160% IVs as 1.60%.
    """
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if number != number:  # NaN
        return "—"
    if not already_percent:
        number *= 100
    sign = "+" if number > 0 else ""
    return f"{sign}{number:.{digits}f}%"


def pct_points(value: Any, digits: int = 2) -> str:
    """Alias: value is already in percent points (Yahoo day change, surprise %, …)."""
    return pct(value, already_percent=True, digits=digits)


def pct_frac(value: Any, digits: int = 2) -> str:
    """Alias: value is a fraction (short % of float, IV, trailing yield, …)."""
    return pct(value, already_percent=False, digits=digits)


def signed(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    sign = "+" if number > 0 else ""
    return f"{sign}{number:.{digits}f}"


def number(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def truncate(text: str | None, limit: int = 280) -> str:
    if not text:
        return "—"
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def as_date(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (int, float)) and value > 1_000_000_000:
        return datetime.utcfromtimestamp(value).date().isoformat()
    return str(value)[:10]


def accent(change: float | None) -> int:
    if change is None:
        return 0x5865F2
    if change > 0:
        return 0x2ECC71
    if change < 0:
        return 0xE74C3C
    return 0x95A5A6


ASSET_LABELS = {
    "EQUITY": "Equity",
    "ETF": "ETF",
    "MUTUALFUND": "Mutual Fund",
    "INDEX": "Index",
    "CURRENCY": "FX",
    "CRYPTOCURRENCY": "Crypto",
    "FUTURE": "Future",
    "OPTION": "Option",
    "BOND": "Bond",
    "ECNQUOTE": "ECN",
}
