from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from app.autocomplete import (
    attach_symbol_autocomplete,
    suggest_bonds,
    suggest_periods,
    suggest_smart_query,
    suggest_statements,
    suggest_symbol_list,
)
from app.db import db
from app.market import charts, congress, filings, news, statements
from app.market.bonds import looks_like_bond_query, resolve_bond
from app.market.quotes import get_many, get_security
from app.market.sentiment import crypto_fear_greed, stock_fear_greed
from app.security import normalize_symbol
from app.services.dispatch import run_blocking, send_function
from app.ui.bond_pill import BondPill
from app.ui.pill import TickerPill, simple_embed


class Research(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _remember(self, interaction: discord.Interaction, symbol: str) -> None:
        if interaction.guild_id and interaction.channel_id:
            db.set_last_ticker(interaction.guild_id, interaction.channel_id, symbol)

    def _symbol(self, interaction: discord.Interaction, symbol: str | None) -> str:
        if symbol:
            return normalize_symbol(symbol)
        if interaction.guild_id and interaction.channel_id:
            last = db.get_last_ticker(interaction.guild_id, interaction.channel_id)
            if last:
                return last
        raise ValueError("Pass a symbol, or paste a ticker in chat first.")

    async def _defer(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer()

    async def _send_quote(self, interaction: discord.Interaction, symbol: str | None) -> None:
        await self._defer(interaction)
        try:
            sym = self._symbol(interaction, symbol)
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        sec = await run_blocking(get_security, sym)
        self._remember(interaction, sec.yahoo)
        await interaction.followup.send(view=TickerPill(sec))

    async def _send_chart(
        self,
        interaction: discord.Interaction,
        symbol: str | None,
        period: str,
    ) -> None:
        await self._defer(interaction)
        try:
            sym = self._symbol(interaction, symbol)
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        self._remember(interaction, sym)
        buf = await run_blocking(charts.render_chart, sym, period)
        await interaction.followup.send(file=discord.File(buf, filename=f"{sym}-chart.png"))

    @app_commands.command(name="quote", description="Bloomberg-style quote pill for any asset")
    @app_commands.describe(symbol="Equity, ETF, FX, crypto, future, option, index…")
    async def quote(self, interaction: discord.Interaction, symbol: str) -> None:
        await self._send_quote(interaction, symbol)

    @app_commands.command(name="des", description="Description / quote pill (DES)")
    async def des(self, interaction: discord.Interaction, symbol: str | None = None) -> None:
        await self._send_quote(interaction, symbol)

    @app_commands.command(name="chart", description="Price chart (GP)")
    @app_commands.describe(symbol="Ticker", period="1d 5d 1m 3m 6m 1y 5y ytd")
    async def chart(
        self,
        interaction: discord.Interaction,
        symbol: str | None = None,
        period: str = "6m",
    ) -> None:
        await self._send_chart(interaction, symbol, period)

    @app_commands.command(name="gp", description="Alias for /chart")
    async def gp(
        self,
        interaction: discord.Interaction,
        symbol: str | None = None,
        period: str = "6m",
    ) -> None:
        await self._send_chart(interaction, symbol, period)

    @app_commands.command(name="financials", description="Income / balance / cash flow (FA)")
    @app_commands.describe(statement="income, balance, or cashflow", quarterly="Use quarterly periods")
    async def financials(
        self,
        interaction: discord.Interaction,
        symbol: str | None = None,
        statement: str = "income",
        quarterly: bool = True,
    ) -> None:
        await self._defer(interaction)
        sym = self._symbol(interaction, symbol)
        data = await run_blocking(statements.financials, sym, statement, quarterly)
        await interaction.followup.send(embed=simple_embed("FA · Financials", data["text"]))

    @app_commands.command(name="fa", description="Alias for /financials")
    async def fa(
        self,
        interaction: discord.Interaction,
        symbol: str | None = None,
        statement: str = "income",
        quarterly: bool = True,
    ) -> None:
        await self.financials(interaction, symbol, statement, quarterly)

    @app_commands.command(name="news", description="Company / asset news (CN)")
    async def news_cmd(self, interaction: discord.Interaction, symbol: str | None = None) -> None:
        await self._defer(interaction)
        sym = self._symbol(interaction, symbol)
        data = await run_blocking(news.company_news, sym)
        await interaction.followup.send(embed=simple_embed("CN · News", data["text"]))

    @app_commands.command(name="cn", description="Alias for /news")
    async def cn(self, interaction: discord.Interaction, symbol: str | None = None) -> None:
        await self.news_cmd(interaction, symbol)

    @app_commands.command(name="holders", description="Institutions & insiders (PHDC)")
    async def holders(self, interaction: discord.Interaction, symbol: str | None = None) -> None:
        await self._defer(interaction)
        sym = self._symbol(interaction, symbol)
        data = await run_blocking(statements.holders, sym)
        await interaction.followup.send(embed=simple_embed("PHDC · Holders", data["text"]))

    @app_commands.command(name="phdc", description="Alias for /holders")
    async def phdc(self, interaction: discord.Interaction, symbol: str | None = None) -> None:
        await self.holders(interaction, symbol)

    @app_commands.command(name="analysts", description="Analyst ratings & targets (ANR)")
    async def analysts(self, interaction: discord.Interaction, symbol: str | None = None) -> None:
        await self._defer(interaction)
        sym = self._symbol(interaction, symbol)
        data = await run_blocking(statements.analysts, sym)
        await interaction.followup.send(embed=simple_embed("ANR · Analysts", data["text"]))

    @app_commands.command(name="anr", description="Alias for /analysts")
    async def anr(self, interaction: discord.Interaction, symbol: str | None = None) -> None:
        await self.analysts(interaction, symbol)

    @app_commands.command(name="earnings", description="Earnings dates & estimates (ERN)")
    async def earnings(self, interaction: discord.Interaction, symbol: str | None = None) -> None:
        await self._defer(interaction)
        sym = self._symbol(interaction, symbol)
        data = await run_blocking(statements.earnings, sym)
        await interaction.followup.send(embed=simple_embed("ERN · Earnings", data["text"]))

    @app_commands.command(name="ern", description="Alias for /earnings")
    async def ern(self, interaction: discord.Interaction, symbol: str | None = None) -> None:
        await self.earnings(interaction, symbol)

    @app_commands.command(name="dividends", description="Dividend yield & dates (DVD)")
    async def dividends(self, interaction: discord.Interaction, symbol: str | None = None) -> None:
        await send_function(interaction, "dvd", self._symbol(interaction, symbol))

    @app_commands.command(name="dvd", description="Alias for /dividends")
    async def dvd(self, interaction: discord.Interaction, symbol: str | None = None) -> None:
        await self.dividends(interaction, symbol)

    @app_commands.command(name="options", description="Options chain snapshot")
    async def options(
        self,
        interaction: discord.Interaction,
        symbol: str | None = None,
        expiry: str | None = None,
    ) -> None:
        await self._defer(interaction)
        sym = self._symbol(interaction, symbol)
        data = await run_blocking(statements.options_chain, sym, expiry)
        await interaction.followup.send(embed=simple_embed("Options", data["text"]))

    @app_commands.command(name="opt", description="Alias for /options")
    async def opt(
        self,
        interaction: discord.Interaction,
        symbol: str | None = None,
        expiry: str | None = None,
    ) -> None:
        await self.options(interaction, symbol, expiry)

    @app_commands.command(name="short", description="Short interest")
    async def short(self, interaction: discord.Interaction, symbol: str | None = None) -> None:
        await send_function(interaction, "short", self._symbol(interaction, symbol))

    @app_commands.command(name="compare", description="Relative performance chart (RV)")
    @app_commands.describe(symbols="Space-separated tickers, e.g. AAPL MSFT GOOGL")
    async def compare(
        self,
        interaction: discord.Interaction,
        symbols: str,
        period: str = "6m",
    ) -> None:
        await self._defer(interaction)
        parts = [normalize_symbol(s) for s in symbols.replace(",", " ").split() if s.strip()]
        if len(parts) < 2:
            await interaction.followup.send("Pass at least two symbols.", ephemeral=True)
            return
        buf = await run_blocking(charts.render_compare, parts[:8], period)
        await interaction.followup.send(file=discord.File(buf, filename="compare.png"))

    @app_commands.command(name="rv", description="Alias for /compare")
    async def rv(self, interaction: discord.Interaction, symbols: str, period: str = "6m") -> None:
        await self.compare(interaction, symbols, period)

    @app_commands.command(name="filings", description="Recent SEC filings")
    async def filings_cmd(
        self,
        interaction: discord.Interaction,
        symbol: str | None = None,
        forms: str | None = None,
    ) -> None:
        await self._defer(interaction)
        sym = self._symbol(interaction, symbol)
        form_list = [f.strip() for f in forms.split(",")] if forms else None
        data = await run_blocking(filings.recent_filings, sym, form_list)
        await interaction.followup.send(embed=simple_embed("SEC filings", data["text"]))

    @app_commands.command(name="sec", description="Alias for /filings")
    async def sec(
        self,
        interaction: discord.Interaction,
        symbol: str | None = None,
        forms: str | None = None,
    ) -> None:
        await self.filings_cmd(interaction, symbol, forms)

    @app_commands.command(name="congress", description="Congressional STOCK Act trades")
    async def congress_cmd(
        self,
        interaction: discord.Interaction,
        symbol: str | None = None,
        limit: app_commands.Range[int, 1, 25] = 10,
    ) -> None:
        await self._defer(interaction)
        data = await run_blocking(congress.recent_trades, symbol, limit)
        await interaction.followup.send(embed=simple_embed("Congress", data["text"]))

    @app_commands.command(name="heatmap", description="Watchlist % change board")
    async def heatmap(self, interaction: discord.Interaction, symbols: str | None = None) -> None:
        await self._defer(interaction)
        if symbols:
            tickers = [normalize_symbol(s) for s in symbols.replace(",", " ").split() if s.strip()]
        else:
            rows = db.watch_list(guild_id=interaction.guild_id or 0, server=True)
            tickers = [r["symbol"] for r in rows]
            if not tickers and interaction.guild_id:
                rows = db.watch_list(guild_id=interaction.guild_id, user_id=interaction.user.id)
                tickers = [r["symbol"] for r in rows]
        if not tickers:
            await interaction.followup.send("No symbols. Pass some or `/watch` first.", ephemeral=True)
            return
        secs = await run_blocking(get_many, tickers[:30])
        pairs = [(s.yahoo, float(s.change_pct or 0)) for s in secs]
        buf = await run_blocking(charts.render_heatmap, pairs, "Watchlist movers")
        await interaction.followup.send(file=discord.File(buf, filename="heatmap.png"))

    @app_commands.command(name="hmap", description="Alias for /heatmap")
    async def hmap(self, interaction: discord.Interaction, symbols: str | None = None) -> None:
        await self.heatmap(interaction, symbols)

    @app_commands.command(name="fgi", description="Fear & Greed — stocks and crypto")
    async def fgi(self, interaction: discord.Interaction) -> None:
        await self._defer(interaction)
        stocks = await run_blocking(stock_fear_greed)
        crypto = await run_blocking(crypto_fear_greed)
        text = stocks["text"] + "\n\n" + crypto["text"]
        await interaction.followup.send(embed=simple_embed("Fear & Greed", text))

    @app_commands.command(
        name="bond",
        description="Corporate bond card via FINRA TRACE (coupon, CUSIP, or FINRA symbol)",
    )
    @app_commands.describe(
        query="e.g. IHRT 8 3/8 May 2027 · IHRT 8.375 05/01/27 · 45174HBD8",
    )
    async def bond(self, interaction: discord.Interaction, query: str) -> None:
        await self._defer(interaction)
        try:
            quote = await resolve_bond(query)
        except Exception as exc:
            await interaction.followup.send(f"Could not resolve bond: {exc}", ephemeral=True)
            return
        if interaction.guild_id and interaction.channel_id and quote.cusip:
            db.set_last_ticker(interaction.guild_id, interaction.channel_id, quote.cusip)
        await interaction.followup.send(view=BondPill(quote))

    @app_commands.command(name="quote-smart", description="Auto-detect equity/FX/crypto/future/option/bond")
    async def quote_smart(self, interaction: discord.Interaction, query: str) -> None:
        await self._defer(interaction)
        if looks_like_bond_query(query):
            quote = await resolve_bond(query)
            await interaction.followup.send(view=BondPill(quote))
            return
        sym = normalize_symbol(query)
        sec = await run_blocking(get_security, sym)
        self._remember(interaction, sec.yahoo)
        await interaction.followup.send(view=TickerPill(sec))


def _wire_autocomplete(cog: Research) -> None:
    symbol_cmds = [
        cog.quote,
        cog.des,
        cog.chart,
        cog.gp,
        cog.financials,
        cog.fa,
        cog.news_cmd,
        cog.cn,
        cog.holders,
        cog.phdc,
        cog.analysts,
        cog.anr,
        cog.earnings,
        cog.ern,
        cog.dividends,
        cog.dvd,
        cog.options,
        cog.opt,
        cog.short,
        cog.filings_cmd,
        cog.sec,
        cog.congress_cmd,
    ]
    for cmd in symbol_cmds:
        attach_symbol_autocomplete(cmd, "symbol")

    for cmd in (cog.chart, cog.gp, cog.compare, cog.rv):
        cmd.autocomplete("period")(suggest_periods)

    for cmd in (cog.financials, cog.fa):
        cmd.autocomplete("statement")(suggest_statements)

    for cmd in (cog.compare, cog.rv, cog.heatmap, cog.hmap):
        cmd.autocomplete("symbols")(suggest_symbol_list)

    cog.bond.autocomplete("query")(suggest_bonds)
    cog.quote_smart.autocomplete("query")(suggest_smart_query)


async def setup(bot: commands.Bot) -> None:
    cog = Research(bot)
    await bot.add_cog(cog)
    _wire_autocomplete(cog)
