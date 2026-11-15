from __future__ import annotations

import asyncio
from typing import Any

import discord

from app import format as fmt
from app.market import charts, congress, filings, news, statements
from app.market.quotes import get_security
from app.ui.pill import simple_embed
from app.ui.ticker_respond import publish_ticker_pill


async def run_blocking(func, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)


async def send_function(
    destination: discord.abc.Messageable | discord.Interaction,
    fn: str,
    symbol: str,
    *,
    ephemeral: bool = False,
) -> None:
    fn = fn.lower()
    try:
        if fn == "gp":
            await _send_chart(destination, symbol, ephemeral=ephemeral)
        elif fn == "des":
            sec = await run_blocking(get_security, symbol)
            if isinstance(destination, discord.Interaction):
                await publish_ticker_pill(destination, sec, ephemeral=ephemeral)
            else:
                await publish_ticker_pill(destination, sec)
        elif fn == "fa":
            data = await run_blocking(statements.financials, symbol, "income", True)
            await _respond(destination, embed=simple_embed("FA · Financials", data["text"]), ephemeral=ephemeral)
        elif fn == "cn":
            data = await run_blocking(news.company_news, symbol)
            await _respond(destination, embed=simple_embed("CN · News", data["text"]), ephemeral=ephemeral)
        elif fn == "phdc":
            data = await run_blocking(statements.holders, symbol)
            await _respond(destination, embed=simple_embed("PHDC · Holders", data["text"]), ephemeral=ephemeral)
        elif fn == "anr":
            data = await run_blocking(statements.analysts, symbol)
            await _respond(destination, embed=simple_embed("ANR · Analysts", data["text"]), ephemeral=ephemeral)
        elif fn == "ern":
            data = await run_blocking(statements.earnings, symbol)
            await _respond(destination, embed=simple_embed("ERN · Earnings", data["text"]), ephemeral=ephemeral)
        elif fn == "dvd":
            sec = await run_blocking(get_security, symbol)
            text = (
                f"**{sec.yahoo} dividends**\n"
                f"Yield {fmt.pct(sec.yield_ if (sec.yield_ or 0) > 1 else sec.yield_, already_percent=(sec.yield_ or 0) > 1)}\n"
                f"Ex-date {fmt.as_date(sec.raw.get('exDividendDate'))}\n"
                f"Trailing annual yield {fmt.pct(sec.raw.get('trailingAnnualDividendYield'))}"
            )
            await _respond(destination, embed=simple_embed("DVD · Dividends", text), ephemeral=ephemeral)
        elif fn == "opt":
            data = await run_blocking(statements.options_chain, symbol)
            await _respond(destination, embed=simple_embed("Options", data["text"]), ephemeral=ephemeral)
        elif fn == "short":
            sec = await run_blocking(get_security, symbol)
            text = (
                f"**{sec.yahoo} short interest**\n"
                f"Short % of float {fmt.pct(sec.short_percent)}\n"
                f"Days to cover {fmt.number(sec.days_to_cover)}\n"
                f"Shares short {fmt.compact(sec.raw.get('sharesShort'))}"
            )
            await _respond(destination, embed=simple_embed("Short interest", text), ephemeral=ephemeral)
        elif fn == "sec":
            data = await run_blocking(filings.recent_filings, symbol)
            await _respond(destination, embed=simple_embed("SEC filings", data["text"]), ephemeral=ephemeral)
        elif fn == "congress":
            data = await run_blocking(congress.recent_trades, symbol)
            await _respond(destination, embed=simple_embed("Congress", data["text"]), ephemeral=ephemeral)
        else:
            await _respond(destination, content=f"Unknown function `{fn}`", ephemeral=True)
    except Exception as exc:
        await _respond(destination, content=f"Could not run `{fn}` on `{symbol}`: {exc}", ephemeral=True)


async def _send_chart(
    destination: discord.abc.Messageable | discord.Interaction,
    symbol: str,
    *,
    period: str = "6m",
    ephemeral: bool = False,
) -> None:
    buf = await run_blocking(charts.render_chart, symbol, period)
    file = discord.File(buf, filename=f"{symbol.replace('^','').replace('=','')}-chart.png")
    if isinstance(destination, discord.Interaction):
        if destination.response.is_done():
            await destination.followup.send(file=file, ephemeral=ephemeral)
        else:
            await destination.response.send_message(file=file, ephemeral=ephemeral)
    else:
        await destination.send(file=file)


async def _respond(
    destination: discord.abc.Messageable | discord.Interaction,
    *,
    content: str | None = None,
    embed: discord.Embed | None = None,
    view: discord.ui.View | None = None,
    ephemeral: bool = False,
) -> None:
    kwargs: dict[str, Any] = {}
    if content:
        kwargs["content"] = content
    if embed:
        kwargs["embed"] = embed
    if view:
        kwargs["view"] = view
    if isinstance(destination, discord.Interaction):
        kwargs["ephemeral"] = ephemeral
        if destination.response.is_done():
            await destination.followup.send(**kwargs)
        else:
            await destination.response.send_message(**kwargs)
    else:
        await destination.send(**{k: v for k, v in kwargs.items() if k != "ephemeral"})
