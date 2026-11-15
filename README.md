# MarkIt · Market Desk

A Discord research bot for investing communities — Bloomberg-style ticker pills, multi-asset quotes, TRACE corporate bonds, alerts, watchlists, trade ideas, and optional Gemini Q&A.

Paste a ticker. Get a card. Drill in with slash commands.

---

## For community members

Once the bot is in your server, you barely need this doc. Type `/help` in Discord anytime.

### The fastest way to use it

**Plain English** — no need to memorize slash commands:

```
/markit show me the chart on AAPL
/markit news for NVDA
/markit quote BTC
/markit compare AAPL and MSFT over a year
/markit IHRT 8 3/8 May 2027
/markit fear and greed
```

Or paste a symbol in chat (or prefix with `$`):

```
AAPL
$NVDA
EURUSD
BTC
CL=F
IHRT 8 3/8 May 2027
```

The bot posts a **pill** — price, change, and function buttons (GP / DES / FA / CN / …).  
Slash fields also **autocomplete** — type a few letters of a ticker or bond and pick from the list.

The channel remembers the last ticker for a few minutes, so `/chart` or `/markit show the chart` reuses it.

---

## Quick examples

### Quotes & charts

```
/quote symbol:AAPL
/quote symbol:SPY
/quote symbol:BTC
/quote symbol:EURUSD
/quote symbol:CL=F
/des symbol:NVDA

/chart symbol:TSLA period:3m
/gp symbol:SPX period:1y
/compare symbols:AAPL MSFT GOOGL period:6m
/heatmap
/fgi
```

**Chart periods:** `1d` `5d` `1m` `3m` `6m` `1y` `5y` `ytd` `max`

### Corporate bonds (FINRA TRACE)

Individual corporates are **not** on Yahoo. MarkIt resolves them via OpenFIGI + TRACE last sale.

```
/bond query:IHRT 8 3/8 May 2027
/bond query:IHRT 8.375 05/01/27
/bond query:45174HBD8
/quote-smart query:IHRT 8 3/8 May 2027
```

You can also paste the bond string directly in chat. The pill shows TRACE last print (% of par), YTM when available, ratings, and links out to FINRA / BondFacts.

Bond *ETFs* (`TLT`, `HYG`, `LQD`) still use the normal equity path:

```
/quote symbol:TLT
/chart symbol:HYG period:1y
```

### Fundamentals & filings

```
/financials symbol:AAPL statement:income
/fa symbol:MSFT statement:cashflow quarterly:True
/news symbol:NVDA
/holders symbol:ASTS
/analysts symbol:PLTR
/earnings symbol:AAPL
/dividends symbol:KO
/options symbol:SPY
/short symbol:GME
/filings symbol:AAPL
/sec symbol:TSLA forms:8-K,10-Q
/congress symbol:NVDA
```

### Alerts

```
/alert price symbol:AAPL above:200
/alert price symbol:ASTS below:20
/alert percent symbol:NVDA move:5
/alert trailing symbol:SPY trail_pct:8
/alert date when:2026-12-01 note:Revisit thesis
/alert earnings symbol:AAPL
/alert dividend symbol:KO
/alert insider symbol:ASTS min_value:100000
/alert filing symbol:AAPL forms:8-K,10-Q,10-K

/alerts
/alert-cancel id:12
```

Admins can set a shared alerts channel:

```
/alerts-channel channel:#alerts
```

### Watchlists

```
/watch tickers:AAPL,MSFT,NVDA tag:tech
/watch tickers:SPY,TLT,HYG server:True
/watchlist
/watchlist server:True
/unwatch ticker:AAPL
/unwatch tag:tech
```

The **server** watchlist feeds `/brief`, `/board`, and `/heatmap`.

### Trade ideas & paper PnL

```
/idea side:long symbol:ASTS entry:28 stop:24 target:40 note:spectrum thesis
/ideas
/idea-close id:3 exit:35

/paper action:buy symbol:AAPL qty:10
/paper action:sell symbol:NVDA qty:5
/paper action:positions
/paper action:positions server_wide:True
/paper action:close position_id:1
/paper action:pnl
/paper action:pnl trader:@someone
/paper action:leaderboard
/paper action:server
/leaderboard
/pnl
```

**Attribution:** every paper fill is tagged to the Discord user who booked it.  
**Server PnL** = sum of all traders’ realized (closed) + unrealized (open marks).  
**Leaderboard** ranks traders by total attributed PnL.

Natural language:

```
/markit paper buy 10 AAPL
/markit paper short NVDA
/markit my pnl
/markit server pnl
/markit leaderboard
/markit show open positions
/markit close position #3
```

### Desk briefs

```
/brief kind:morning
/brief kind:close
/board
/schedule channel:#markets morning:True close:True
```

### Ask Gemini (if enabled)

```
/ask question:What moved NVDA after earnings?
```

You can also @mention the bot with a question. Without a Gemini key, everything else still works.

### Report a bug

```
/bug description:chart blank for CL=F command:chart severity:high
/report-bug description:bond lookup timed out on IHRT command:bond
/bugs list
/bugs show id:42
```

---

## Symbol cheatsheet

| You type | Asset |
|---|---|
| `AAPL`, `BRK-B` | Equity |
| `SPY`, `QQQ`, `IWM` | ETF |
| `TLT`, `HYG`, `LQD` | Bond ETF |
| `SPX`, `NDX`, `VIX`, `DJI` | Index |
| `TNX`, `US10Y`, `US2Y` | Rates / yields |
| `EURUSD`, `USDJPY`, `GBP/USD` | FX |
| `BTC`, `ETH`, `SOL-USD` | Crypto |
| `CL=F`, `GC=F`, `ES`, `NQ=F` | Futures |
| `AAPL 275C 11/16/26` | Option |
| `IHRT 8 3/8 May 2027`, CUSIP | Corporate bond (TRACE) |

Aliases like `BTC` → `BTC-USD`, `SPX` → `^GSPC`, `ES` → `ES=F` are built in. Slash fields autocomplete against Yahoo (and OpenFIGI for bonds), plus your watchlist and the channel’s last ticker.

---

## Slash command map

| Command | Alias | What it does |
|---|---|---|
| `/quote` | `/des` | Bloomberg-style pill |
| `/quote-smart` | | Auto-detect equity vs bond |
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
| `/heatmap` | `/hmap` | Watchlist movers board |
| `/fgi` | | Fear & Greed (stocks + crypto) |
| `/bond` | | Corporate bond via TRACE |
| `/alert …` | | Price / event reminders |
| `/watch` `/watchlist` | | Personal or server lists |
| `/idea` `/ideas` | | Structured trade cards |
| `/brief` `/board` | | Desk rhythm |
| `/paper` | | Paper buy / sell / positions |
| `/ask` | | Gemini Q&A (optional) |
| `/help` | | In-bot docs (`/help topic:bonds`) |
| `/bug` `/bugs` | | Ticket desk |

In Discord: `/help topic:tickers` · `commands` · `bonds` · `alerts` · `watchlist` · `ideas` · `desk` · `ask` · `bugs` · `symbols`

---

## Data sources & caveats

| Asset | Source | Notes |
|---|---|---|
| Equities, ETFs, FX, crypto, futures, options, indices | Yahoo Finance | May be delayed; not a consolidated tape |
| Corporate bonds | OpenFIGI + **FINRA TRACE** | Last sale as % of par; YTM when available |
| Filings | SEC EDGAR | Set a polite `SEC_USER_AGENT` with an email |
| Congress trades | Public STOCK Act feeds | Best-effort |
| Fear & Greed | Public sentiment endpoints | Stocks + crypto |

This is a **research desk**, not a broker. No orders are routed. Paper trading is local to the bot’s SQLite DB.

---

## Invite the bot (admins)

1. [Discord Developer Portal](https://discord.com/developers/applications) → your application → **Bot**
2. Enable **Message Content Intent**
3. OAuth2 URL Generator → scopes `bot` + `applications.commands`
4. Permissions: Send Messages, Embed Links, Attach Files, Read Message History
5. Open the invite URL and pick a server

Slash commands appear immediately in servers listed in `DISCORD_GUILD_ID` (comma-separated). Other servers still work via global sync (can take up to ~1 hour).

---

## Run it yourself (local)

Requirements: Python **3.13**, [uv](https://github.com/astral-sh/uv)

```bash
git clone https://github.com/sterno874/MarkIt.git
cd MarkIt
cp .env.example .env
# edit DISCORD_TOKEN
# optional: DISCORD_GUILD_ID=111,222   GEMINI_API_KEY=...

uv venv --python 3.13 .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
uv pip install -r requirements.txt
python -m app
```

`.env.example` documents every variable.

```bash
pytest -q
```

---

## Production deploy

Repo: [sterno874/MarkIt](https://github.com/sterno874/MarkIt)

| Path | Purpose |
|---|---|
| `/opt/markit/current` | App code (rsync’d on every `main` push) |
| `/var/lib/markit/data` | SQLite + bug ticket JSON (survives deploys) |
| `/etc/markit.env` | Written by CI from GitHub Secrets |
| `markit.service` | systemd unit |

**One-time on the host**

```bash
bash deploy/bootstrap-server.sh
```

**GitHub Secrets** (Settings → Secrets and variables → Actions)

| Secret | Required | Purpose |
|---|---|---|
| `DEPLOY_SSH_KEY` | yes | SSH key for the host |
| `DISCORD_TOKEN` | yes | Bot token |
| `DISCORD_GUILD_ID` | recommended | One or more server ids, comma-separated |
| `GEMINI_API_KEY` | no | Enables `/ask` |
| `GEMINI_MODEL` | no | Defaults to `gemini-3.8-flash` |
| `SEC_USER_AGENT` | no | Identify yourself to SEC EDGAR |

Push to `main` → Actions runs tests, writes `/etc/markit.env`, rsyncs code, recreates a uv-managed 3.13 venv, restarts `markit`.

---

## Bug tickets → autofix loop

1. `/bugs channel channel:#bugs`
2. Members file `/bug` or `/report-bug`
3. Each ticket lands in SQLite **and** `data/tickets/00042.json`
4. `/bugs pickup` claims open tickets and returns JSON an agent can consume
5. `/bugs resolve id:42 note:fixed …` closes the loop

---

## Project layout

```
app/
  bot.py              Discord client + ticker paste detection
  autocomplete.py     Slash autocomplete (Yahoo / OpenFIGI / watchlists)
  cogs/               Slash command groups
  market/             Quotes, charts, bonds/TRACE, filings, news…
  ui/                 Ticker + bond pills
  services/           Gemini, background workers
deploy/               systemd unit + host bootstrap
.github/workflows/    CI + deploy
```

---

## Contributing

`main` is protected:

- **Others** must open a **pull request** (no direct pushes to `main`)
- **Repo admins** (Matt) can still push straight to `main` for hotfixes / deploys
- Force-pushes to `main` are blocked

Fork → branch → PR is the default path for community changes.

## License / sharing

Built for private investing communities. Share the repo, fork it, or invite the hosted bot — whatever fits your desk.

Questions in Discord: `/help`  
Something broken: `/bug`
