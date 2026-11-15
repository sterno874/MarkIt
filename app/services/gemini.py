from __future__ import annotations

import json
from typing import Any

from app.config import GEMINI_API_KEY, GEMINI_MODEL
from app.market import congress, filings, news, statements
from app.market.quotes import get_security
from app.market.sentiment import crypto_fear_greed, stock_fear_greed
from app.security import normalize_symbol


SYSTEM = """You are Market Desk, a research assistant inside a private investing Discord.
Be concise, direct, and cite tickers clearly. You can call tools for live data.
Never claim to place real trades. Quotes are Yahoo-sourced and may be delayed.
Support equities, ETFs, FX, crypto, futures, options, and bond/rate tickers.
If a symbol is ambiguous, ask one clarifying question.
"""


def available() -> bool:
    return bool(GEMINI_API_KEY)


def _tool_quote(symbol: str) -> dict[str, Any]:
    sec = get_security(symbol)
    return {
        "symbol": sec.yahoo,
        "type": sec.quote_type,
        "name": sec.name,
        "last": sec.last,
        "change": sec.change,
        "change_pct": sec.change_pct,
        "bid": sec.bid,
        "ask": sec.ask,
        "bid_size": sec.bid_size,
        "ask_size": sec.ask_size,
        "spread": sec.spread,
        "mid": sec.mid,
        "open": sec.open,
        "day_high": sec.day_high,
        "day_low": sec.day_low,
        "volume_shares": sec.volume,
        "avg_volume_10d_shares": sec.avg_volume_10d,
        "pre_market": sec.pre_market,
        "post_market": sec.post_market,
        "currency": sec.currency,
        "market_cap": sec.market_cap,
        "pe": sec.trailing_pe,
        "sector": sec.sector,
        "summary": (sec.summary or "")[:500],
    }


def _tool_news(symbol: str) -> dict[str, Any]:
    return {"text": news.company_news(symbol, limit=5)["text"]}


def _tool_filings(symbol: str) -> dict[str, Any]:
    return {"text": filings.recent_filings(symbol, limit=5)["text"]}


def _tool_earnings(symbol: str) -> dict[str, Any]:
    return {"text": statements.earnings(symbol)["text"]}


def _tool_holders(symbol: str) -> dict[str, Any]:
    return {"text": statements.holders(symbol)["text"]}


def _tool_analysts(symbol: str) -> dict[str, Any]:
    return {"text": statements.analysts(symbol)["text"]}


def _tool_congress(symbol: str | None = None) -> dict[str, Any]:
    return {"text": congress.recent_trades(symbol, limit=8)["text"]}


def _tool_fgi() -> dict[str, Any]:
    return {
        "stocks": stock_fear_greed(),
        "crypto": crypto_fear_greed(),
    }


def _tool_normalize(symbol: str) -> dict[str, Any]:
    return {"yahoo": normalize_symbol(symbol)}


TOOLS = [
    _tool_quote,
    _tool_news,
    _tool_filings,
    _tool_earnings,
    _tool_holders,
    _tool_analysts,
    _tool_congress,
    _tool_fgi,
    _tool_normalize,
]


def _generate(contents: str, *, system: str, tools: list | None, temperature: float) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY)
    kwargs: dict[str, Any] = {
        "system_instruction": system,
        "temperature": temperature,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(
            maximum_remote_calls=8
        )
    config = types.GenerateContentConfig(**kwargs)
    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=config,
        )
    except Exception as exc:
        if "not found" in str(exc).lower() or "NOT_FOUND" in str(exc):
            response = client.models.generate_content(
                model="gemini-3-flash-preview",
                contents=contents,
                config=config,
            )
        else:
            raise
    text = response.text
    return text.strip() if text else ""


def ask(prompt: str, *, context: str | None = None) -> str:
    """Research Q&A with live Yahoo/SEC tools."""
    if not GEMINI_API_KEY:
        return "Gemini is not configured. Add `GEMINI_API_KEY` to `.env` and restart the bot."

    contents = prompt if not context else f"Context:\n{context}\n\nUser:\n{prompt}"
    text = _generate(contents, system=SYSTEM, tools=TOOLS, temperature=0.3)
    return text or "No response from Gemini."


def ask_plain(prompt: str) -> str:
    """Planner / JSON-only calls — no research tools, so the model returns a plan."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not configured")
    system = (
        "You are a routing agent. Reply with the requested format only "
        "(usually compact JSON). No markdown fences unless asked. No prose."
    )
    return _generate(prompt, system=system, tools=None, temperature=0.1)


def summarize_bug(description: str, command: str | None, context: dict[str, Any]) -> str:
    if not GEMINI_API_KEY:
        return description
    prompt = (
        "Summarize this Discord bot bug into a short title (max 80 chars) "
        "and 3 concrete reproduction / fix bullets.\n"
        f"Command: {command}\nDescription: {description}\nContext: {json.dumps(context)[:1500]}"
    )
    try:
        return ask(prompt)
    except Exception:
        return description
