from __future__ import annotations

from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

from app.autocomplete import attach_symbol_autocomplete
from app.config import TZ
from app.db import db
from app.security import normalize_symbol
from app.ui.pill import simple_embed

AlertKind = Literal["price", "percent", "date", "insider", "filing", "earnings", "dividend", "trailing"]


class Alerts(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    alert = app_commands.Group(name="alert", description="Set price / event reminders")

    @alert.command(name="price", description="Ping when price crosses a level")
    async def alert_price(
        self,
        interaction: discord.Interaction,
        symbol: str,
        above: float | None = None,
        below: float | None = None,
        note: str | None = None,
    ) -> None:
        if above is None and below is None:
            await interaction.response.send_message("Pass `above` and/or `below`.", ephemeral=True)
            return
        await self._add(
            interaction,
            symbol,
            "price",
            {"above": above, "below": below},
            note,
        )

    @alert.command(name="percent", description="Ping on a % move from the current price")
    async def alert_percent(
        self,
        interaction: discord.Interaction,
        symbol: str,
        move: float,
        note: str | None = None,
    ) -> None:
        await self._add(interaction, symbol, "percent", {"move": abs(move)}, note)

    @alert.command(name="trailing", description="Trailing stop from the high since set")
    async def alert_trailing(
        self,
        interaction: discord.Interaction,
        symbol: str,
        trail_pct: float,
        note: str | None = None,
    ) -> None:
        await self._add(
            interaction,
            symbol,
            "trailing",
            {"trail_pct": abs(trail_pct), "high": None},
            note,
        )

    @alert.command(name="date", description="Calendar reminder (defaults to 09:30 ET)")
    async def alert_date(
        self,
        interaction: discord.Interaction,
        when: str,
        note: str,
        symbol: str | None = None,
    ) -> None:
        try:
            when_dt = _parse_when(when)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await self._add(
            interaction,
            symbol or "CAL",
            "date",
            {"when": when_dt.isoformat()},
            note,
        )

    @alert.command(name="insider", description="Open-market Form 4 buys over a $ minimum")
    async def alert_insider(
        self,
        interaction: discord.Interaction,
        symbol: str,
        min_value: float = 100_000.0,
        note: str | None = None,
    ) -> None:
        await self._add(interaction, symbol, "insider", {"min_value": min_value}, note)

    @alert.command(name="filing", description="SEC filing alert for watched forms")
    async def alert_filing(
        self,
        interaction: discord.Interaction,
        symbol: str,
        forms: str = "8-K,10-Q,10-K",
        note: str | None = None,
    ) -> None:
        form_list = [f.strip().upper() for f in forms.split(",") if f.strip()]
        await self._add(interaction, symbol, "filing", {"forms": form_list}, note)

    @alert.command(name="earnings", description="Remind the evening before earnings")
    async def alert_earnings(
        self,
        interaction: discord.Interaction,
        symbol: str,
        note: str | None = None,
    ) -> None:
        await self._add(interaction, symbol, "earnings", {}, note)

    @alert.command(name="dividend", description="Remind before the ex-dividend date")
    async def alert_dividend(
        self,
        interaction: discord.Interaction,
        symbol: str,
        note: str | None = None,
    ) -> None:
        await self._add(interaction, symbol, "dividend", {}, note)

    async def _add(
        self,
        interaction: discord.Interaction,
        symbol: str,
        kind: str,
        params: dict,
        note: str | None,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Server only.", ephemeral=True)
            return
        sym = symbol if symbol == "CAL" else normalize_symbol(symbol)
        alert_id = db.add_alert(
            guild_id=interaction.guild.id,
            channel_id=interaction.channel_id or 0,
            user_id=interaction.user.id,
            symbol=sym,
            kind=kind,
            params=params,
            note=note,
        )
        await interaction.response.send_message(
            f"Alert **#{alert_id}** set · `{kind}` on `{sym}`.",
            ephemeral=True,
        )

    @app_commands.command(name="alerts", description="List your active alerts")
    async def alerts_list(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Server only.", ephemeral=True)
            return
        rows = db.list_alerts(guild_id=interaction.guild.id, user_id=interaction.user.id)
        if not rows:
            await interaction.response.send_message("No active alerts.", ephemeral=True)
            return
        lines = [
            f"#{r['id']} `{r['kind']}` `{r['symbol']}` {r['params_json']}"
            + (f" — {r['note']}" if r["note"] else "")
            for r in rows
        ]
        await interaction.response.send_message(
            embed=simple_embed("Your alerts", "\n".join(lines)),
            ephemeral=True,
        )

    @app_commands.command(name="alert-cancel", description="Cancel one of your alerts")
    async def alert_cancel(
        self,
        interaction: discord.Interaction,
        id: app_commands.Range[int, 1, 1_000_000],
    ) -> None:
        row = db.get_alert(id)
        if not row or row["user_id"] != interaction.user.id:
            await interaction.response.send_message("Not found (or not yours).", ephemeral=True)
            return
        db.deactivate_alert(id)
        await interaction.response.send_message(f"Cancelled alert #{id}.", ephemeral=True)

    @app_commands.command(name="alerts-channel", description="Set the shared alerts channel")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def alerts_channel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ) -> None:
        if not interaction.guild:
            return
        db.set_setting(interaction.guild.id, "alerts_channel_id", str(channel.id))
        await interaction.response.send_message(
            f"Alerts can also post in {channel.mention}.",
            ephemeral=True,
        )


def _parse_when(text: str) -> datetime:
    text = text.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d", "%m/%d/%Y %H:%M", "%m/%d/%Y"):
        try:
            dt = datetime.strptime(text, fmt)
            if fmt in {"%Y-%m-%d", "%m/%d/%Y"}:
                dt = dt.replace(hour=9, minute=30)
            return dt.replace(tzinfo=TZ)
        except ValueError:
            continue
    raise ValueError("Use `YYYY-MM-DD` or `YYYY-MM-DD HH:MM` (ET).")


async def setup(bot: commands.Bot) -> None:
    cog = Alerts(bot)
    await bot.add_cog(cog)
    for cmd in (
        cog.alert_price,
        cog.alert_percent,
        cog.alert_trailing,
        cog.alert_date,
        cog.alert_insider,
        cog.alert_filing,
        cog.alert_earnings,
        cog.alert_dividend,
    ):
        attach_symbol_autocomplete(cmd, "symbol")
