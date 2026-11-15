from __future__ import annotations

import re

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
from app.services.desk_ctx import DeskCtx
from app.services.dispatch import run_blocking, send_function
from app.services.markit_nl import Intent, resolve_intent
from app.ui.bond_respond import send_bond_card
from app.ui.pill import simple_embed
from app.ui.ticker_respond import publish_ticker_pill

EXAMPLE_PROMPTS = [
    "show me apples volume for the past week",
    "show me the chart on AAPL",
    "pill for Tesla",
    "filings for MSFT",
    "news for NVDA",
    "quote BTC",
    "paper buy 10 AAPL",
    "my pnl",
    "leaderboard",
    "compare AAPL and GOOGL over a year",
    "IHRT 8 3/8 May 2027",
    "fear and greed",
]

HELP_BLURB = (
    "Ping me to run the desk:\n"
    "• `@MarkIt AAPL` → quote pill\n"
    "• `@MarkIt chart NVDA 3m` → price chart\n"
    "• `@MarkIt apples volume past week` → volume chart\n"
    "• `@MarkIt filings MSFT` · `@MarkIt news TSLA`\n\n"
    "Or use the raw slash command `/markit …` (no ping needed)."
)


def strip_bot_mentions(content: str, bot_user: discord.ClientUser | discord.User) -> str:
    text = content or ""
    text = text.replace(f"<@{bot_user.id}>", " ").replace(f"<@!{bot_user.id}>", " ")
    # Nickname form / leftover @MarkIt text
    text = re.sub(r"@MarkIt\b", " ", text, flags=re.I)
    return " ".join(text.split()).strip()


class MarkIt(commands.Cog):
    """Desk front door — `/markit` slash (raw) or `@MarkIt …` in chat."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="markit",
        description="Ask in plain English — chart, news, quote, bond, compare…",
    )
    @app_commands.describe(request="e.g. show me the chart on AAPL · news for NVDA")
    async def markit_cmd(self, interaction: discord.Interaction, request: str) -> None:
        await interaction.response.defer()
        ctx = DeskCtx.from_interaction(interaction)
        try:
            await self.run_request(ctx, request)
        except Exception as exc:
            await ctx.send(
                f"Couldn't run that: {exc}\n_Try `/markit chart AAPL 3m` or `@MarkIt AAPL`._",
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

    async def handle_mention(self, message: discord.Message, request: str) -> None:
        """Chat path: `@MarkIt AAPL` / `@MarkIt chart NVDA`."""
        ctx = DeskCtx.from_message(message)
        if not request:
            await ctx.send(embed=simple_embed("MarkIt", HELP_BLURB))
            return
        # Allow `@MarkIt /quote AAPL` style — strip leading slash command noise.
        request = re.sub(r"^/+", "", request).strip()
        try:
            await self.run_request(ctx, request)
        except Exception as exc:
            await ctx.send(
                f"Couldn't run that: {exc}\n_Try `@MarkIt AAPL` or `/markit chart AAPL`._"
            )

    async def run_request(self, ctx: DeskCtx, request: str) -> None:
        last = None
        if ctx.guild_id and ctx.channel_id:
            last = db.get_last_ticker(ctx.guild_id, ctx.channel_id)
        intent = await run_blocking(resolve_intent, request, last_ticker=last)
        await self._execute(ctx, intent, request)

    async def _remember(self, ctx: DeskCtx, symbol: str) -> None:
        if ctx.guild_id and ctx.channel_id and symbol:
            db.set_last_ticker(ctx.guild_id, ctx.channel_id, symbol)

    async def _execute(self, ctx: DeskCtx, intent: Intent, original: str) -> None:
        action = intent.action

        if action == "help":
            await ctx.send(embed=simple_embed("MarkIt", HELP_BLURB))
            return

        if action.startswith("paper_"):
            await self._execute_paper(ctx, intent)
            return

        if action == "ask":
            if not gemini.available():
                await ctx.send(
                    "I couldn't map that to a desk command. Try "
                    "`@MarkIt chart AAPL`, `@MarkIt news NVDA`, or `/markit help`.",
                    ephemeral=True,
                )
                return
            context = f"Last ticker: {intent.symbol}" if intent.symbol else None
            answer = await run_blocking(
                gemini.ask, intent.query or original, context=context
            )
            await ctx.send(embed=simple_embed("MarkIt", answer[:4000]))
            return

        if action == "fgi":
            stocks = await run_blocking(stock_fear_greed)
            crypto = await run_blocking(crypto_fear_greed)
            await ctx.send(
                embed=simple_embed("Fear & Greed", stocks["text"] + "\n\n" + crypto["text"])
            )
            return

        if action == "heatmap":
            if not ctx.guild_id:
                await ctx.send("Server only.", ephemeral=True)
                return
            rows = db.watch_list(guild_id=ctx.guild_id, server=True)
            tickers = [r["symbol"] for r in rows] or intent.symbols
            if not tickers:
                await ctx.send(
                    "No watchlist yet — `/watch tickers:AAPL,MSFT server:True` or name some tickers.",
                    ephemeral=True,
                )
                return
            secs = await run_blocking(get_many, tickers[:30])
            pairs = [(s.yahoo, float(s.change_pct or 0)) for s in secs]
            buf = await run_blocking(charts.render_heatmap, pairs, "Watchlist movers")
            await ctx.send(file=discord.File(buf, filename="heatmap.png"))
            return

        if action == "bond":
            import asyncio

            query = intent.query or original
            try:
                quote = await asyncio.wait_for(resolve_bond(query), timeout=45)
            except Exception as exc:
                await ctx.send(
                    f"Could not resolve bond `{query}`: {exc}\n"
                    "_Try `IHRT 8 3/8 May 2027` or CUSIP `45174HBD8`._",
                    ephemeral=True,
                )
                return
            if ctx.guild_id and ctx.channel_id and quote.cusip:
                db.set_last_ticker(ctx.guild_id, ctx.channel_id, quote.cusip)
            await send_bond_card(ctx.destination, quote)
            return

        if action == "compare":
            parts = intent.symbols[:]
            if intent.symbol and intent.symbol not in parts:
                parts.insert(0, intent.symbol)
            if len(parts) < 2:
                await ctx.send(
                    "Compare needs at least two tickers — e.g. `compare AAPL and MSFT`.",
                    ephemeral=True,
                )
                return
            buf = await run_blocking(charts.render_compare, parts[:8], intent.period)
            await ctx.send(file=discord.File(buf, filename="compare.png"))
            return

        symbol = intent.symbol
        if not symbol:
            await ctx.send(
                "Which ticker? e.g. `@MarkIt AAPL` or `@MarkIt chart NVDA`.",
                ephemeral=True,
            )
            return

        symbol = normalize_symbol(symbol)
        await self._remember(ctx, symbol)

        if action == "chart":
            buf = await run_blocking(charts.render_chart, symbol, intent.period)
            await ctx.send(
                file=discord.File(
                    buf,
                    filename=f"{symbol.replace('^', '').replace('=', '')}-chart.png",
                )
            )
            return

        if action == "volume":
            buf = await run_blocking(charts.render_volume_chart, symbol, intent.period)
            await ctx.send(
                file=discord.File(
                    buf,
                    filename=f"{symbol.replace('^', '').replace('=', '')}-volume.png",
                )
            )
            return

        if action in {"quote", "book"}:
            sec = await run_blocking(get_security, symbol)
            await self._remember(ctx, sec.yahoo)
            # Book asks open expanded so bid/ask/spread are visible immediately.
            await publish_ticker_pill(
                ctx.destination,
                sec,
                expanded=(action == "book"),
            )
            return

        if action == "financials":
            data = await run_blocking(
                statements.financials, symbol, intent.statement, True
            )
            await ctx.send(embed=simple_embed("FA · Financials", data["text"]))
            return

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
            await send_function(ctx.destination, fn, symbol)
            return

        await ctx.send(
            f"Not sure how to handle `{action}`. Try `/markit help` or `@MarkIt AAPL`.",
            ephemeral=True,
        )

    async def _execute_paper(self, ctx: DeskCtx, intent: Intent) -> None:
        if not ctx.guild:
            await ctx.send("Paper trading is server-only.", ephemeral=True)
            return

        action = intent.action
        guild_id = ctx.guild.id

        if action == "paper_leaderboard":
            book = await run_blocking(paper_pnl.build_server_book, guild_id)
            await ctx.send(
                embed=simple_embed("Paper leaderboard", paper_pnl.format_leaderboard(book))
            )
            return

        if action == "paper_server":
            book = await run_blocking(paper_pnl.build_server_book, guild_id)
            await ctx.send(
                embed=simple_embed("Server paper PnL", paper_pnl.format_server_summary(book))
            )
            return

        if action == "paper_pnl":
            uid = intent.trader_mention or ctx.user_id
            book = await run_blocking(paper_pnl.build_trader_book, guild_id, uid)
            member = ctx.guild.get_member(uid)
            name = member.display_name if member else str(uid)
            await ctx.send(
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
                uid = intent.trader_mention or ctx.user_id
                tbook = await run_blocking(paper_pnl.build_trader_book, guild_id, uid)
                member = ctx.guild.get_member(uid)
                name = member.display_name if member else str(uid)
                text = paper_pnl.format_positions(tbook.positions, title=f"Open · {name}")
            await ctx.send(embed=simple_embed("Paper positions", text))
            return

        if action == "paper_close":
            if intent.position_id is None:
                await ctx.send("Which position? e.g. `close position #3`", ephemeral=True)
                return
            row = db.paper_get(intent.position_id, guild_id)
            if not row:
                await ctx.send("Position not found.", ephemeral=True)
                return
            is_owner = row["user_id"] == ctx.user_id
            is_mod = isinstance(ctx.user, discord.Member) and (
                ctx.user.guild_permissions.manage_messages
            )
            if not is_owner and not is_mod:
                await ctx.send(
                    "Only the trader (or a mod) can close that position.",
                    ephemeral=True,
                )
                return
            sec = await run_blocking(get_security, row["symbol"])
            if sec.last is None:
                await ctx.send("No last price to mark the close.", ephemeral=True)
                return
            closed = db.paper_close(
                intent.position_id,
                ctx.user_id,
                exit_price=float(sec.last),
                allow_any=is_mod and not is_owner,
            )
            if not closed:
                await ctx.send("Could not close.", ephemeral=True)
                return
            await ctx.send(
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
                await ctx.send("Which ticker? e.g. `paper buy 10 AAPL`", ephemeral=True)
                return
            sym = normalize_symbol(intent.symbol)
            sec = await run_blocking(get_security, sym)
            if sec.last is None:
                await ctx.send("No last price.", ephemeral=True)
                return
            side = "long" if action == "paper_buy" else "short"
            qty = intent.qty if intent.qty > 0 else 1.0
            pid = db.paper_open(guild_id, ctx.user_id, sym, side, qty, sec.last)
            await self._remember(ctx, sym)
            await ctx.send(
                embed=simple_embed(
                    f"Paper #{pid} booked",
                    f"<@{ctx.user_id}> {side} `{sym}` x{qty} @ {fmt.number(sec.last)}\n"
                    "Attributed to your book · try `my pnl` or `leaderboard`",
                )
            )
            return

        await ctx.send(f"Unknown paper action `{action}`.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MarkIt(bot))
