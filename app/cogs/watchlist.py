from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from app.db import db
from app.security import normalize_symbol
from app.ui.pill import simple_embed


class Watchlist(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="watch", description="Add tickers to your or the server watchlist")
    async def watch(
        self,
        interaction: discord.Interaction,
        tickers: str,
        tag: str | None = None,
        server: bool = False,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Server only.", ephemeral=True)
            return
        symbols = [normalize_symbol(s) for s in tickers.replace(",", " ").split() if s.strip()]
        for sym in symbols:
            db.watch_add(
                guild_id=interaction.guild.id,
                symbol=sym,
                user_id=None if server else interaction.user.id,
                tag=tag,
            )
        scope = "server" if server else "personal"
        await interaction.response.send_message(
            f"Watching {', '.join(f'`{s}`' for s in symbols)} ({scope}).",
            ephemeral=True,
        )

    @app_commands.command(name="unwatch", description="Remove from a watchlist")
    async def unwatch(
        self,
        interaction: discord.Interaction,
        ticker: str | None = None,
        tag: str | None = None,
        server: bool = False,
        all: bool = False,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Server only.", ephemeral=True)
            return
        n = db.watch_remove(
            guild_id=interaction.guild.id,
            symbol=normalize_symbol(ticker) if ticker else None,
            user_id=None if server else interaction.user.id,
            tag=tag,
            clear_all=all,
        )
        await interaction.response.send_message(f"Removed {n} entr(y/ies).", ephemeral=True)

    @app_commands.command(name="watchlist", description="Show a watchlist")
    async def watchlist(
        self,
        interaction: discord.Interaction,
        server: bool = False,
        tag: str | None = None,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Server only.", ephemeral=True)
            return
        rows = db.watch_list(
            guild_id=interaction.guild.id,
            user_id=None if server else interaction.user.id,
            tag=tag,
            server=server,
        )
        if not rows:
            await interaction.response.send_message("Empty watchlist.", ephemeral=True)
            return
        lines = [
            f"`{r['symbol']}`" + (f" · {r['tag']}" if r["tag"] else "")
            for r in rows
        ]
        title = "Server watchlist" if server else "Your watchlist"
        await interaction.response.send_message(
            embed=simple_embed(title, "\n".join(lines)),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Watchlist(bot))
