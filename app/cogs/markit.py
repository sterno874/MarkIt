from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from app import format as fmt
from app.db import db
from app.market import charts, statements
from app.market.bonds import resolve_bond
from app.market.quotes import get_many, get_security
from app.market.sentiment import crypto_fear_greed, stock_fear_greed
from app.security import normalize_symbol
from app.services import gemini, paper_pnl
from app.services.dispatch import run_blocking, send_function
from app.services.markit_nl import Intent, resolve_intent
from app.ui.bond_respond import send_bond_card
from app.ui.pill import TickerPill, simple_embed

EXAMPLE_PROMPTS = [
    "show me the chart on AAPL",
    "news for NVDA",
    "quote BTC",
    "paper buy 10 AAPL",
    "paper short NVDA",
    "my pnl",
    "server pnl",
    "leaderboard",
    "show open positions",
    "compare AAPL and GOOGL over a year",
    "IHRT 8 3/8 May 2027",
    "fear and greed",
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
                    "• `paper buy 10 AAPL` · `my pnl` · `leaderboard` · `server pnl`\n"
                    "• `compare AAPL MSFT over a year`\n"
                    "• `IHRT 8 3/8 May 2027`\n"
                    "• `fear and greed`\n\n"
                    "Or use the classic slash commands — `/help topic:commands`.",
                )
            )
            return

        if action.startswith("paper_"):
            await self._execute_paper(interaction, intent)
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
            import asyncio

            query = intent.query or original
            try:
                quote = await asyncio.wait_for(resolve_bond(query), timeout=45)
            except Exception as exc:
                await interaction.followup.send(
                    f"Could not resolve bond `{query}`: {exc}\n"
                    "_Try a full string like `IHRT 8 3/8 May 2027` or CUSIP `45174HBD8`._",
                    ephemeral=True,
                )
                return
            if interaction.guild_id and interaction.channel_id and quote.cusip:
                db.set_last_ticker(interaction.guild_id, interaction.channel_id, quote.cusip)
            await send_bond_card(interaction, quote)
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

    async def _execute_paper(
        self,
        interaction: discord.Interaction,
        intent: Intent,
    ) -> None:
        if not interaction.guild:
            await interaction.followup.send("Paper trading is server-only.", ephemeral=True)
            return

        action = intent.action
        guild_id = interaction.guild.id

        if action == "paper_leaderboard":
            book = await run_blocking(paper_pnl.build_server_book, guild_id)
            await interaction.followup.send(
                embed=simple_embed("Paper leaderboard", paper_pnl.format_leaderboard(book))
            )
            return

        if action == "paper_server":
            book = await run_blocking(paper_pnl.build_server_book, guild_id)
            await interaction.followup.send(
                embed=simple_embed("Server paper PnL", paper_pnl.format_server_summary(book))
            )
            return

        if action == "paper_pnl":
            uid = intent.trader_mention or interaction.user.id
            book = await run_blocking(paper_pnl.build_trader_book, guild_id, uid)
            member = interaction.guild.get_member(uid)
            name = member.display_name if member else str(uid)
            await interaction.followup.send(
                embed=simple_embed(
                    f"Paper PnL · {name}",
                    paper_pnl.format_trader(book, include_history=True, guild_id=guild_id),
                )
            )
            return

        if action == "paper_positions":
            if intent.server_wide:
                book = await run_blocking(paper_pnl.build_server_book, guild_id)
                text = paper_pnl.format_positions(
                    book.open_positions, title="Server open positions"
                )
            else:
                uid = intent.trader_mention or interaction.user.id
                tbook = await run_blocking(paper_pnl.build_trader_book, guild_id, uid)
                member = interaction.guild.get_member(uid)
                name = member.display_name if member else str(uid)
                text = paper_pnl.format_positions(tbook.positions, title=f"Open · {name}")
            await interaction.followup.send(embed=simple_embed("Paper positions", text))
            return

        if action == "paper_close":
            if intent.position_id is None:
                await interaction.followup.send(
                    "Which position? e.g. `close position #3`",
                    ephemeral=True,
                )
                return
            row = db.paper_get(intent.position_id, guild_id)
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
            sec = await run_blocking(get_security, row["symbol"])
            if sec.last is None:
                await interaction.followup.send("No last price to mark the close.", ephemeral=True)
                return
            closed = db.paper_close(
                intent.position_id,
                interaction.user.id,
                exit_price=float(sec.last),
                allow_any=is_mod and not is_owner,
            )
            if not closed:
                await interaction.followup.send("Could not close.", ephemeral=True)
                return
            await interaction.followup.send(
                embed=simple_embed(
                    f"Closed paper #{intent.position_id}",
                    f"<@{closed['user_id']}> {closed['side']} `{closed['symbol']}` "
                    f"x{closed['qty']} {fmt.number(closed['entry'])}→{fmt.number(closed['exit'])}\n"
                    f"Realized **{fmt.money(closed['pnl_dollars'])}** "
                    f"({fmt.pct(closed['pnl_pct'], already_percent=True)})",
                )
            )
            return

        if action in {"paper_buy", "paper_sell"}:
            if not intent.symbol:
                await interaction.followup.send(
                    "Which ticker? e.g. `paper buy 10 AAPL`",
                    ephemeral=True,
                )
                return
            sym = normalize_symbol(intent.symbol)
            sec = await run_blocking(get_security, sym)
            if sec.last is None:
                await interaction.followup.send("No last price.", ephemeral=True)
                return
            side = "long" if action == "paper_buy" else "short"
            qty = intent.qty if intent.qty > 0 else 1.0
            pid = db.paper_open(
                guild_id, interaction.user.id, sym, side, qty, sec.last
            )
            await self._remember(interaction, sym)
            await interaction.followup.send(
                embed=simple_embed(
                    f"Paper #{pid} booked",
                    f"<@{interaction.user.id}> {side} `{sym}` x{qty} @ {fmt.number(sec.last)}\n"
                    "Attributed to your book · try `my pnl` or `leaderboard`",
                )
            )
            return

        await interaction.followup.send(
            f"Unknown paper action `{action}`.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MarkIt(bot))
