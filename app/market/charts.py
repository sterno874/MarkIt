from __future__ import annotations

import io
from typing import Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mticker  # noqa: E402
import pandas as pd  # noqa: E402

from app.market.quotes import download_closes, history

PERIOD_MAP = {
    "1d": ("1d", "5m"),
    "5d": ("5d", "15m"),
    "1m": ("1mo", "1d"),
    "3m": ("3mo", "1d"),
    "6m": ("6mo", "1d"),
    "1y": ("1y", "1d"),
    "5y": ("5y", "1wk"),
    "ytd": ("ytd", "1d"),
    "max": ("max", "1mo"),
}


def _fmt_shares(value: float, _pos: int | None = None) -> str:
    """Human share counts for axis ticks (not dollar volume)."""
    v = abs(float(value))
    if v >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    if v >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"{value / 1_000:.0f}K"
    return f"{value:.0f}"


def _fmt_usd(value: float, _pos: int | None = None) -> str:
    return f"${value:,.2f}" if abs(value) < 1000 else f"${value:,.0f}"


def _fmt_share_count(n: float) -> str:
    return _fmt_shares(n).rstrip()


def render_chart(
    symbol: str,
    period: str = "6m",
    *,
    mas: Sequence[int] = (20, 50),
    title: str | None = None,
) -> io.BytesIO:
    p, interval = PERIOD_MAP.get(period.lower(), ("6mo", "1d"))
    df = history(symbol, period=p, interval=interval)
    if df is None or df.empty:
        raise ValueError(f"No history for {symbol}")

    fig, (ax, axv) = plt.subplots(
        2,
        1,
        figsize=(10, 5.2),
        sharex=True,
        gridspec_kw={"height_ratios": [3.2, 1]},
        constrained_layout=True,
    )
    color = "#2ecc71" if float(df["Close"].iloc[-1]) >= float(df["Close"].iloc[0]) else "#e74c3c"
    ax.plot(df.index, df["Close"], color=color, linewidth=1.6, label="Close ($)")
    for window in mas:
        if len(df) >= window:
            ax.plot(df.index, df["Close"].rolling(window).mean(), linewidth=1.0, alpha=0.85, label=f"MA{window}")
    ax.set_title(title or f"{symbol} · price ($) · {period.upper()}")
    ax.set_ylabel("Price (USD)")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(_fmt_usd))
    ax.grid(True, alpha=0.25)
    ax.legend(loc="upper left", fontsize=8, frameon=False)

    vol = df.get("Volume", pd.Series(0, index=df.index)).fillna(0)
    axv.bar(df.index, vol, width=0.8, color="#7f8c8d", alpha=0.55)
    axv.set_ylabel("Share volume")
    axv.yaxis.set_major_formatter(mticker.FuncFormatter(_fmt_shares))
    axv.grid(True, alpha=0.2)
    for spine in (*ax.spines.values(), *axv.spines.values()):
        spine.set_alpha(0.3)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=140)
    plt.close(fig)
    buf.seek(0)
    return buf


def render_volume_chart(
    symbol: str,
    period: str = "5d",
    *,
    title: str | None = None,
) -> io.BytesIO:
    """Volume-first chart — share volume (not $ volume) with USD price context."""
    p, interval = PERIOD_MAP.get(period.lower(), ("5d", "15m"))
    # Prefer daily bars for multi-day volume requests.
    if period.lower() in {"5d", "1m", "3m", "6m", "1y", "ytd"}:
        interval = "1d"
        if period.lower() == "5d":
            p = "10d"  # include a bit of context around "the past week"
    df = history(symbol, period=p, interval=interval)
    if df is None or df.empty or "Volume" not in df.columns:
        raise ValueError(f"No volume history for {symbol}")

    vol = df["Volume"].fillna(0)
    last_px = float(df["Close"].iloc[-1])
    last_vol = float(vol.iloc[-1])
    fig, (axp, axv) = plt.subplots(
        2,
        1,
        figsize=(10, 5.4),
        sharex=True,
        gridspec_kw={"height_ratios": [1.4, 2.4]},
        constrained_layout=True,
    )
    color = "#2ecc71" if last_px >= float(df["Close"].iloc[0]) else "#e74c3c"
    axp.plot(df.index, df["Close"], color=color, linewidth=1.5, label="Close (USD)")
    axp.set_ylabel("Price (USD)")
    axp.yaxis.set_major_formatter(mticker.FuncFormatter(_fmt_usd))
    axp.grid(True, alpha=0.25)
    axp.legend(loc="upper left", fontsize=8, frameon=False)
    axp.set_title(
        title
        or (
            f"{symbol} · share volume · {period.upper()}"
            f"  ·  last ${last_px:,.2f}  ·  {_fmt_share_count(last_vol)} shares"
        )
    )

    up = df["Close"] >= df["Close"].shift(1)
    bar_colors = ["#2ecc71" if bool(u) else "#e74c3c" for u in up.fillna(True)]
    axv.bar(df.index, vol, width=0.8, color=bar_colors, alpha=0.85, label="Shares traded")
    axv.set_ylabel("Shares traded")
    axv.yaxis.set_major_formatter(mticker.FuncFormatter(_fmt_shares))
    axv.grid(True, alpha=0.2)
    if len(vol):
        avg = float(vol.mean())
        axv.axhline(
            avg,
            color="#95a5a6",
            linewidth=0.9,
            linestyle="--",
            label=f"avg {_fmt_share_count(avg)} shares/day",
        )
        axv.legend(loc="upper left", fontsize=8, frameon=False)
    axv.set_xlabel("Session date  ·  green = up day, red = down day  ·  volume = shares (not $)")
    for spine in (*axp.spines.values(), *axv.spines.values()):
        spine.set_alpha(0.3)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=140)
    plt.close(fig)
    buf.seek(0)
    return buf


def render_compare(symbols: list[str], period: str = "6m") -> io.BytesIO:
    p, _ = PERIOD_MAP.get(period.lower(), ("6mo", "1d"))
    raw = download_closes(symbols, period=p)
    if raw is None or raw.empty:
        raise ValueError("No history for comparison")

    if isinstance(raw.columns, pd.MultiIndex):
        closes = raw["Close"]
    else:
        closes = raw[["Close"]].rename(columns={"Close": symbols[0]})

    norm = closes.dropna(how="all").ffill().dropna()
    if norm.empty:
        raise ValueError("Not enough overlapping history")
    norm = norm / norm.iloc[0] * 100

    fig, ax = plt.subplots(figsize=(10, 5), constrained_layout=True)
    for col in norm.columns:
        ax.plot(norm.index, norm[col], linewidth=1.6, label=str(col))
    ax.axhline(100, color="#95a5a6", linewidth=0.8, linestyle="--")
    ax.set_title(f"Relative performance · {period.upper()} (rebased 100)")
    ax.set_ylabel("Index")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="upper left", fontsize=8, frameon=False)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=140)
    plt.close(fig)
    buf.seek(0)
    return buf


def render_heatmap(rows: list[tuple[str, float]], title: str = "Movers") -> io.BytesIO:
    if not rows:
        raise ValueError("Nothing to plot")
    labels = [r[0] for r in rows]
    values = [r[1] for r in rows]
    colors = ["#2ecc71" if v >= 0 else "#e74c3c" for v in values]
    fig, ax = plt.subplots(figsize=(9, max(3.2, 0.38 * len(rows) + 1)), constrained_layout=True)
    ax.barh(labels[::-1], values[::-1], color=colors[::-1])
    ax.axvline(0, color="#7f8c8d", linewidth=0.8)
    ax.set_title(title)
    ax.set_xlabel("% change")
    ax.grid(True, axis="x", alpha=0.25)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=140)
    plt.close(fig)
    buf.seek(0)
    return buf
