from __future__ import annotations

from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from app import format as fmt
from app.autocomplete import attach_symbol_autocomplete
from app.db import db
from app.market.quotes import get_security
from app.security import normalize_symbol
from app.services.dispatch import run_blocking
from app.ui.pill import simple_embed


class Ideas(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="idea", description="Post a structured trade idea card")
    async def idea(
        self,
        interaction: discord.Interaction,
        side: Literal["long", "short"],
        symbol: str,
        entry: float | None = None,
        stop: float | None = None,
        target: float | None = None,
        note: str | None = None,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Server only.", ephemeral=True)
            return
        await interaction.response.defer()
        sym = normalize_symbol(symbol)
        try:
            sec = await run_blocking(get_security, sym)
            last = sec.last
        except Exception:
            last = None
        idea_id = db.idea_create(
            guild_id=interaction.guild.id,
            channel_id=interaction.channel_id or 0,
            message_id=None,
            user_id=interaction.user.id,
            symbol=sym,
            side=side,
            entry=entry if entry is not None else last,
            stop=stop,
            target=target,
            note=note,
        )
        embed = simple_embed(
            f"Idea #{idea_id} · {side.upper()} {sym}",
            "\n".join(
                [
                    f"**By** <@{interaction.user.id}>",
                    f"Entry `{fmt.number(entry if entry is not None else last)}` · "
                    f"Stop `{fmt.number(stop)}` · Target `{fmt.number(target)}`",
                    f"Last `{fmt.number(last)}`" if last is not None else "",
                    note or "",
                ]
            ),
            colour=0x2ECC71 if side == "long" else 0xE74C3C,
        )
        msg = await interaction.followup.send(embed=embed)
        if hasattr(msg, "id"):
            db.idea_set_message(idea_id, msg.id)

    @app_commands.command(name="ideas", description="List open trade ideas")
    async def ideas(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Server only.", ephemeral=True)
            return
        rows = db.idea_list(interaction.guild.id, status="open")
        if not rows:
            await interaction.response.send_message("No open ideas.", ephemeral=True)
            return
        lines = [
            f"#{r['id']} {r['side'].upper()} `{r['symbol']}` entry {fmt.number(r['entry'])} "
            f"stop {fmt.number(r['stop'])} tgt {fmt.number(r['target'])}"
            for r in rows
        ]
        await interaction.response.send_message(embed=simple_embed("Open ideas", "\n".join(lines)))

    @app_commands.command(name="idea-close", description="Close an idea with an exit price")
    async def idea_close(
        self,
        interaction: discord.Interaction,
        id: app_commands.Range[int, 1, 1_000_000],
        exit: float | None = None,
    ) -> None:
        row = db.idea_get(id)
        if not row or (interaction.guild and row["guild_id"] != interaction.guild.id):
            await interaction.response.send_message("Idea not found.", ephemeral=True)
            return
        if row["user_id"] != interaction.user.id and not (
            isinstance(interaction.user, discord.Member)
            and interaction.user.guild_permissions.manage_messages
        ):
            await interaction.response.send_message("Only the author (or a mod) can close it.", ephemeral=True)
            return
        exit_px = exit
        if exit_px is None:
            try:
                exit_px = (await run_blocking(get_security, row["symbol"])).last
            except Exception:
                exit_px = None
        pnl = None
        if exit_px is not None and row["entry"]:
            raw = (exit_px - row["entry"]) / row["entry"] * 100
            pnl = raw if row["side"] == "long" else -raw
        db.idea_close(id, exit_px, pnl)
        await interaction.response.send_message(
            f"Closed idea #{id} @ {fmt.number(exit_px)} · P&L {fmt.pct(pnl, already_percent=True)}"
        )


async def setup(bot: commands.Bot) -> None:
    cog = Ideas(bot)
    await bot.add_cog(cog)
    attach_symbol_autocomplete(cog.idea, "symbol")
