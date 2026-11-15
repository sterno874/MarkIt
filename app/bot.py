from __future__ import annotations

import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

from app.config import GUILD_IDS
from app.db import db
from app.services.dispatch import send_function
from app.services.workers import DeskWorkers
from app.ui.pill import EXPAND_TEMPLATE, FN_TEMPLATE, REFRESH_TEMPLATE
from app.ui.ticker_respond import refresh_ticker_message, set_ticker_pill_expanded

log = logging.getLogger("market-desk")

COGS = [
    "app.cogs.help",
    "app.cogs.markit",
    "app.cogs.research",
    "app.cogs.alerts",
    "app.cogs.watchlist",
    "app.cogs.ideas",
    "app.cogs.desk",
    "app.cogs.ask",
    "app.cogs.bugs",
]


class FunctionButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=FN_TEMPLATE,
):
    def __init__(
        self,
        fn: str = "gp",
        symbol: str = "AAPL",
        expiry: str | None = None,
    ) -> None:
        custom_id = f"md:fn:{fn}:{symbol}"
        if expiry:
            custom_id = f"{custom_id}:{expiry}"
        super().__init__(
            discord.ui.Button(
                label=fn.upper(),
                style=discord.ButtonStyle.secondary,
                custom_id=custom_id,
            )
        )
        self.fn = fn
        self.symbol = symbol
        self.expiry = expiry

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
        /,
    ):
        return cls(
            fn=match.group("fn"),
            symbol=match.group("symbol"),
            expiry=match.groupdict().get("expiry"),
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        try:
            await send_function(
                interaction, self.fn, self.symbol, expiry=self.expiry
            )
        except Exception as exc:
            log.exception("function button %s %s failed", self.fn, self.symbol)
            await interaction.followup.send(
                f"Couldn't run `{self.fn}` on `{self.symbol}`: {exc}",
                ephemeral=True,
            )


class RefreshButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=REFRESH_TEMPLATE,
):
    """Manual IB-style tick — re-quote and flash last-tick direction."""

    def __init__(self, symbol: str = "AAPL") -> None:
        super().__init__(
            discord.ui.Button(
                label="Refresh",
                style=discord.ButtonStyle.success,
                custom_id=f"md:ref:{symbol}",
            )
        )
        self.symbol = symbol

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
        /,
    ):
        return cls(symbol=match.group("symbol"))

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        if not interaction.message:
            return
        row = db.live_pill_get(interaction.message.id)
        previous = float(row["last_price"]) if row and row["last_price"] is not None else None
        try:
            await refresh_ticker_message(
                interaction.message,
                self.symbol,
                previous_last=previous,
                extend_live=True,
            )
        except Exception as exc:
            await interaction.followup.send(f"Refresh failed: {exc}", ephemeral=True)


class ExpandButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=EXPAND_TEMPLATE,
):
    """Toggle collapsed ↔ expanded pill (tools + full stats)."""

    def __init__(self, symbol: str = "AAPL", state: str = "0") -> None:
        expanded = state == "1"
        super().__init__(
            discord.ui.Button(
                label="Collapse" if expanded else "Expand",
                style=discord.ButtonStyle.secondary if expanded else discord.ButtonStyle.primary,
                custom_id=f"md:xp:{state}:{symbol}",
            )
        )
        self.symbol = symbol
        # Current state in custom_id; click flips it.
        self.currently_expanded = expanded

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
        /,
    ):
        return cls(symbol=match.group("symbol"), state=match.group("state"))

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        if not interaction.message:
            return
        try:
            await set_ticker_pill_expanded(
                interaction.message,
                self.symbol,
                expanded=not self.currently_expanded,
            )
        except Exception as exc:
            await interaction.followup.send(f"Expand failed: {exc}", ephemeral=True)


class DeskBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = False
        super().__init__(command_prefix="!", intents=intents)
        self.workers: DeskWorkers | None = None

    async def setup_hook(self) -> None:
        self.add_dynamic_items(FunctionButton, RefreshButton, ExpandButton)
        for ext in COGS:
            await self.load_extension(ext)
        # Guild sync = instant in listed servers; global sync covers any other invites.
        # Skip guilds the bot isn't in yet (403 Missing Access) instead of crash-looping.
        if GUILD_IDS:
            for gid in GUILD_IDS:
                guild = discord.Object(id=gid)
                try:
                    self.tree.copy_global_to(guild=guild)
                    synced = await self.tree.sync(guild=guild)
                    log.info("Synced %s guild commands to %s", len(synced), gid)
                except discord.Forbidden:
                    log.warning(
                        "Cannot sync commands to guild %s yet — invite the bot there first",
                        gid,
                    )
                except discord.HTTPException as exc:
                    log.warning("Guild command sync failed for %s: %s", gid, exc)
        try:
            synced = await self.tree.sync()
            log.info("Synced %s global commands", len(synced))
        except discord.HTTPException as exc:
            log.warning("Global command sync failed: %s", exc)

        @self.tree.error
        async def on_app_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
            log.exception("command error: %s", error)
            msg = f"Error: {error.__cause__ or error}"
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(msg[:500], ephemeral=True)
                else:
                    await interaction.response.send_message(msg[:500], ephemeral=True)
            except discord.HTTPException:
                pass

        self.workers = DeskWorkers(self)
        self.workers.start()

    async def close(self) -> None:
        if self.workers:
            self.workers.stop()
        await super().close()

    async def on_ready(self) -> None:
        log.info("Logged in as %s (%s)", self.user, self.user and self.user.id)

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return

        # Chat desk only via @MarkIt …  (/markit slash stays raw, no ping needed)
        if self.user and self.user.mentioned_in(message):
            # Ignore @everyone / @here false-positives when bot isn't actually mentioned.
            if self.user not in message.mentions:
                await self.process_commands(message)
                return
            from app.cogs.markit import MarkIt, strip_bot_mentions

            request = strip_bot_mentions(message.content, self.user)
            cog = self.get_cog("MarkIt")
            if isinstance(cog, MarkIt):
                async with message.channel.typing():
                    await cog.handle_mention(message, request)
            return

        await self.process_commands(message)


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
