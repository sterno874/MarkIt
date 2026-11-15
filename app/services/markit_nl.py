"""MCP-style desk agent for `/markit`.

Plans which Discord desk tool to invoke (pill, chart, volume, filings, …),
then the cog posts that artifact. Gemini is the primary planner when
configured; a local pattern router is the fast offline fallback.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from app.security import ALIASES, TICKER_TOKEN, extract_option_contracts, normalize_symbol
from app.services import gemini

log = logging.getLogger("market-desk.markit_nl")

PERIODS = {"1d", "5d", "1m", "3m", "6m", "1y", "5y", "ytd", "max"}

# Desk tools the agent may call — each maps to a real Discord post type.
DESK_TOOLS = """
post_pill       — live quote pill / ticker card (last, day change, bid/ask/spread when available)
post_book       — same pill expanded on top-of-book (bid/ask/size/spread) — use for "what's the bid", "spread", "ask size"
post_chart      — price chart image (with volume subplot)
post_volume     — volume-focused chart for a period ("volume last week")
post_news       — company headlines
post_filings    — SEC filings
post_financials — income / balance / cashflow snapshot
post_holders    — institutional / insider holders
post_analysts   — analyst ratings / price targets
post_earnings   — earnings calendar + surprises
post_dividends  — yield / ex-date
post_options    — options chain snapshot
post_short      — short interest
post_congress   — congressional trades
post_bond       — TRACE corporate bond card
post_compare    — relative performance chart (2+ tickers)
post_fgi        — fear & greed
post_heatmap    — watchlist movers board
post_help       — how to use MarkIt
post_paper_buy / post_paper_sell / post_paper_close / post_paper_positions /
post_paper_pnl / post_paper_leaderboard / post_paper_server — paper desk
ask             — free-form research answer (text only; last resort)
"""

# Local action names used by the cog (kept stable).
ACTION_ALIASES = {
    "post_pill": "quote",
    "post_book": "book",
    "book": "book",
    "post_chart": "chart",
    "post_volume": "volume",
    "post_news": "news",
    "post_filings": "filings",
    "post_financials": "financials",
    "post_holders": "holders",
    "post_analysts": "analysts",
    "post_earnings": "earnings",
    "post_dividends": "dividends",
    "post_options": "options",
    "post_short": "short",
    "post_congress": "congress",
    "post_bond": "bond",
    "post_compare": "compare",
    "post_fgi": "fgi",
    "post_heatmap": "heatmap",
    "post_help": "help",
    "post_paper_buy": "paper_buy",
    "post_paper_sell": "paper_sell",
    "post_paper_close": "paper_close",
    "post_paper_positions": "paper_positions",
    "post_paper_pnl": "paper_pnl",
    "post_paper_leaderboard": "paper_leaderboard",
    "post_paper_server": "paper_server",
    # Accept bare names too
    "quote": "quote",
    "pill": "quote",
    "chart": "chart",
    "graph": "chart",
    "volume": "volume",
    "news": "news",
    "filings": "filings",
    "financials": "financials",
    "holders": "holders",
    "analysts": "analysts",
    "earnings": "earnings",
    "dividends": "dividends",
    "options": "options",
    "short": "short",
    "congress": "congress",
    "bond": "bond",
    "compare": "compare",
    "fgi": "fgi",
    "heatmap": "heatmap",
    "help": "help",
    "ask": "ask",
    "paper_buy": "paper_buy",
    "paper_sell": "paper_sell",
    "paper_close": "paper_close",
    "paper_positions": "paper_positions",
    "paper_pnl": "paper_pnl",
    "paper_leaderboard": "paper_leaderboard",
    "paper_server": "paper_server",
}

STOPWORDS = {
    "A", "AN", "THE", "ME", "MY", "ON", "FOR", "OF", "TO", "AND", "OR", "VS",
    "VERSUS", "WITH", "ABOUT", "SHOW", "GET", "GIVE", "PULL", "FIND", "LOOK",
    "WANT", "NEED", "PLEASE", "CAN", "YOU", "JUST", "WHAT", "WHATS", "HOW",
    "IS", "ARE", "WAS", "WERE", "IT", "ITS", "THIS", "THAT", "LAST", "PRICE",
    "QUOTE", "CHART", "GRAPH", "PLOT", "NEWS", "HEADLINES", "HEADLINE",
    "EARNINGS", "DIVIDEND", "DIVIDENDS", "OPTIONS", "OPTION", "FILINGS",
    "FILING", "HOLDERS", "ANALYSTS", "ANALYST", "SHORT", "INTEREST",
    "CONGRESS", "BOND", "BONDS", "COMPARE", "PERFORMANCE", "RELATIVE",
    "HEATMAP", "FEAR", "GREED", "FGI", "HELP", "FINANCIALS", "INCOME",
    "BALANCE", "CASHFLOW", "CASH", "FLOW", "STATEMENT", "MONTH", "MONTHS",
    "YEAR", "YEARS", "WEEK", "WEEKS", "DAY", "DAYS", "TODAY", "YTD", "MAX",
    "OVER", "PAST", "SINCE", "FROM", "IN", "AT", "UP", "DOWN", "SOME", "ANY",
    "INFO", "INFORMATION", "DATA", "DESK", "MARKIT", "TELL", "RETURN", "RUN",
    "DO", "I", "IM", "I'D", "LIKE", "SEE", "CHECK", "QUICK", "QUICKLY",
    "PAPER", "BOOK", "BUY", "SELL", "LONG", "SHORT", "LEADERBOARD", "PNL",
    "P&L", "ATTRIBUTION", "POSITIONS", "POSITION", "CLOSE", "CLOSED", "OPEN",
    "SERVER", "TOTAL", "TRADER", "TRADERS", "SHARES", "SHARE", "UNITS",
    "VOLUME", "VOL", "VOLUMES", "PILL", "CARD", "LIVE",
    "BID", "ASK", "SPREAD", "MID", "SIZE",
}

ACTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("help", re.compile(r"\b(help|commands|how (do|to) use)\b", re.I)),
    (
        "paper_leaderboard",
        re.compile(
            r"\b(leaderboard|standings|who('?s| is) (winning|ahead|up)|rankings?|top\s+traders?)\b",
            re.I,
        ),
    ),
    (
        "paper_server",
        re.compile(
            r"\b((server|desk|team|our|total)\s+(paper\s+)?(pnl|p&l|profit|performance)|"
            r"paper\s+server|server\s+book)\b",
            re.I,
        ),
    ),
    (
        "paper_pnl",
        re.compile(
            r"\b((my|mine|his|her|their)\s+(pnl|p&l|paper)|"
            r"(pnl|p&l|attribution)\b|"
            r"how('?s| is) .{0,40}(doing|performing|pnl|p&l))\b",
            re.I,
        ),
    ),
    (
        "paper_positions",
        re.compile(
            r"\b((paper\s+)?positions|open\s+(paper\s+)?(trades?|books?|positions?)|"
            r"what('?s| is) open|show\s+(my\s+)?(book|positions))\b",
            re.I,
        ),
    ),
    (
        "paper_close",
        re.compile(r"\b(close|flatten|exit)\s+(paper\s+)?(position\s*)?#?\d+\b", re.I),
    ),
    (
        "paper_sell",
        re.compile(r"\b((paper\s+)?(sell|short)|book\s+a\s+short|paper\s+short)\b", re.I),
    ),
    (
        "paper_buy",
        re.compile(
            r"\b((paper\s+)?(buy|long)|book\s+(a\s+)?(long\s+)?|paper\s+trade|"
            r"add\s+to\s+(my\s+)?(paper\s+)?book)\b",
            re.I,
        ),
    ),
    ("fgi", re.compile(r"\b(fear\s*(&|and)?\s*greed|fgi)\b", re.I)),
    ("heatmap", re.compile(r"\b(heatmap|heat\s*map|movers\s*board)\b", re.I)),
    ("compare", re.compile(r"\b(compare|vs\.?|versus|relative|rv)\b", re.I)),
    ("bond", re.compile(r"\b(bond|trace|cusip|corporate\s+bond)\b", re.I)),
    ("congress", re.compile(r"\b(congress|politician|senate|house\s+trade|stock\s+act)\b", re.I)),
    ("filings", re.compile(r"\b(filing|filings|10-?k|10-?q|8-?k|sec\b|edgar)\b", re.I)),
    (
        "options",
        re.compile(
            r"\b(options?\s+chain|option\s+chain|\bopt\b|calls?\s+and\s+puts?|"
            r"options?\s+on|options?\s+for|\boptions?\b)\b",
            re.I,
        ),
    ),
    ("short", re.compile(r"\b(short\s+interest|shorts?\s+float|days?\s+to\s+cover)\b", re.I)),
    ("dividends", re.compile(r"\b(dividend|dividends|yield|ex-?date|dvd)\b", re.I)),
    ("earnings", re.compile(r"\b(earnings?|eps|ern)\b", re.I)),
    ("analysts", re.compile(r"\b(analyst|analysts|price\s+target|ratings?|anr)\b", re.I)),
    ("holders", re.compile(r"\b(holders?|institutions?|insiders?|phdc|13f)\b", re.I)),
    ("financials", re.compile(r"\b(financials?|income\s+statement|balance\s+sheet|cash\s*flow|\bfa\b)\b", re.I)),
    ("news", re.compile(r"\b(news|headlines?|\bcn\b)\b", re.I)),
    # Volume before generic chart/quote so "volume chart" / "apples volume" win.
    (
        "volume",
        re.compile(
            r"\b(volume|vol\b|trading\s+volume|share\s+volume|daily\s+volume)\b",
            re.I,
        ),
    ),
    (
        "book",
        re.compile(
            r"\b(bid|ask|bids?|asks?|spread|top\s+of\s+book|bid[\s/-]?ask|mid\s*price|nbbo)\b",
            re.I,
        ),
    ),
    ("chart", re.compile(r"\b(chart|graph|plot|\bgp\b|candles?)\b", re.I)),
    ("quote", re.compile(r"\b(quote|price|des|ticker\s+card|pill|how'?s)\b", re.I)),
]


@dataclass
class Intent:
    action: str
    symbol: str | None = None
    symbols: list[str] = field(default_factory=list)
    period: str = "6m"
    statement: str = "income"
    expiry: str | None = None  # YYYY-MM-DD for options chain / contract
    query: str | None = None
    qty: float = 1.0
    position_id: int | None = None
    trader_mention: int | None = None
    server_wide: bool = False
    source: str = "local"  # local | gemini | fallback


def _normalize_action(raw: str | None) -> str:
    if not raw:
        return "ask"
    key = str(raw).strip().lower().replace("-", "_")
    return ACTION_ALIASES.get(key, key)


def _detect_period(text: str) -> str:
    t = text.lower()
    rules: list[tuple[str, str]] = [
        (r"\b(ytd|year[\s-]?to[\s-]?date)\b", "ytd"),
        (r"\b(max|all\s*time|everything)\b", "max"),
        (r"\b(5\s*y(ear)?s?|five\s+years?)\b", "5y"),
        (r"\b(1\s*y(ear)?|12\s*m(onths?)?|one\s+year|a\s+year)\b", "1y"),
        (r"\b(6\s*m(onths?)?|half\s+year|six\s+months?)\b", "6m"),
        (r"\b(3\s*m(onths?)?|quarter|three\s+months?)\b", "3m"),
        (r"\b(1\s*m(onth)?|one\s+month|a\s+month)\b", "1m"),
        (r"\b(5\s*d(ays?)?|one\s+week|a\s+week|past\s+week|this\s+week|last\s+week|\bweek\b)\b", "5d"),
        (r"\b(1\s*d(ay)?|today|intraday)\b", "1d"),
    ]
    for pattern, period in rules:
        if re.search(pattern, t):
            return period
    m = re.search(r"\b(1d|5d|1m|3m|6m|1y|5y|ytd|max)\b", t)
    if m:
        return m.group(1)
    return "6m"


def _detect_statement(text: str) -> str:
    t = text.lower()
    if re.search(r"\b(balance(\s+sheet)?)\b", t):
        return "balance"
    if re.search(r"\b(cash\s*flow|cashflow)\b", t):
        return "cashflow"
    return "income"


def _extract_expiry_hint(text: str) -> str | None:
    """Pull an explicit options expiry date from free text when present."""
    # Bare ISO first: "options AAPL 2026-11-20"
    m = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    if m:
        return m.group(1)

    m = re.search(
        r"\b(?:exp(?:iry|iration)?|expires?)\s+(?:on\s+)?"
        r"(\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b",
        text,
        re.I,
    )
    if m:
        raw = m.group(1)
        if re.match(r"\d{4}-\d{2}-\d{2}", raw):
            return raw
        parts = re.split(r"[/-]", raw)
        if len(parts) != 3:
            return None
        month, day, year = (int(parts[0]), int(parts[1]), int(parts[2]))
        if year < 100:
            year += 2000
        return f"{year:04d}-{month:02d}-{day:02d}"

    m = re.search(
        r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+"
        r"(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(\d{2,4}))?\b",
        text,
        re.I,
    )
    if not m:
        return None
    from datetime import date as _date

    from app.security import MONTHS

    month = MONTHS[m.group(1)[:3].upper()]
    day = int(m.group(2))
    year = int(m.group(3) or _date.today().year)
    if year < 100:
        year += 2000
    target = _date(year, month, day)
    if not m.group(3) and target < _date.today():
        target = _date(year + 1, month, day)
    return target.isoformat()


def _extract_symbols(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    # Option contracts first — otherwise "AAPL 360C 11/21/26" collapses to equity AAPL.
    for sym in extract_option_contracts(text):
        key = sym.upper()
        if key not in seen:
            seen.add(key)
            found.append(sym)

    for m in re.finditer(r"\$([A-Za-z][A-Za-z0-9.\-]{0,11})", text):
        sym = normalize_symbol(m.group(1))
        key = sym.upper()
        if key not in seen:
            seen.add(key)
            found.append(sym)

    # Company / index aliases as whole words (APPLE, BITCOIN, …)
    upper = text.upper()
    for alias in sorted(ALIASES.keys(), key=len, reverse=True):
        if re.search(rf"(?<![A-Z0-9]){re.escape(alias)}(?![A-Z0-9])", upper):
            sym = normalize_symbol(alias)
            key = sym.upper()
            if key not in seen:
                seen.add(key)
                found.append(sym)

    for m in TICKER_TOKEN.finditer(text):
        raw = m.group(1)
        if raw.upper().lstrip("$") in STOPWORDS:
            continue
        if raw.upper() in {"CN", "GP", "FA", "ANR", "ERN", "DVD", "OPT", "SEC", "RV"}:
            continue
        try:
            sym = normalize_symbol(raw)
        except Exception:
            continue
        key = sym.upper()
        if key in seen:
            continue
        clean = re.sub(r"[^A-Za-z]", "", raw)
        if len(clean) <= 1 or clean.upper() in STOPWORDS:
            continue
        # Reject obvious non-tickers that slipped past FX guard
        if sym.endswith("=X") and clean.upper() not in ALIASES:
            legs = clean.upper()
            from app.security import FX_CURRENCIES

            if len(legs) == 6 and not (
                legs[:3] in FX_CURRENCIES and legs[3:] in FX_CURRENCIES
            ):
                continue
        seen.add(key)
        found.append(sym)

    return found


def _detect_action(text: str) -> str | None:
    for action, pattern in ACTION_PATTERNS:
        if pattern.search(text):
            return action
    return None


def _extract_qty(text: str) -> float:
    patterns = [
        r"\b(?:buy|sell|long|short|book)\s+(\d+(?:\.\d+)?)\s+",
        r"\bx\s*(\d+(?:\.\d+)?)\b",
        r"\b(\d+(?:\.\d+)?)\s+(?:shares?|units?)\b",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                continue
    return 1.0


def _extract_position_id(text: str) -> int | None:
    m = re.search(r"(?:position\s*)?#\s*(\d+)\b", text, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"\b(?:close|flatten|exit)\s+(?:paper\s+)?(?:position\s+)?(\d+)\b", text, re.I)
    if m:
        return int(m.group(1))
    return None


def _extract_mention(text: str) -> int | None:
    m = re.search(r"<@!?(\d+)>", text)
    return int(m.group(1)) if m else None


def _intent_from_parts(
    *,
    action: str,
    symbols: list[str],
    period: str,
    statement: str,
    qty: float,
    position_id: int | None,
    mention: int | None,
    server_wide: bool,
    last_ticker: str | None,
    text: str,
    source: str,
) -> Intent | None:
    from app.market.bonds import looks_like_bond_query

    if looks_like_bond_query(text) or (action == "bond" and not symbols):
        return Intent(action="bond", query=text, source=source)

    if action.startswith("paper_"):
        if action == "paper_buy" and not (symbols or last_ticker):
            return None
        if action == "paper_sell" and not (symbols or last_ticker):
            return None
        if action == "paper_close" and position_id is None:
            return None
        return Intent(
            action=action,
            symbol=(symbols[0] if symbols else last_ticker),
            symbols=symbols,
            qty=qty,
            position_id=position_id,
            trader_mention=mention,
            server_wide=server_wide,
            source=source,
        )

    if action == "compare":
        if len(symbols) >= 2:
            return Intent(action="compare", symbols=symbols[:8], period=period, source=source)
        return None

    if action in {"fgi", "heatmap", "help"}:
        return Intent(action=action, source=source)

    symbol = symbols[0] if symbols else last_ticker
    if action and symbol:
        return Intent(
            action=action,
            symbol=symbol,
            symbols=symbols,
            period=period,
            statement=statement,
            source=source,
        )

    if not action and symbol:
        return Intent(action="quote", symbol=symbol, period=period, source=source)

    if action and last_ticker and action not in {"fgi", "heatmap", "help", "bond", "compare"}:
        return Intent(
            action=action,
            symbol=last_ticker,
            period=period,
            statement=statement,
            source=source,
        )
    return None


def parse_local(text: str, *, last_ticker: str | None = None) -> Intent | None:
    text = (text or "").strip()
    if not text:
        return None

    symbols = _extract_symbols(text)
    action = _detect_action(text) or ""
    # Bare / quoted option contract → quote that OCC, not the equity root.
    if symbols and re.match(r"^[A-Z]{1,6}\d{6}[CP]\d{8}$", symbols[0].upper()):
        if not action or action in {"quote", "options"}:
            action = "quote"

    intent = _intent_from_parts(
        action=action,
        symbols=symbols,
        period=_detect_period(text),
        statement=_detect_statement(text),
        qty=_extract_qty(text),
        position_id=_extract_position_id(text),
        mention=_extract_mention(text),
        server_wide=bool(
            re.search(r"\b(server|everyone|all\s+traders?|desk|team)\b", text, re.I)
        ),
        last_ticker=last_ticker,
        text=text,
        source="local",
    )
    if intent:
        occ = re.match(
            r"^([A-Z]{1,6})(\d{2})(\d{2})(\d{2})[CP]\d{8}$",
            (symbols[0] if symbols else "").upper(),
        )
        if occ:
            intent.expiry = f"20{occ.group(2)}-{occ.group(3)}-{occ.group(4)}"
        else:
            hint = _extract_expiry_hint(text)
            if hint and intent.symbol:
                from datetime import date as _date

                from app.security import nearest_listed_expiry

                try:
                    root = intent.symbol.upper()
                    intent.expiry = nearest_listed_expiry(
                        root, _date.fromisoformat(hint)
                    ).isoformat()
                except Exception:
                    intent.expiry = hint
    return intent


def _parse_planner_json(raw: str) -> dict | None:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None


def plan_with_gemini(text: str, *, last_ticker: str | None = None) -> Intent | None:
    """MCP-style planner: pick ONE desk tool to post (not a prose answer)."""
    if not gemini.available():
        return None

    prompt = f"""You are MarkIt's desk agent (MCP-style tool router) inside Discord.
Pick ONE tool to POST as a Discord message. Do NOT write research prose.
Return ONLY compact JSON (no markdown).

Available tools:
{DESK_TOOLS}

JSON keys:
  action: tool name (prefer post_* names)
  symbol: Yahoo ticker OR null (resolve company names: apples→AAPL, google→GOOGL)
  symbols: array for compare, else []
  period: 1d|5d|1m|3m|6m|1y|5y|ytd|max
  statement: income|balance|cashflow
  expiry: YYYY-MM-DD for options when the user named a date, else null
  query: bond string if post_bond, else null
  qty: number for paper trades (default 1)
  position_id: int or null
  trader_mention: snowflake or null
  server_wide: bool

Rules:
- "show me apples volume for the past week" → post_volume / AAPL / 5d
- "graph NVDA" / "chart apple 3m" → post_chart
- "quote AAPL" / "pill on tesla" → post_pill
- "what's the bid on AAPL" / "AAPL spread" / "show ask" → post_book
- "AAPL 360C 11/21/26" / "quote the AAPL Nov 20 362.5 call" → post_pill with OCC symbol (not equity AAPL)
- "options chain AAPL exp 2026-11-20" → post_options with that expiry
- "filings for MSFT" → post_filings
- Never invent FX pairs from English words (APPLES is Apple Inc., not FX).
- Prefer the most specific artifact for what they asked.
- For options, put the full OCC or strike+expiry in symbol/expiry — never substitute a different week.

Last ticker in channel: {last_ticker or "none"}
User request: {text}
"""
    try:
        # Planner must NOT use research tools — we want a JSON plan, then the
        # cog posts the Discord artifact. Use ask_raw if present; else ask.
        if hasattr(gemini, "ask_plain"):
            raw = gemini.ask_plain(prompt)
        else:
            raw = gemini.ask(prompt)
    except Exception as exc:
        log.warning("gemini desk plan failed: %s", exc)
        return None

    data = _parse_planner_json(raw)
    if not data:
        return None

    action = _normalize_action(data.get("action"))
    symbol = data.get("symbol")
    symbols = data.get("symbols") or []
    if isinstance(symbols, str):
        symbols = [s for s in symbols.replace(",", " ").split() if s.strip()]
    period = str(data.get("period") or "6m").lower()
    if period not in PERIODS:
        period = _detect_period(text)
    statement = str(data.get("statement") or "income").lower()
    if statement not in {"income", "balance", "cashflow"}:
        statement = "income"
    expiry = data.get("expiry")
    if expiry:
        expiry = str(expiry).strip()[:10]
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", expiry):
            expiry = _extract_expiry_hint(text) or _extract_expiry_hint(str(data.get("expiry")))
    else:
        expiry = _extract_expiry_hint(text)
    query = data.get("query")
    try:
        qty_f = float(data.get("qty", 1) or 1)
    except (TypeError, ValueError):
        qty_f = 1.0
    try:
        position_id_i = int(data["position_id"]) if data.get("position_id") is not None else None
    except (TypeError, ValueError):
        position_id_i = None
    try:
        trader_mention_i = (
            int(data["trader_mention"]) if data.get("trader_mention") is not None else None
        )
    except (TypeError, ValueError):
        trader_mention_i = None

    paper_actions = {
        "paper_buy",
        "paper_sell",
        "paper_close",
        "paper_positions",
        "paper_pnl",
        "paper_leaderboard",
        "paper_server",
    }
    if symbol:
        try:
            symbol = normalize_symbol(str(symbol))
        except Exception:
            symbol = None
    elif last_ticker and action not in {
        "fgi",
        "heatmap",
        "help",
        "bond",
        "compare",
        "ask",
        *paper_actions,
    }:
        symbol = last_ticker
    elif last_ticker and action in {"paper_buy", "paper_sell"} and not symbol:
        symbol = last_ticker

    norm_symbols: list[str] = []
    for s in symbols:
        try:
            norm_symbols.append(normalize_symbol(str(s)))
        except Exception:
            continue

    if expiry and symbol and action in {"options", "quote", "book"}:
        from datetime import date as _date

        from app.security import nearest_listed_expiry

        try:
            root = re.sub(r"\d{6}[CP]\d{8}$", "", symbol.upper()) or symbol
            expiry = nearest_listed_expiry(root, _date.fromisoformat(expiry)).isoformat()
        except Exception:
            pass

    return Intent(
        action=action,
        symbol=symbol,
        symbols=norm_symbols,
        period=period,
        statement=statement,
        expiry=expiry,
        query=str(query) if query else None,
        qty=qty_f,
        position_id=position_id_i,
        trader_mention=trader_mention_i,
        server_wide=bool(data.get("server_wide")),
        source="gemini",
    )


# Back-compat name used by older tests / imports
def parse_with_gemini(text: str, *, last_ticker: str | None = None) -> Intent | None:
    return plan_with_gemini(text, last_ticker=last_ticker)


def resolve_intent(text: str, *, last_ticker: str | None = None) -> Intent:
    """Plan which desk tool to post.

    Prefer Gemini (agent) when available so company names + nuanced asks
    ("volume last week", "filings", "pill") map to the right artifact.
    Fall back to local patterns when Gemini is down or returns junk.
    """
    # Fast local path when the phrase is already unambiguous ticker+verb.
    local = parse_local(text, last_ticker=last_ticker)
    local_confident = bool(
        local
        and local.action
        and local.action != "ask"
        and (
            local.action in {"fgi", "heatmap", "help"}
            or local.action.startswith("paper_")
            or (local.symbol and local.action in {
                "chart", "volume", "news", "filings", "quote", "book", "compare",
                "financials", "holders", "analysts", "earnings", "dividends",
                "options", "short", "congress", "bond",
            })
            or (local.action == "compare" and len(local.symbols) >= 2)
            or (local.action == "bond" and local.query)
        )
    )

    # Company-name / volume / messy English → let the agent decide first.
    messy = bool(
        re.search(
            r"\b(apple|apples|google|alphabet|microsoft|amazon|nvidia|tesla|"
            r"volume|filings?|pill|graph|show me|what(?:'| i)?s)\b",
            text,
            re.I,
        )
    )

    if gemini.available() and (messy or not local_confident):
        gem = plan_with_gemini(text, last_ticker=last_ticker)
        if gem and gem.action and gem.action != "ask":
            return gem

    if local_confident and local:
        return local

    if gemini.available():
        gem = plan_with_gemini(text, last_ticker=last_ticker)
        if gem:
            return gem

    if local:
        return local

    symbols = _extract_symbols(text)
    if symbols:
        return Intent(action="quote", symbol=symbols[0], source="fallback")
    return Intent(action="ask", query=text, source="fallback")
