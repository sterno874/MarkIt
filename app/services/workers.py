from __future__ import annotations

import json
import logging
from datetime import datetime

import discord
from discord.ext import tasks

from app import format as fmt
from app.config import CLOSE_HHMM, MORNING_HHMM, TZ
from app.cogs.desk import build_brief
from app.db import db
from app.market import filings, statements
from app.market.quotes import get_security
from app.services.dispatch import run_blocking

log = logging.getLogger("market-desk.workers")


class DeskWorkers:
    def __init__(self, bot: discord.Client) -> None:
        self.bot = bot

    def start(self) -> None:
        self.poll_alerts.start()
        self.poll_briefs.start()

    def stop(self) -> None:
        self.poll_alerts.cancel()
        self.poll_briefs.cancel()

    @tasks.loop(seconds=60)
    async def poll_alerts(self) -> None:
        for row in db.list_alerts(active_only=True):
            try:
                await self._check_alert(row)
            except Exception:
                log.exception("alert %s failed", row["id"])

    @poll_alerts.before_loop
    async def _wait_ready_alerts(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=1)
    async def poll_briefs(self) -> None:
        now = datetime.now(TZ)
        hhmm = now.strftime("%H:%M")
        day = now.strftime("%Y-%m-%d")
        for guild in self.bot.guilds:
            channel_id = db.get_setting(guild.id, "brief_channel_id")
            if not channel_id:
                continue
            channel = guild.get_channel(int(channel_id))
            if not isinstance(channel, discord.TextChannel):
                continue
            if (
                hhmm == MORNING_HHMM
                and db.get_setting(guild.id, "brief_morning", "1") == "1"
                and db.schedule_get(f"morning:{guild.id}") != day
            ):
                text = await run_blocking(build_brief, guild.id, "morning")
                await channel.send(embed=discord.Embed(title="Morning brief", description=text[:4000], colour=0x3498DB))
                db.schedule_set(f"morning:{guild.id}", day)
            if (
                hhmm == CLOSE_HHMM
                and db.get_setting(guild.id, "brief_close", "1") == "1"
                and db.schedule_get(f"close:{guild.id}") != day
            ):
                text = await run_blocking(build_brief, guild.id, "close")
                await channel.send(embed=discord.Embed(title="Close brief", description=text[:4000], colour=0x9B59B6))
                db.schedule_set(f"close:{guild.id}", day)

    @poll_briefs.before_loop
    async def _wait_ready_briefs(self) -> None:
        await self.bot.wait_until_ready()

    async def _check_alert(self, row) -> None:  # type: ignore[no-untyped-def]
        kind = row["kind"]
        params = json.loads(row["params_json"] or "{}")
        symbol = row["symbol"]
        fired = False
        body = ""

        if kind == "date":
            when = datetime.fromisoformat(params["when"])
            now = datetime.now(TZ)
            if now >= when and (not row["last_fired_at"]):
                fired = True
                body = f"📅 Reminder: {row['note'] or symbol}"
        elif kind in {"price", "percent", "trailing"}:
            if symbol == "CAL":
                return
            sec = await run_blocking(get_security, symbol)
            if sec.last is None:
                return
            if kind == "price":
                if params.get("above") is not None and sec.last >= params["above"]:
                    fired = True
                    body = f"`{symbol}` at {fmt.number(sec.last)} ≥ {params['above']}"
                if params.get("below") is not None and sec.last <= params["below"]:
                    fired = True
                    body = f"`{symbol}` at {fmt.number(sec.last)} ≤ {params['below']}"
            elif kind == "percent":
                # Store baseline on first check
                if params.get("baseline") is None:
                    params["baseline"] = sec.last
                    with db.connect() as conn:
                        conn.execute(
                            "UPDATE alerts SET params_json = ? WHERE id = ?",
                            (json.dumps(params), row["id"]),
                        )
                    return
                move = (sec.last - params["baseline"]) / params["baseline"] * 100
                if abs(move) >= float(params["move"]):
                    fired = True
                    body = f"`{symbol}` moved {fmt.pct(move, already_percent=True)} from {fmt.number(params['baseline'])}"
            elif kind == "trailing":
                high = params.get("high") or sec.last
                high = max(float(high), float(sec.last))
                params["high"] = high
                with db.connect() as conn:
                    conn.execute(
                        "UPDATE alerts SET params_json = ? WHERE id = ?",
                        (json.dumps(params), row["id"]),
                    )
                stop = high * (1 - float(params["trail_pct"]) / 100)
                if sec.last <= stop:
                    fired = True
                    body = (
                        f"`{symbol}` hit trailing stop {fmt.number(stop)} "
                        f"(high {fmt.number(high)}, trail {params['trail_pct']}%)"
                    )
        elif kind == "insider":
            data = await run_blocking(statements.holders, symbol)
            # Naive: fire once per day if purchases summary mentions buys — better: parse transactions.
            text = data["text"].lower()
            if "purchase" in text or "buy" in text:
                key = f"insider:{row['id']}:{datetime.now(TZ).date()}"
                if db.schedule_get(key) != "1":
                    fired = True
                    body = f"Insider activity update for `{symbol}`\n{data['text'][:800]}"
                    db.schedule_set(key, "1")
        elif kind == "filing":
            forms = params.get("forms") or ["8-K", "10-Q", "10-K"]
            data = await run_blocking(filings.recent_filings, symbol, forms, 5)
            for filing in data["filings"]:
                if not db.filing_seen(filing["accession"]):
                    db.mark_filing(filing["accession"], symbol)
                    fired = True
                    body = (
                        f"New `{filing['form']}` for `{symbol}` on {filing['filed']}\n"
                        f"{filing['url']}"
                    )
                    break
        elif kind in {"earnings", "dividend"}:
            data = await run_blocking(statements.earnings, symbol)
            cal = data.get("calendar") or {}
            key = f"{kind}:{row['id']}:{datetime.now(TZ).date()}"
            if db.schedule_get(key) == "1":
                return
            if kind == "earnings" and cal.get("Earnings Date"):
                # Fire the calendar day before if we can parse; else surface weekly.
                fired = True
                body = f"Earnings watch `{symbol}`\n{data['text'][:900]}"
                db.schedule_set(key, "1")
            if kind == "dividend" and (cal.get("Ex-Dividend Date") or cal.get("Dividend Date")):
                fired = True
                body = f"Dividend watch `{symbol}`\n{data['text'][:900]}"
                db.schedule_set(key, "1")

        if not fired:
            return

        if row["note"] and row["note"] not in body:
            body = f"{body}\n_{row['note']}_"

        user = self.bot.get_user(row["user_id"]) or await self.bot.fetch_user(row["user_id"])
        embed = discord.Embed(title=f"Alert #{row['id']}", description=body[:4000], colour=0xF1C40F)
        try:
            await user.send(embed=embed)
        except discord.HTTPException:
            pass

        guild = self.bot.get_guild(row["guild_id"])
        if guild:
            alerts_channel_id = db.get_setting(guild.id, "alerts_channel_id")
            channel = guild.get_channel(int(alerts_channel_id)) if alerts_channel_id else None
            if isinstance(channel, discord.TextChannel):
                await channel.send(content=f"<@{row['user_id']}>", embed=embed)

        # One-shot for price/percent/date/trailing; keep filing/insider/earnings rolling.
        if kind in {"price", "percent", "date", "trailing"}:
            db.deactivate_alert(row["id"])
        db.mark_alert_fired(row["id"])
