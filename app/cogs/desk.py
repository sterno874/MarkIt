from __future__ import annotations

from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from app import format as fmt
from app.autocomplete import attach_symbol_autocomplete
from app.db import db
from app.market.quotes import get_many, get_security
from app.security import normalize_symbol
from app.services.dispatch import run_blocking
from app.ui.pill import simple_embed

INDEX_SET = ["^GSPC", "^IXIC", "^DJI", "^VIX", "^TNX", "DX-Y.NYB", "GC=F", "CL=F"]


def build_brief(guild_id: int, kind: str) -> str:
    secs = get_many(INDEX_SET)
    lines = [f"**{kind.title()} brief**", ""]
    for s in secs:
        lines.append(
            f"`{s.yahoo}` {fmt.number(s.last)} {fmt.pct(s.change_pct, already_percent=True)}"
        )
    if guild_id:
        watch = db.watch_list(guild_id=guild_id, server=True)
        if watch:
            lines.append("")
            lines.append("**Watchlist**")
            wsecs = get_many([r["symbol"] for r in watch[:15]])
            for s in wsecs:
                lines.append(
                    f"`{s.yahoo}` {fmt.number(s.last)} {fmt.pct(s.change_pct, already_percent=True)}"
                )
    return "\n".join(lines)


class Desk(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="brief", description="Morning or close market brief")
    @app_commands.describe(kind="morning or close")
    async def brief(
        self,
        interaction: discord.Interaction,
        kind: Literal["morning", "close"] = "morning",
    ) -> None:
        await interaction.response.defer()
        text = await run_blocking(build_brief, interaction.guild_id or 0, kind)
        await interaction.followup.send(embed=simple_embed(f"{kind.title()} brief", text))

    @app_commands.command(name="board", description="Quote board for the server watchlist")
    async def board(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Server only.", ephemeral=True)
            return
        await interaction.response.defer()
        rows = db.watch_list(guild_id=interaction.guild.id, server=True)
        symbols = [r["symbol"] for r in rows] or INDEX_SET[:4]
        secs = await run_blocking(get_many, symbols[:25])
        lines = [
            f"`{s.yahoo}` {fmt.number(s.last)} {fmt.pct(s.change_pct, already_percent=True)} · {s.asset_label}"
            for s in secs
        ]
        await interaction.followup.send(embed=simple_embed("Board", "\n".join(lines)))

    @app_commands.command(name="schedule", description="Auto-post morning/close briefs to a channel")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def schedule(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        morning: bool = True,
        close: bool = True,
    ) -> None:
        if not interaction.guild:
            return
        db.set_setting(interaction.guild.id, "brief_channel_id", str(channel.id))
        db.set_setting(interaction.guild.id, "brief_morning", "1" if morning else "0")
        db.set_setting(interaction.guild.id, "brief_close", "1" if close else "0")
        await interaction.response.send_message(
            f"Briefs → {channel.mention} (morning={morning}, close={close}).",
            ephemeral=True,
        )

    @app_commands.command(name="paper", description="Paper buy/sell/positions/close")
    @app_commands.describe(action="buy, sell, positions, or close")
    async def paper(
        self,
        interaction: discord.Interaction,
        action: Literal["buy", "sell", "positions", "close"],
        symbol: str | None = None,
        qty: float = 1.0,
        position_id: int | None = None,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Server only.", ephemeral=True)
            return

        if action == "positions":
            rows = db.paper_list(interaction.guild.id, interaction.user.id)
            if not rows:
                await interaction.response.send_message("No open paper positions.", ephemeral=True)
                return
            lines = []
            for r in rows:
                try:
                    last = (await run_blocking(get_security, r["symbol"])).last
                except Exception:
                    last = None
                pnl = None
                if last is not None:
                    raw = (last - r["entry"]) / r["entry"] * 100
                    pnl = raw if r["side"] == "long" else -raw
                lines.append(
                    f"#{r['id']} {r['side']} `{r['symbol']}` x{r['qty']} @ {fmt.number(r['entry'])} "
                    f"→ {fmt.number(last)} ({fmt.pct(pnl, already_percent=True)})"
                )
            await interaction.response.send_message(
                embed=simple_embed("Paper positions", "\n".join(lines)),
                ephemeral=True,
            )
            return

        if action == "close":
            if position_id is None:
                await interaction.response.send_message("Pass `position_id` to close.", ephemeral=True)
                return
            row = db.paper_close(position_id, interaction.user.id)
            if not row:
                await interaction.response.send_message("Position not found.", ephemeral=True)
                return
            await interaction.response.send_message(f"Closed paper #{position_id}.", ephemeral=True)
            return

        if not symbol:
            await interaction.response.send_message("Pass a symbol.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        sym = normalize_symbol(symbol)
        sec = await run_blocking(get_security, sym)
        if sec.last is None:
            await interaction.followup.send("No last price.", ephemeral=True)
            return
        side = "long" if action == "buy" else "short"
        pid = db.paper_open(interaction.guild.id, interaction.user.id, sym, side, qty, sec.last)
        await interaction.followup.send(
            f"Paper #{pid}: {side} `{sym}` x{qty} @ {fmt.number(sec.last)}",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    cog = Desk(bot)
    await bot.add_cog(cog)
    attach_symbol_autocomplete(cog.paper, "symbol")
