# Market Desk

A Discord research bot for investing communities — Bloomberg-style ticker pills, slash commands, alerts, trade ideas, and corporate bond TRACE quotes.

## What it does

- Paste `$AAPL`, `EURUSD`, `BTC`, `CL=F`, or `IHRT 8 3/8 May 2027` → rich card with links
- Slash commands with Bloomberg aliases (`/gp`, `/des`, `/fa`, `/cn`, `/phdc`, …)
- Alerts: price, %, trailing, date, insider, filings, earnings, dividends
- Server + personal watchlists, morning/close briefs, paper trades, idea cards
- `/ask` + @mention via Gemini (optional)
- `/bug` tickets → `data/tickets/NNNNN.json` for human or agent pickup

### Asset coverage

| Type | Examples | Source |
|---|---|---|
| Equities / ETFs | `AAPL`, `SPY`, `TLT` | Yahoo |
| Indices / rates | `SPX`, `VIX`, `TNX` | Yahoo |
| FX | `EURUSD`, `USDJPY` | Yahoo |
| Crypto | `BTC`, `ETH-USD` | Yahoo |
| Futures | `CL=F`, `GC=F`, `ES` | Yahoo |
| Options | `AAPL 275C 11/16/26` | Yahoo |
| **Corporate bonds** | `IHRT 8 3/8 May 2027`, CUSIP | OpenFIGI + **FINRA TRACE** |

## Setup (local)

1. Create a Discord application + bot at https://discord.com/developers/applications  
   Enable **Message Content Intent**.
2. Invite the bot with scopes `bot` + `applications.commands` and permissions to send messages / embeds / attach files.
3. Copy env and install:

```bash
cp .env.example .env
# edit DISCORD_TOKEN, optional DISCORD_GUILD_ID + GEMINI_API_KEY
uv venv --python 3.13 .venv
source .venv/bin/activate
uv pip install -r requirements.txt
python -m app
```

Set `DISCORD_GUILD_ID` to your server id so slash commands appear immediately.

## Production (Oracle VM, next to Research Desk)

Repo: [sterno874/MarkIt](https://github.com/sterno874/MarkIt)  
Host: same box as Research Desk (`129.80.137.103`)

| Path | Purpose |
|---|---|
| `/opt/markit/current` | App code (rsync’d on every `main` push) |
| `/var/lib/markit/data` | SQLite + bug ticket JSON (survives deploys) |
| `/etc/markit.env` | Secrets (`DISCORD_TOKEN`, optional Gemini key) |
| `markit.service` | systemd unit |

**One-time on the VM**

```bash
# from a checkout, or copy deploy/bootstrap-server.sh up
bash deploy/bootstrap-server.sh
sudo nano /etc/markit.env   # paste DISCORD_TOKEN
```

**GitHub**

1. Add repository secret `DEPLOY_SSH_KEY` (same private key Research Desk already uses).
2. Push to `main` → Actions runs pytest, rsyncs to `/opt/markit/current`, recreates the 3.13 venv with `uv`, restarts `markit`.

The VM’s system Python is 3.8; production always runs the uv-managed 3.13 venv.

## Commands

Type `/help` in Discord, or `/help topic:bonds`.

Useful starters:

```
/quote AAPL
/bond query:IHRT 8 3/8 May 2027
/chart NVDA period:3m
/alert price symbol:ASTS above:40
/watch AAPL,MSFT server:True
/idea long ASTS entry:28 stop:24 target:40
/bug description:chart blank for CL=F command:chart
/bugs pickup
```

## Bug tickets → autofix

1. `/bugs channel #bugs`
2. Members run `/bug …` or `/report-bug …`
3. Each ticket is stored in SQLite **and** written to `data/tickets/00042.json`
4. `/bugs pickup` claims open tickets and returns JSON an agent can consume
5. `/bugs resolve id:42 note:fixed …` closes the loop

## Notes

- Equity quotes are Yahoo-sourced (not a consolidated tape).
- Bond prices are FINRA TRACE **last sale** (percent of par) with YTM when available.
- Gemini is optional; without a key, everything else still runs.
