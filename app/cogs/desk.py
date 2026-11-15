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

    @app_commands.command(
        name="paper",
        description="Paper trade desk — buy/sell/close + PnL attribution",
    )
    @app_commands.describe(
        action="buy, sell, close, positions, pnl, leaderboard, or server",
        symbol="Ticker for buy/sell",
        qty="Share/contract count",
        position_id="Open position id to close",
        trader="Whose book to show (pnl / positions)",
        server_wide="Show everyone's open positions",
        note="Optional note on the fill",
    )
    async def paper(
        self,
        interaction: discord.Interaction,
        action: Literal[
            "buy", "sell", "close", "positions", "pnl", "leaderboard", "server"
        ],
        symbol: str | None = None,
        qty: float = 1.0,
        position_id: int | None = None,
        trader: discord.Member | None = None,
        server_wide: bool = False,
        note: str | None = None,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Server only.", ephemeral=True)
            return

        from app.services import paper_pnl

        if action == "leaderboard":
            await interaction.response.defer()
            book = await run_blocking(paper_pnl.build_server_book, interaction.guild.id)
            await interaction.followup.send(
                embed=simple_embed("Paper leaderboard", paper_pnl.format_leaderboard(book))
            )
            return

        if action == "server":
            await interaction.response.defer()
            book = await run_blocking(paper_pnl.build_server_book, interaction.guild.id)
            await interaction.followup.send(
                embed=simple_embed("Server paper PnL", paper_pnl.format_server_summary(book))
            )
            return

        if action == "pnl":
            await interaction.response.defer()
            target = trader or interaction.user
            book = await run_blocking(
                paper_pnl.build_trader_book, interaction.guild.id, target.id
            )
            await interaction.followup.send(
                embed=simple_embed(
                    f"Paper PnL · {target.display_name}",
                    paper_pnl.format_trader(
                        book, include_history=True, guild_id=interaction.guild.id
                    ),
                )
            )
            return

        if action == "positions":
            await interaction.response.defer(ephemeral=not server_wide and trader is None)
            if server_wide:
                book = await run_blocking(paper_pnl.build_server_book, interaction.guild.id)
                text = paper_pnl.format_positions(
                    book.open_positions, title="Server open positions"
                )
            else:
                target = trader or interaction.user
                tbook = await run_blocking(
                    paper_pnl.build_trader_book, interaction.guild.id, target.id
                )
                text = paper_pnl.format_positions(
                    tbook.positions, title=f"Open · {target.display_name}"
                )
            await interaction.followup.send(embed=simple_embed("Paper positions", text))
            return

        if action == "close":
            if position_id is None:
                await interaction.response.send_message(
                    "Pass `position_id` to close (see `/paper action:positions`).",
                    ephemeral=True,
                )
                return
            await interaction.response.defer()
            row = db.paper_get(position_id, interaction.guild.id)
            if not row:
                await interaction.followup.send("Position not found.", ephemeral=True)
                return
            is_owner = row["user_id"] == interaction.user.id
            is_mod = isinstance(interaction.user, discord.Member) and (
                interaction.user.guild_permissions.manage_messages
            )
            if not is_owner and not is_mod:
                await interaction.followup.send(
                    "Only the trader (or a mod) can close that position.",
                    ephemeral=True,
                )
                return
            try:
                sec = await run_blocking(get_security, row["symbol"])
                exit_px = sec.last
            except Exception:
                exit_px = None
            if exit_px is None:
                await interaction.followup.send("No last price to mark the close.", ephemeral=True)
                return
            closed = db.paper_close(
                position_id,
                interaction.user.id,
                exit_price=float(exit_px),
                allow_any=is_mod and not is_owner,
            )
            if not closed:
                await interaction.followup.send("Could not close position.", ephemeral=True)
                return
            await interaction.followup.send(
                embed=simple_embed(
                    f"Closed paper #{position_id}",
                    f"<@{closed['user_id']}> {closed['side']} `{closed['symbol']}` "
                    f"x{closed['qty']} {fmt.number(closed['entry'])}→{fmt.number(closed['exit'])}\n"
                    f"Realized **{fmt.money(closed['pnl_dollars'])}** "
                    f"({fmt.pct(closed['pnl_pct'], already_percent=True)})",
                )
            )
            return

        if action in {"buy", "sell"}:
            if not symbol:
                await interaction.response.send_message("Pass a symbol.", ephemeral=True)
                return
            await interaction.response.defer()
            sym = normalize_symbol(symbol)
            sec = await run_blocking(get_security, sym)
            if sec.last is None:
                await interaction.followup.send("No last price.", ephemeral=True)
                return
            side = "long" if action == "buy" else "short"
            pid = db.paper_open(
                interaction.guild.id,
                interaction.user.id,
                sym,
                side,
                qty,
                sec.last,
                note=note,
            )
            await interaction.followup.send(
                embed=simple_embed(
                    f"Paper #{pid} booked",
                    f"<@{interaction.user.id}> {side} `{sym}` x{qty} @ {fmt.number(sec.last)}"
                    + (f"\n_{note}_" if note else "")
                    + "\nAttributed to your book · `/paper action:pnl` · `/paper action:leaderboard`",
                )
            )
            return

    @app_commands.command(
        name="leaderboard",
        description="Paper trading PnL leaderboard for this server",
    )
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Server only.", ephemeral=True)
            return
        from app.services import paper_pnl

        await interaction.response.defer()
        book = await run_blocking(paper_pnl.build_server_book, interaction.guild.id)
        await interaction.followup.send(
            embed=simple_embed("Paper leaderboard", paper_pnl.format_leaderboard(book))
        )

    @app_commands.command(name="pnl", description="Your (or another trader's) paper PnL")
    @app_commands.describe(trader="Defaults to you")
    async def pnl_cmd(
        self,
        interaction: discord.Interaction,
        trader: discord.Member | None = None,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Server only.", ephemeral=True)
            return
        from app.services import paper_pnl

        await interaction.response.defer()
        target = trader or interaction.user
        book = await run_blocking(
            paper_pnl.build_trader_book, interaction.guild.id, target.id
        )
        await interaction.followup.send(
            embed=simple_embed(
                f"Paper PnL · {target.display_name}",
                paper_pnl.format_trader(
                    book, include_history=True, guild_id=interaction.guild.id
                ),
            )
        )


async def setup(bot: commands.Bot) -> None:
    cog = Desk(bot)
    await bot.add_cog(cog)
    attach_symbol_autocomplete(cog.paper, "symbol")
