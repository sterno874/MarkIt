"""Natural-language router for `/markit`.

Fast local parsing for common desk requests; optional Gemini JSON fallback
when the phrase is ambiguous. Returns structured intents the cog executes
as real desk outputs (chart image, news embed, quote pill, …).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from app.security import ALIASES, TICKER_TOKEN, normalize_symbol
from app.services import gemini

log = logging.getLogger("market-desk.markit_nl")

PERIODS = {"1d", "5d", "1m", "3m", "6m", "1y", "5y", "ytd", "max"}

STOPWORDS = {
    "A",
    "AN",
    "THE",
    "ME",
    "MY",
    "ON",
    "FOR",
    "OF",
    "TO",
    "AND",
    "OR",
    "VS",
    "VERSUS",
    "WITH",
    "ABOUT",
    "SHOW",
    "GET",
    "GIVE",
    "PULL",
    "FIND",
    "LOOK",
    "WANT",
    "NEED",
    "PLEASE",
    "CAN",
    "YOU",
    "JUST",
    "WHAT",
    "WHATS",
    "HOW",
    "IS",
    "ARE",
    "WAS",
    "WERE",
    "IT",
    "ITS",
    "THIS",
    "THAT",
    "LAST",
    "PRICE",
    "QUOTE",
    "CHART",
    "GRAPH",
    "PLOT",
    "NEWS",
    "HEADLINES",
    "HEADLINE",
    "EARNINGS",
    "DIVIDEND",
    "DIVIDENDS",
    "OPTIONS",
    "OPTION",
    "FILINGS",
    "FILING",
    "HOLDERS",
    "ANALYSTS",
    "ANALYST",
    "SHORT",
    "INTEREST",
    "CONGRESS",
    "BOND",
    "BONDS",
    "COMPARE",
    "PERFORMANCE",
    "RELATIVE",
    "HEATMAP",
    "FEAR",
    "GREED",
    "FGI",
    "HELP",
    "FINANCIALS",
    "INCOME",
    "BALANCE",
    "CASHFLOW",
    "CASH",
    "FLOW",
    "STATEMENT",
    "MONTH",
    "MONTHS",
    "YEAR",
    "YEARS",
    "WEEK",
    "WEEKS",
    "DAY",
    "DAYS",
    "TODAY",
    "YTD",
    "MAX",
    "OVER",
    "PAST",
    "SINCE",
    "FROM",
    "IN",
    "AT",
    "UP",
    "DOWN",
    "SOME",
    "ANY",
    "INFO",
    "INFORMATION",
    "DATA",
    "DESK",
    "MARKIT",
    "TELL",
    "RETURN",
    "RUN",
    "DO",
    "I",
    "IM",
    "I'D",
    "LIKE",
    "SEE",
    "CHECK",
    "QUICK",
    "QUICKLY",
    "PAPER",
    "BOOK",
    "BUY",
    "SELL",
    "LONG",
    "SHORT",
    "LEADERBOARD",
    "PNL",
    "P&L",
    "ATTRIBUTION",
    "POSITIONS",
    "POSITION",
    "CLOSE",
    "CLOSED",
    "OPEN",
    "SERVER",
    "TOTAL",
    "TRADER",
    "TRADERS",
    "SHARES",
    "SHARE",
    "UNITS",
}

# (action, compiled pattern) — first match wins; order = specificity
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
        re.compile(
            r"\b((paper\s+)?(sell|short)|book\s+a\s+short|paper\s+short)\b",
            re.I,
        ),
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
    ("options", re.compile(r"\b(options?\s+chain|option\s+chain|\bopt\b|calls?\s+and\s+puts?)\b", re.I)),
    ("short", re.compile(r"\b(short\s+interest|shorts?\s+float|days?\s+to\s+cover)\b", re.I)),
    ("dividends", re.compile(r"\b(dividend|dividends|yield|ex-?date|dvd)\b", re.I)),
    ("earnings", re.compile(r"\b(earnings?|eps|ern)\b", re.I)),
    ("analysts", re.compile(r"\b(analyst|analysts|price\s+target|ratings?|anr)\b", re.I)),
    ("holders", re.compile(r"\b(holders?|institutions?|insiders?|phdc|13f)\b", re.I)),
    ("financials", re.compile(r"\b(financials?|income\s+statement|balance\s+sheet|cash\s*flow|\bfa\b)\b", re.I)),
    ("news", re.compile(r"\b(news|headlines?|\bcn\b)\b", re.I)),
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
    query: str | None = None
    qty: float = 1.0
    position_id: int | None = None
    trader_mention: int | None = None  # Discord snowflake from <@id>
    server_wide: bool = False
    source: str = "local"  # local | gemini | fallback


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
        (r"\b(5\s*d(ays?)?|one\s+week|a\s+week|week)\b", "5d"),
        (r"\b(1\s*d(ay)?|today|intraday)\b", "1d"),
    ]
    for pattern, period in rules:
        if re.search(pattern, t):
            return period
    # bare tokens like "period 3m"
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


def _extract_symbols(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    # Explicit $TICKER
    for m in re.finditer(r"\$([A-Za-z][A-Za-z0-9.\-]{0,11})", text):
        sym = normalize_symbol(m.group(1))
        key = sym.upper()
        if key not in seen:
            seen.add(key)
            found.append(sym)

    # Alias words (BTC, SPX, …) as whole words
    upper = text.upper()
    for alias in sorted(ALIASES.keys(), key=len, reverse=True):
        if re.search(rf"(?<![A-Z0-9]){re.escape(alias)}(?![A-Z0-9])", upper):
            sym = normalize_symbol(alias)
            key = sym.upper()
            if key not in seen:
                seen.add(key)
                found.append(sym)

    # Generic ticker tokens
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
        # Skip tiny / likely English leftovers
        clean = re.sub(r"[^A-Za-z]", "", raw)
        if len(clean) <= 1:
            continue
        if clean.upper() in STOPWORDS:
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
    # "buy 10 AAPL", "paper buy AAPL x5", "book 2.5 NVDA"
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


def parse_local(text: str, *, last_ticker: str | None = None) -> Intent | None:
    text = (text or "").strip()
    if not text:
        return None

    action = _detect_action(text)
    period = _detect_period(text)
    statement = _detect_statement(text)
    symbols = _extract_symbols(text)
    qty = _extract_qty(text)
    position_id = _extract_position_id(text)
    mention = _extract_mention(text)
    server_wide = bool(
        re.search(r"\b(server|everyone|all\s+traders?|desk|team)\b", text, re.I)
    )

    # Bond free-text: keep original query when it looks like a bond string
    from app.market.bonds import looks_like_bond_query

    if looks_like_bond_query(text) or (action == "bond" and not symbols):
        return Intent(
            action="bond",
            query=text,
            source="local",
        )

    # Paper desk — no symbol required for books / leaderboard / pnl
    if action and action.startswith("paper_"):
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
            source="local",
        )

    if action == "compare":
        if len(symbols) >= 2:
            return Intent(action="compare", symbols=symbols[:8], period=period, source="local")
        return None

    if action in {"fgi", "heatmap", "help"}:
        return Intent(action=action, source="local")

    symbol = symbols[0] if symbols else last_ticker
    if action and symbol:
        return Intent(
            action=action,
            symbol=symbol,
            symbols=symbols,
            period=period,
            statement=statement,
            source="local",
        )

    # Bare ticker / "AAPL please" → quote
    if not action and symbol:
        return Intent(action="quote", symbol=symbol, period=period, source="local")

    # Action without symbol but we have channel memory
    if action and last_ticker and action not in {"fgi", "heatmap", "help", "bond", "compare"}:
        return Intent(
            action=action,
            symbol=last_ticker,
            period=period,
            statement=statement,
            source="local",
        )

    return None


def parse_with_gemini(text: str, *, last_ticker: str | None = None) -> Intent | None:
    if not gemini.available():
        return None

    prompt = f"""You route Discord Market Desk requests to ONE desk action.
Return ONLY compact JSON (no markdown) with keys:
  action: one of quote, chart, news, financials, holders, analysts, earnings, dividends,
          options, short, filings, congress, bond, compare, fgi, heatmap, help, ask,
          paper_buy, paper_sell, paper_close, paper_positions, paper_pnl,
          paper_leaderboard, paper_server
  symbol: ticker string or null
  symbols: array of tickers (for compare) or []
  period: one of 1d,5d,1m,3m,6m,1y,5y,ytd,max (default 6m)
  statement: income|balance|cashflow (for financials)
  query: original bond string if action=bond, else null
  qty: number (default 1) for paper_buy/paper_sell
  position_id: int or null for paper_close
  trader_mention: Discord user snowflake int or null
  server_wide: bool

Examples:
  "show me the chart on aapl" → {{"action":"chart","symbol":"AAPL","symbols":[],"period":"6m","statement":"income","query":null,"qty":1,"position_id":null,"trader_mention":null,"server_wide":false}}
  "paper buy 10 AAPL" → {{"action":"paper_buy","symbol":"AAPL","symbols":[],"period":"6m","statement":"income","query":null,"qty":10,"position_id":null,"trader_mention":null,"server_wide":false}}
  "leaderboard" → {{"action":"paper_leaderboard","symbol":null,"symbols":[],"period":"6m","statement":"income","query":null,"qty":1,"position_id":null,"trader_mention":null,"server_wide":false}}
  "server pnl" → {{"action":"paper_server","symbol":null,"symbols":[],"period":"6m","statement":"income","query":null,"qty":1,"position_id":null,"trader_mention":null,"server_wide":true}}
  "my pnl" → {{"action":"paper_pnl","symbol":null,"symbols":[],"period":"6m","statement":"income","query":null,"qty":1,"position_id":null,"trader_mention":null,"server_wide":false}}
  "close position #3" → {{"action":"paper_close","symbol":null,"symbols":[],"period":"6m","statement":"income","query":null,"qty":1,"position_id":3,"trader_mention":null,"server_wide":false}}

Last ticker in channel: {last_ticker or "none"}
User request: {text}
"""
    try:
        raw = gemini.ask(prompt)
    except Exception as exc:
        log.warning("gemini route failed: %s", exc)
        return None

    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Sometimes models wrap JSON in prose — grab first {...}
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None

    action = str(data.get("action") or "ask").lower().strip()
    symbol = data.get("symbol")
    symbols = data.get("symbols") or []
    if isinstance(symbols, str):
        symbols = [s for s in symbols.replace(",", " ").split() if s.strip()]
    period = str(data.get("period") or "6m").lower()
    if period not in PERIODS:
        period = "6m"
    statement = str(data.get("statement") or "income").lower()
    if statement not in {"income", "balance", "cashflow"}:
        statement = "income"
    query = data.get("query")
    qty = data.get("qty", 1)
    try:
        qty_f = float(qty)
    except (TypeError, ValueError):
        qty_f = 1.0
    position_id = data.get("position_id")
    try:
        position_id_i = int(position_id) if position_id is not None else None
    except (TypeError, ValueError):
        position_id_i = None
    trader_mention = data.get("trader_mention")
    try:
        trader_mention_i = int(trader_mention) if trader_mention is not None else None
    except (TypeError, ValueError):
        trader_mention_i = None
    server_wide = bool(data.get("server_wide"))

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
        symbol = normalize_symbol(str(symbol))
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

    norm_symbols = []
    for s in symbols:
        try:
            norm_symbols.append(normalize_symbol(str(s)))
        except Exception:
            continue

    return Intent(
        action=action,
        symbol=symbol,
        symbols=norm_symbols,
        period=period,
        statement=statement,
        query=str(query) if query else None,
        qty=qty_f,
        position_id=position_id_i,
        trader_mention=trader_mention_i,
        server_wide=server_wide,
        source="gemini",
    )


def resolve_intent(text: str, *, last_ticker: str | None = None) -> Intent:
    local = parse_local(text, last_ticker=last_ticker)
    if local:
        return local
    gem = parse_with_gemini(text, last_ticker=last_ticker)
    if gem:
        return gem
    # Last resort: treat as free-form ask / quote attempt
    symbols = _extract_symbols(text)
    if symbols:
        return Intent(action="quote", symbol=symbols[0], source="fallback")
    return Intent(action="ask", query=text, source="fallback")
