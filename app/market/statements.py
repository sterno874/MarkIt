from __future__ import annotations

from typing import Any

import pandas as pd
import yfinance as yf

from app import format as fmt
from app.security import Security, resolve

INCOME_ROWS = [
    ("Total Revenue", "Revenue"),
    ("Gross Profit", "Gross profit"),
    ("Operating Income", "Op. income"),
    ("Net Income", "Net income"),
    ("Diluted EPS", "Diluted EPS"),
    ("EBITDA", "EBITDA"),
]
BALANCE_ROWS = [
    ("Total Assets", "Assets"),
    ("Total Liabilities Net Minority Interest", "Liabilities"),
    ("Stockholders Equity", "Equity"),
    ("Cash And Cash Equivalents", "Cash"),
    ("Total Debt", "Debt"),
]
CASHFLOW_ROWS = [
    ("Operating Cash Flow", "Operating CF"),
    ("Capital Expenditure", "Capex"),
    ("Free Cash Flow", "Free CF"),
    ("Cash Dividends Paid", "Dividends"),
    ("Repurchase Of Capital Stock", "Buybacks"),
]


def financials(symbol: str, statement: str = "income", quarterly: bool = True) -> dict[str, Any]:
    sec = resolve(symbol)
    if not sec.is_equity_like:
        raise ValueError(f"{sec.asset_label} securities do not have standard financial statements on Yahoo.")
    t = yf.Ticker(sec.yahoo)
    key = {
        "income": "quarterly_income_stmt" if quarterly else "income_stmt",
        "balance": "quarterly_balance_sheet" if quarterly else "balance_sheet",
        "cashflow": "quarterly_cashflow" if quarterly else "cashflow",
    }[statement]
    df: pd.DataFrame = getattr(t, key)
    if df is None or df.empty:
        raise ValueError(f"No {statement} data for {sec.yahoo}")
    rows = {"income": INCOME_ROWS, "balance": BALANCE_ROWS, "cashflow": CASHFLOW_ROWS}[statement]
    periods = list(df.columns)[:4]
    lines: list[str] = []
    header = " | ".join(p.strftime("%Y-%m-%d") if hasattr(p, "strftime") else str(p)[:10] for p in periods)
    lines.append(f"**{sec.yahoo} · {statement}** (`{'Q' if quarterly else 'Y'}`)")
    lines.append(f"`{header}`")
    for raw, label in rows:
        if raw not in df.index:
            continue
        vals = []
        for p in periods:
            val = df.loc[raw, p]
            if raw == "Diluted EPS":
                vals.append(fmt.number(val, 2))
            else:
                vals.append(fmt.compact(val))
        lines.append(f"**{label}**: " + " · ".join(vals))
    return {"security": sec, "text": "\n".join(lines), "dataframe": df}


def holders(symbol: str) -> dict[str, Any]:
    sec = resolve(symbol)
    t = yf.Ticker(sec.yahoo)
    major = t.major_holders
    institutional = t.institutional_holders
    insider = t.insider_transactions
    purchases = t.insider_purchases
    lines = [f"**{sec.yahoo} holders**"]
    if major is not None and not major.empty:
        for idx, row in major.iterrows():
            label = str(idx)
            val = row.iloc[0]
            if isinstance(val, (int, float)) and "percent" in label.lower():
                lines.append(f"• {label}: {fmt.pct_frac(val)}")
            elif isinstance(val, (int, float)):
                lines.append(f"• {label}: {fmt.compact(val)}")
            else:
                lines.append(f"• {label}: {val}")
    if institutional is not None and not institutional.empty:
        lines.append("\n**Top institutions**")
        for _, row in institutional.head(5).iterrows():
            lines.append(
                f"• {row.get('Holder')}: {fmt.pct_frac(row.get('pctHeld'))} · "
                f"{fmt.compact(row.get('Shares'))} sh"
            )
    if purchases is not None and not purchases.empty:
        lines.append("\n**Insider summary (6m)**")
        for _, row in purchases.head(4).iterrows():
            lines.append(f"• {row.iloc[0]}: {fmt.compact(row.get('Shares'))}")
    if insider is not None and not insider.empty:
        lines.append("\n**Recent Form 4 activity**")
        for _, row in insider.head(5).iterrows():
            lines.append(
                f"• {fmt.as_date(row.get('Start Date'))} {row.get('Insider')} "
                f"{row.get('Transaction') or ''} {fmt.compact(row.get('Shares'))} — {row.get('Text') or ''}"
            )
    return {"security": sec, "text": "\n".join(lines)}


def analysts(symbol: str) -> dict[str, Any]:
    sec = resolve(symbol)
    t = yf.Ticker(sec.yahoo)
    targets = t.analyst_price_targets or {}
    summary = t.recommendations_summary
    lines = [f"**{sec.yahoo} analyst coverage**"]
    if targets:
        lines.append(
            f"Target mean {fmt.money(targets.get('mean'), sec.currency)} · "
            f"median {fmt.money(targets.get('median'), sec.currency)} · "
            f"high {fmt.money(targets.get('high'), sec.currency)} · "
            f"low {fmt.money(targets.get('low'), sec.currency)}"
        )
        if targets.get("current") is not None:
            lines.append(f"Current {fmt.money(targets.get('current'), sec.currency)}")
    if summary is not None and not summary.empty:
        row = summary.iloc[0]
        lines.append(
            "Latest month: "
            f"strong buy {int(row.get('strongBuy', 0))} · buy {int(row.get('buy', 0))} · "
            f"hold {int(row.get('hold', 0))} · sell {int(row.get('sell', 0))} · "
            f"strong sell {int(row.get('strongSell', 0))}"
        )
    return {"security": sec, "text": "\n".join(lines), "targets": targets}


def earnings(symbol: str) -> dict[str, Any]:
    sec = resolve(symbol)
    t = yf.Ticker(sec.yahoo)
    cal = t.calendar or {}
    dates = t.earnings_dates
    lines = [f"**{sec.yahoo} earnings**"]
    if cal:
        if cal.get("Earnings Date"):
            eds = cal["Earnings Date"]
            if isinstance(eds, list):
                lines.append("Next: " + ", ".join(str(x) for x in eds))
            else:
                lines.append(f"Next: {eds}")
        if cal.get("Earnings Average") is not None:
            lines.append(
                f"EPS est avg {fmt.number(cal.get('Earnings Average'))} "
                f"(low {fmt.number(cal.get('Earnings Low'))} / high {fmt.number(cal.get('Earnings High'))})"
            )
        if cal.get("Revenue Average") is not None:
            lines.append(f"Revenue est {fmt.compact(cal.get('Revenue Average'))}")
        if cal.get("Ex-Dividend Date"):
            lines.append(f"Ex-div {cal.get('Ex-Dividend Date')}")
        if cal.get("Dividend Date"):
            lines.append(f"Div pay {cal.get('Dividend Date')}")
    if dates is not None and not dates.empty:
        lines.append("\n**Recent / upcoming**")
        for idx, row in dates.head(6).iterrows():
            when = idx.strftime("%Y-%m-%d %H:%M %Z") if hasattr(idx, "strftime") else str(idx)
            est = row.get("EPS Estimate")
            rep = row.get("Reported EPS")
            sur = row.get("Surprise(%)")
            lines.append(
                f"• {when}: est {fmt.number(est)} · reported {fmt.number(rep)} · surprise {fmt.pct(sur, already_percent=True)}"
            )
    return {"security": sec, "text": "\n".join(lines), "calendar": cal}


def options_chain(symbol: str, expiry: str | None = None) -> dict[str, Any]:
    sec = resolve(symbol)
    underlying = sec.underlying or sec.yahoo
    if sec.is_option:
        underlying = sec.underlying or underlying
    t = yf.Ticker(underlying)
    expiries = list(t.options or [])
    if not expiries:
        raise ValueError(f"No options listed for {underlying}")
    chosen = expiry or expiries[0]
    if chosen not in expiries:
        # allow YYYY-MM-DD prefix match
        matches = [e for e in expiries if e.startswith(chosen)]
        if not matches:
            raise ValueError(f"Expiry {chosen} not in {expiries[:8]}…")
        chosen = matches[0]
    chain = t.option_chain(chosen)
    def top(df: pd.DataFrame, n: int = 5) -> list[str]:
        if df is None or df.empty:
            return ["—"]
        out = []
        view = df.sort_values("volume", ascending=False).head(n)
        for _, row in view.iterrows():
            out.append(
                f"`{row['contractSymbol']}` K{fmt.number(row['strike'], 1)} "
                f"last {fmt.number(row['lastPrice'])} vol {fmt.compact(row['volume'])} "
                f"OI {fmt.compact(row['openInterest'])} IV {fmt.pct_frac(row['impliedVolatility'])}"
            )
        return out
    text = [
        f"**{underlying} options · {chosen}**",
        "",
        "**Top calls by volume**",
        *top(chain.calls),
        "",
        "**Top puts by volume**",
        *top(chain.puts),
        "",
        f"Expiries: {', '.join(expiries[:10])}{'…' if len(expiries) > 10 else ''}",
    ]
    return {"security": resolve(underlying), "expiry": chosen, "expiries": expiries, "text": "\n".join(text)}
