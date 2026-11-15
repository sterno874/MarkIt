from __future__ import annotations

import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

from app.config import GUILD_IDS
from app.db import db
from app.market.bonds import looks_like_bond_query, resolve_bond
from app.market.quotes import get_security
from app.security import extract_tickers
from app.services.dispatch import run_blocking, send_function
from app.services.workers import DeskWorkers
from app.ui.bond_pill import BondPill
from app.ui.pill import FN_TEMPLATE, TickerPill
from app.services import gemini

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
    def __init__(self, fn: str = "gp", symbol: str = "AAPL") -> None:
        super().__init__(
            discord.ui.Button(
                label=fn.upper(),
                style=discord.ButtonStyle.secondary,
                custom_id=f"md:fn:{fn}:{symbol}",
            )
        )
        self.fn = fn
        self.symbol = symbol

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
        /,
    ):
        return cls(fn=match.group("fn"), symbol=match.group("symbol"))

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        await send_function(interaction, self.fn, self.symbol)


class DeskBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = False
        super().__init__(command_prefix="!", intents=intents)
        self.workers: DeskWorkers | None = None

    async def setup_hook(self) -> None:
        self.add_dynamic_items(FunctionButton)
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

        # @mention → Gemini ask
        if self.user and self.user.mentioned_in(message) and gemini.available():
            question = message.content
            for mention in message.mentions:
                question = question.replace(f"<@{mention.id}>", "").replace(f"<@!{mention.id}>", "")
            question = question.strip()
            if question:
                async with message.channel.typing():
                    try:
                        last = db.get_last_ticker(message.guild.id, message.channel.id)
                        answer = await run_blocking(
                            gemini.ask,
                            question,
                            context=f"Last ticker: {last}" if last else None,
                        )
                        await message.reply(answer[:1900], mention_author=False)
                    except Exception as exc:
                        await message.reply(f"Gemini error: {exc}", mention_author=False)
                return

        content = message.content.strip()
        if not content or content.startswith("/") or content.startswith("!"):
            await self.process_commands(message)
            return

        # Full-message bond query
        if looks_like_bond_query(content) and (
            " " in content or re.fullmatch(r"[0-9A-Za-z]{9}", content)
        ):
            try:
                async with message.channel.typing():
                    bond = await resolve_bond(content)
                if bond.cusip:
                    db.set_last_ticker(message.guild.id, message.channel.id, bond.cusip)
                await message.channel.send(view=BondPill(bond))
            except Exception as exc:
                log.info("bond resolve failed for %r: %s", content, exc)
            return

        tickers = extract_tickers(content, limit=2)
        if not tickers:
            await self.process_commands(message)
            return

        # Avoid firing on long prose unless $TICKER is used
        if "$" not in content and not re.fullmatch(r"[\$]?[A-Za-z^][A-Za-z0-9.\-=/]{0,24}", content):
            await self.process_commands(message)
            return

        for symbol in tickers:
            try:
                async with message.channel.typing():
                    sec = await run_blocking(get_security, symbol)
                db.set_last_ticker(message.guild.id, message.channel.id, sec.yahoo)
                await message.channel.send(view=TickerPill(sec))
            except Exception as exc:
                log.info("quote failed for %s: %s", symbol, exc)

        await self.process_commands(message)


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
