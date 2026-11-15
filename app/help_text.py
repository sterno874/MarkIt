from __future__ import annotations

HELP_OVERVIEW = """
# Market Desk

Paste a ticker (`AAPL`, `$NVDA`, `EURUSD`, `BTC`, `CL=F`) or use slash commands.
The bot posts a Bloomberg-style pill with quote + function buttons.

**Asset types:** equities · ETFs · indices · FX · crypto · futures · options · **individual corporate bonds (TRACE)** · bond ETFs / rates

Use `/help topic:<name>` for details. Topics: `tickers`, `commands`, `bonds`, `alerts`, `watchlist`, `ideas`, `desk`, `ask`, `bugs`, `symbols`.
""".strip()

HELP_TOPICS: dict[str, str] = {
    "tickers": """
## Tickers & the pill

- Paste `$AAPL` or a message that is only a symbol → pill with price and buttons
- Buttons map to Bloomberg-style functions: **GP** chart, **DES** description, **FA** financials, **CN** news, **PHDC** holders, **ANR** analysts, **ERN** earnings, **DVD** dividends
- The channel remembers the last ticker for a few minutes, so `/chart` with no symbol uses it

### Symbol cheatsheet
| You type | Resolves to |
|---|---|
| `AAPL` | Equity |
| `SPY` / `TLT` | ETF / bond ETF |
| `SPX` / `VIX` | Index |
| `EURUSD` / `USDJPY` | FX |
| `BTC` / `ETH-USD` | Crypto |
| `CL=F` / `GC=F` / `ES` | Futures |
| `AAPL 275C 11/16/26` | Option contract |
""".strip(),
    "commands": """
## Slash commands (research)

| Command | Alias | What it does |
|---|---|---|
| `/quote` | `/des` | Pill / description |
| `/chart` | `/gp` | Price chart image |
| `/financials` | `/fa` | Income / balance / cash flow |
| `/news` | `/cn` | Headlines |
| `/holders` | `/phdc` | Institutions + insiders |
| `/analysts` | `/anr` | Ratings & targets |
| `/earnings` | `/ern` | Dates & estimates |
| `/dividends` | `/dvd` | Yield & ex-date |
| `/options` | `/opt` | Options chain snapshot |
| `/compare` | `/rv` | Relative performance chart |
| `/short` | | Short interest |
| `/filings` | `/sec` | Recent SEC filings |
| `/congress` | | STOCK Act disclosures |
| `/heatmap` | `/hmap` | Watchlist / movers board |
| `/fgi` | | Fear & Greed (stocks + crypto) |
| `/bond` | | Corporate bond via TRACE (coupon / CUSIP) |
""".strip(),
    "bonds": """
## Corporate bonds (TRACE)

Yahoo does **not** cover individual corporates. Market Desk resolves them through OpenFIGI + FINRA TRACE.

Examples that work in chat or `/bond`:
- `IHRT 8 3/8 May 2027`
- `IHRT 8.375 05/01/27`
- CUSIP `45174HBD8`
- FINRA symbol `IHRT4830027`

The pill shows last TRACE print (price as % of par), YTM, ratings, callability, and links to FINRA / BondFacts / TradingView trade history.

Treasury / agency bonds also work when you pass a CUSIP; bond *ETFs* (`TLT`, `HYG`) stay on the equity path.
""".strip(),
    "alerts": """
## Alerts

`/alert price symbol:AAPL above:200`
`/alert percent symbol:NVDA move:5`
`/alert date when:2026-12-01 note:Revisit ASTS`
`/alert insider symbol:ASTS min_value:100000`
`/alert filing symbol:AAPL forms:8-K,10-Q`
`/alert earnings symbol:AAPL`
`/alert dividend symbol:KO`
`/alert trailing symbol:SPY trail_pct:8`
`/alerts` list yours · `/alert-cancel id:12` remove one

Alerts ping you (and optionally the alerts channel).
""".strip(),
    "watchlist": """
## Watchlists

`/watch AAPL,MSFT tag:tech` — personal
`/watch SPY server:True` — shared server list
`/watchlist` · `/unwatch AAPL` · `/unwatch tag:tech`
Server watchlist feeds the morning/close briefs and `/heatmap`.
""".strip(),
    "ideas": """
## Trade ideas

`/idea long ASTS entry:28 stop:24 target:40 note:spectrum thesis`
`/ideas` open ideas · `/idea-close id:3 exit:35`

Creates a card in-channel so the desk can track the thesis without a spreadsheet.
""".strip(),
    "desk": """
## Desk rhythm

`/brief morning` · `/brief close` — indices, rates, watchlist, next earnings
`/schedule channel:#markets morning:True close:True` — auto-post
`/board` — refreshable quote board for the server watchlist
`/paper buy AAPL qty:10` · `/paper positions` · `/paper close id:1`
`/webhook` — show TradingView webhook URL (if WEBHOOK_PORT is set)
""".strip(),
    "ask": """
## Gemini (`/ask`)

Set `GEMINI_API_KEY` in `.env`. Then:
`/ask What happened to NVDA after earnings?`
or @mention the bot with a question.

Gemini can call desk tools (quote, chart summary, news, filings, etc.) and answer in plain language.
""".strip(),
    "bugs": """
## Bug tickets

When something breaks in chat:
`/bug the chart button for CL=F times out`
`/report-bug command:chart description:blank image for EURUSD severity:high`

Creates ticket `#42`, posts it to the bugs channel (if configured), and writes `data/tickets/00042.json` so an agent or `/bugs pickup` flow can claim and fix it.

Staff / automations:
`/bugs list` · `/bugs show id:42` · `/bugs claim id:42` · `/bugs resolve id:42 note:fixed yfinance period`
`/bugs channel #bugs` — set the ticket channel
""".strip(),
    "symbols": """
## Multi-asset symbols

**Equities:** `AAPL`, `BRK-B` (or `BRK.B`)
**ETFs / bond funds:** `SPY`, `QQQ`, `TLT`, `HYG`, `AGG`
**Indices:** `SPX`, `NDX`, `VIX`, `DJI` (or `^GSPC`)
**FX:** `EURUSD`, `GBPUSD`, `USDJPY`, `EUR/USD`
**Crypto:** `BTC`, `ETH`, `SOL-USD`
**Futures:** `CL=F` oil, `GC=F` gold, `ES` / `ES=F` S&P, `ZN=F` 10y
**Rates:** `TNX` / `US10Y`, `US2Y`
**Options:** OCC `AAPL261116C00275000` or shorthand `AAPL 275C 11/16/26`
**Corporate bonds:** `IHRT 8 3/8 May 2027`, CUSIP, or FINRA symbol — TRACE last sale

Equity/FX/crypto/futures quotes are Yahoo-sourced (may be delayed). Bond prints are FINRA TRACE last sale.
""".strip(),
}


def topic_list() -> str:
    return ", ".join(f"`{k}`" for k in HELP_TOPICS)
