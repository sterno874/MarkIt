from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from app.db import db
from app.market import charts, statements
from app.market.bonds import resolve_bond
from app.market.quotes import get_many, get_security
from app.market.sentiment import crypto_fear_greed, stock_fear_greed
from app.security import normalize_symbol
from app.services import gemini
from app.services.dispatch import run_blocking, send_function
from app.services.markit_nl import Intent, resolve_intent
from app.ui.bond_pill import BondPill
from app.ui.pill import TickerPill, simple_embed

EXAMPLE_PROMPTS = [
    "show me the chart on AAPL",
    "news for NVDA",
    "quote BTC",
    "earnings on MSFT",
    "compare AAPL and GOOGL over a year",
    "IHRT 8 3/8 May 2027",
    "fear and greed",
    "filings for TSLA",
]


class MarkIt(commands.Cog):
    """Natural-language front door — no need to memorize slash commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="markit",
        description="Ask in plain English — chart, news, quote, bond, compare…",
    )
    @app_commands.describe(request="e.g. show me the chart on AAPL · news for NVDA")
    async def markit_cmd(self, interaction: discord.Interaction, request: str) -> None:
        await interaction.response.defer()
        last = None
        if interaction.guild_id and interaction.channel_id:
            last = db.get_last_ticker(interaction.guild_id, interaction.channel_id)

        intent = await run_blocking(resolve_intent, request, last_ticker=last)
        try:
            await self._execute(interaction, intent, request)
        except Exception as exc:
            await interaction.followup.send(
                f"Couldn't run that: {exc}\n_Try `/help` or rephrase — e.g. `chart AAPL 3m`._",
                ephemeral=True,
            )

    @markit_cmd.autocomplete("request")
    async def markit_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        cur = (current or "").lower()
        return [
            app_commands.Choice(name=p[:100], value=p[:100])
            for p in EXAMPLE_PROMPTS
            if not cur or cur in p.lower()
        ][:25]

    async def _remember(self, interaction: discord.Interaction, symbol: str) -> None:
        if interaction.guild_id and interaction.channel_id and symbol:
            db.set_last_ticker(interaction.guild_id, interaction.channel_id, symbol)

    async def _execute(
        self,
        interaction: discord.Interaction,
        intent: Intent,
        original: str,
    ) -> None:
        action = intent.action

        if action == "help":
            await interaction.followup.send(
                embed=simple_embed(
                    "MarkIt · natural language",
                    "Just say what you want:\n"
                    "• `show me the chart on AAPL`\n"
                    "• `news for NVDA`\n"
                    "• `quote BTC`\n"
                    "• `compare AAPL MSFT over a year`\n"
                    "• `IHRT 8 3/8 May 2027`\n"
                    "• `fear and greed`\n\n"
                    "Or use the classic slash commands — `/help topic:commands`.",
                )
            )
            return

        if action == "ask":
            if not gemini.available():
                await interaction.followup.send(
                    "I couldn't map that to a desk command. Try "
                    "`chart AAPL`, `news NVDA`, or `/help`.",
                    ephemeral=True,
                )
                return
            context = f"Last ticker: {intent.symbol}" if intent.symbol else None
            answer = await run_blocking(
                gemini.ask, intent.query or original, context=context
            )
            await interaction.followup.send(embed=simple_embed("MarkIt", answer[:4000]))
            return

        if action == "fgi":
            stocks = await run_blocking(stock_fear_greed)
            crypto = await run_blocking(crypto_fear_greed)
            await interaction.followup.send(
                embed=simple_embed("Fear & Greed", stocks["text"] + "\n\n" + crypto["text"])
            )
            return

        if action == "heatmap":
            if not interaction.guild_id:
                await interaction.followup.send("Server only.", ephemeral=True)
                return
            rows = db.watch_list(guild_id=interaction.guild_id, server=True)
            tickers = [r["symbol"] for r in rows] or intent.symbols
            if not tickers:
                await interaction.followup.send(
                    "No watchlist yet — `/watch tickers:AAPL,MSFT server:True` or name some tickers.",
                    ephemeral=True,
                )
                return
            secs = await run_blocking(get_many, tickers[:30])
            pairs = [(s.yahoo, float(s.change_pct or 0)) for s in secs]
            buf = await run_blocking(charts.render_heatmap, pairs, "Watchlist movers")
            await interaction.followup.send(
                file=discord.File(buf, filename="heatmap.png")
            )
            return

        if action == "bond":
            query = intent.query or original
            quote = await resolve_bond(query)
            if interaction.guild_id and interaction.channel_id and quote.cusip:
                db.set_last_ticker(interaction.guild_id, interaction.channel_id, quote.cusip)
            await interaction.followup.send(view=BondPill(quote))
            return

        if action == "compare":
            parts = intent.symbols[:]
            if intent.symbol and intent.symbol not in parts:
                parts.insert(0, intent.symbol)
            if len(parts) < 2:
                await interaction.followup.send(
                    "Compare needs at least two tickers — e.g. `compare AAPL and MSFT`.",
                    ephemeral=True,
                )
                return
            buf = await run_blocking(charts.render_compare, parts[:8], intent.period)
            await interaction.followup.send(
                file=discord.File(buf, filename="compare.png")
            )
            return

        # Symbol-required actions below
        symbol = intent.symbol
        if not symbol:
            await interaction.followup.send(
                "Which ticker? e.g. `chart AAPL` or paste a symbol first.",
                ephemeral=True,
            )
            return

        symbol = normalize_symbol(symbol)
        await self._remember(interaction, symbol)

        if action == "chart":
            buf = await run_blocking(charts.render_chart, symbol, intent.period)
            await interaction.followup.send(
                file=discord.File(
                    buf,
                    filename=f"{symbol.replace('^', '').replace('=', '')}-chart.png",
                )
            )
            return

        if action == "quote":
            sec = await run_blocking(get_security, symbol)
            await self._remember(interaction, sec.yahoo)
            await interaction.followup.send(view=TickerPill(sec))
            return

        if action == "financials":
            data = await run_blocking(
                statements.financials, symbol, intent.statement, True
            )
            await interaction.followup.send(
                embed=simple_embed("FA · Financials", data["text"])
            )
            return

        # Map NL actions → Bloomberg-style function codes in dispatch
        fn_map = {
            "news": "cn",
            "holders": "phdc",
            "analysts": "anr",
            "earnings": "ern",
            "dividends": "dvd",
            "options": "opt",
            "short": "short",
            "filings": "sec",
            "congress": "congress",
        }
        fn = fn_map.get(action)
        if fn:
            await send_function(interaction, fn, symbol)
            return

        await interaction.followup.send(
            f"Not sure how to handle `{action}`. Try `/help` or rephrase.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MarkIt(bot))
