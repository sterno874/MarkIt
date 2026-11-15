from __future__ import annotations

import asyncio
import logging
from typing import Iterable

import discord
from discord import app_commands

from app.db import db
from app.help_text import HELP_TOPICS
from app.security import ALIASES

log = logging.getLogger("market-desk.autocomplete")

# Always-on suggestions when the user hasn't typed much yet.
POPULAR: list[tuple[str, str]] = [
    ("AAPL", "Apple · Equity"),
    ("MSFT", "Microsoft · Equity"),
    ("NVDA", "NVIDIA · Equity"),
    ("AMZN", "Amazon · Equity"),
    ("GOOGL", "Alphabet · Equity"),
    ("META", "Meta · Equity"),
    ("TSLA", "Tesla · Equity"),
    ("SPY", "S&P 500 ETF"),
    ("QQQ", "Nasdaq 100 ETF"),
    ("IWM", "Russell 2000 ETF"),
    ("TLT", "20+ Year Treasury ETF"),
    ("HYG", "High Yield Corp Bond ETF"),
    ("SPX", "S&P 500 · Index → ^GSPC"),
    ("VIX", "CBOE Volatility · Index"),
    ("BTC", "Bitcoin → BTC-USD"),
    ("ETH", "Ethereum → ETH-USD"),
    ("EURUSD", "Euro / USD · FX"),
    ("USDJPY", "USD / Yen · FX"),
    ("CL=F", "WTI Crude · Future"),
    ("GC=F", "Gold · Future"),
    ("ES", "E-mini S&P · Future → ES=F"),
    ("TNX", "10-Year Yield → ^TNX"),
]

BOND_EXAMPLES: list[tuple[str, str]] = [
    ("IHRT 8 3/8 May 2027", "iHeart 8.375% May 2027 · Corp"),
    ("45174HBD8", "CUSIP lookup"),
]

PERIODS = ["1d", "5d", "1m", "3m", "6m", "1y", "5y", "ytd", "max"]
STATEMENTS = ["income", "balance", "cashflow"]
BUG_COMMANDS = [
    "markit",
    "quote",
    "chart",
    "bond",
    "financials",
    "news",
    "holders",
    "analysts",
    "earnings",
    "options",
    "compare",
    "filings",
    "congress",
    "alert",
    "watch",
    "idea",
    "brief",
    "ask",
    "heatmap",
    "fgi",
    "paper",
    "leaderboard",
    "pnl",
    "autocomplete",
]


def _choice(value: str, name: str | None = None) -> app_commands.Choice[str]:
    label = name or value
    # Discord: name ≤ 100 chars, value ≤ 100 chars
    return app_commands.Choice(name=label[:100], value=value[:100])


def _dedupe(choices: Iterable[app_commands.Choice[str]]) -> list[app_commands.Choice[str]]:
    seen: set[str] = set()
    out: list[app_commands.Choice[str]] = []
    for choice in choices:
        key = choice.value.upper()
        if key in seen:
            continue
        seen.add(key)
        out.append(choice)
        if len(out) >= 25:
            break
    return out


def _local_symbol_hits(current: str, interaction: discord.Interaction) -> list[app_commands.Choice[str]]:
    cur = (current or "").strip().upper()
    hits: list[app_commands.Choice[str]] = []

    if interaction.guild_id and interaction.channel_id:
        last = db.get_last_ticker(interaction.guild_id, interaction.channel_id)
        if last and (not cur or cur in last.upper()):
            hits.append(_choice(last, f"{last} · last in channel"))

    if interaction.guild_id:
        for row in db.watch_list(guild_id=interaction.guild_id, server=True)[:15]:
            sym = row["symbol"]
            if not cur or cur in sym.upper():
                hits.append(_choice(sym, f"{sym} · server watchlist"))
        if interaction.user:
            for row in db.watch_list(
                guild_id=interaction.guild_id, user_id=interaction.user.id
            )[:15]:
                sym = row["symbol"]
                if not cur or cur in sym.upper():
                    hits.append(_choice(sym, f"{sym} · your watchlist"))
        for row in db.idea_list(interaction.guild_id, status="open")[:10]:
            sym = row["symbol"]
            if not cur or cur in sym.upper():
                hits.append(_choice(sym, f"{sym} · open idea #{row['id']}"))

    for alias, yahoo in ALIASES.items():
        if not cur or cur in alias or cur in yahoo.upper():
            label = f"{alias} → {yahoo}" if alias != yahoo else alias
            hits.append(_choice(alias, label))

    for sym, label in POPULAR:
        if not cur or cur in sym.upper() or cur in label.upper():
            hits.append(_choice(sym, f"{sym} · {label}"))

    # If they're typing a bare ticker, offer it as-is so autocomplete doesn't block free input.
    if cur and cur.replace(".", "").replace("-", "").replace("=", "").replace("^", "").isalnum():
        hits.insert(0, _choice(cur, f"{cur} · use as typed"))

    return _dedupe(hits)


def _yahoo_search(query: str, limit: int = 12) -> list[app_commands.Choice[str]]:
    if not query or len(query) < 1:
        return []
    try:
        import yfinance as yf

        result = yf.Search(query, max_results=limit, enable_fuzzy_query=True)
        quotes = result.quotes or []
    except Exception as exc:
        log.debug("yahoo search failed: %s", exc)
        return []

    hits: list[app_commands.Choice[str]] = []
    for q in quotes:
        symbol = q.get("symbol")
        if not symbol:
            continue
        name = q.get("shortname") or q.get("longname") or ""
        kind = q.get("typeDisp") or q.get("quoteType") or ""
        exch = q.get("exchDisp") or q.get("exchange") or ""
        label = " · ".join(p for p in (name, kind, exch) if p)
        hits.append(_choice(symbol, f"{symbol} — {label}" if label else symbol))
    return hits


def _openfigi_bond_search(query: str, limit: int = 10) -> list[app_commands.Choice[str]]:
    if not query or len(query.strip()) < 2:
        return []
    try:
        import json
        from urllib.request import Request, urlopen

        from app.market.bonds import looks_like_bond_query

        payload = json.dumps({"query": query.strip(), "marketSecDes": "Corp"}).encode()
        req = Request(
            "https://api.openfigi.com/v3/search",
            data=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=1.8) as resp:
            data = json.loads(resp.read().decode()).get("data") or []
    except Exception as exc:
        log.debug("openfigi search failed: %s", exc)
        return []

    hits: list[app_commands.Choice[str]] = []
    for row in data[: limit * 3]:
        # Prefer description/ticker forms our bond parser can resolve.
        candidates = [
            row.get("securityDescription"),
            row.get("ticker"),
        ]
        value = None
        for cand in candidates:
            if cand and looks_like_bond_query(str(cand)):
                value = str(cand)
                break
        if not value:
            continue
        name = row.get("name") or ""
        label = " · ".join(p for p in (name, value) if p)
        hits.append(_choice(value, f"{value} — {label}" if name else value))
        if len(hits) >= limit:
            break
    return hits


async def suggest_symbols(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    local = _local_symbol_hits(current, interaction)
    cur = (current or "").strip()
    remote: list[app_commands.Choice[str]] = []
    if len(cur) >= 1:
        try:
            remote = await asyncio.wait_for(
                asyncio.to_thread(_yahoo_search, cur, 12),
                timeout=2.2,
            )
        except Exception:
            remote = []
    return _dedupe([*remote, *local])


async def suggest_bonds(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    cur = (current or "").strip()
    hits: list[app_commands.Choice[str]] = []
    if cur:
        hits.append(_choice(cur, f"{cur} · use as typed"))
    for value, label in BOND_EXAMPLES:
        if not cur or cur.upper() in value.upper() or cur.upper() in label.upper():
            hits.append(_choice(value, label))
    if len(cur) >= 2:
        try:
            remote = await asyncio.wait_for(
                asyncio.to_thread(_openfigi_bond_search, cur, 10),
                timeout=2.0,
            )
            hits.extend(remote)
        except Exception:
            pass
    # Do NOT mix Yahoo equity hits into /bond — selecting "IHRT" alone fails TRACE parse.
    return _dedupe(hits)


async def suggest_smart_query(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Equity + bond lookup for /quote-smart."""
    cur = (current or "").strip()
    looks_bond = bool(cur) and (
        " " in cur
        or any(ch.isdigit() for ch in cur)
        or len(cur) == 9  # CUSIP-ish
    )
    if looks_bond:
        bond_hits = await suggest_bonds(interaction, current)
        if len(bond_hits) > 1 or (bond_hits and bond_hits[0].value != cur):
            return bond_hits
    return await suggest_symbols(interaction, current)


async def suggest_symbol_list(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Autocomplete the last token in a space/comma-separated ticker list."""
    raw = current or ""
    if "," in raw:
        head, _, last = raw.rpartition(",")
        sep = ","
        prefix = head + sep
        fragment = last.lstrip()
        pad = " " if last.startswith(" ") else ""
    else:
        parts = raw.rsplit(None, 1)
        if len(parts) == 2:
            prefix, fragment = parts[0] + " ", parts[1]
            pad = ""
        else:
            return await suggest_symbols(interaction, raw)

    choices = await suggest_symbols(interaction, fragment)
    out: list[app_commands.Choice[str]] = []
    for choice in choices:
        value = f"{prefix}{pad}{choice.value}"
        out.append(_choice(value, f"{choice.name}"))
    return _dedupe(out)


async def suggest_periods(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    cur = (current or "").lower()
    return [
        _choice(p, p)
        for p in PERIODS
        if not cur or cur in p
    ][:25]


async def suggest_statements(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    cur = (current or "").lower()
    return [
        _choice(s, s)
        for s in STATEMENTS
        if not cur or cur in s
    ][:25]


async def suggest_help_topics(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    cur = (current or "").lower()
    return [
        _choice(name, name)
        for name in HELP_TOPICS
        if not cur or cur in name
    ][:25]


async def suggest_bug_commands(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    cur = (current or "").lower()
    return [
        _choice(name, name)
        for name in BUG_COMMANDS
        if not cur or cur in name
    ][:25]


def attach_symbol_autocomplete(command: app_commands.Command, param: str = "symbol") -> None:
    """Wire shared symbol autocomplete onto a slash command parameter."""

    async def _ac(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return await suggest_symbols(interaction, current)

    command.autocomplete(param)(_ac)


def attach_many(command: app_commands.Command, mapping: dict[str, object]) -> None:
    for param, fn in mapping.items():
        command.autocomplete(param)(fn)  # type: ignore[arg-type]
