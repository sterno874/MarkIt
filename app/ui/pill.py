from __future__ import annotations

from datetime import datetime, timezone

import discord
from discord import ui

from app import format as fmt
from app.security import Security
from app.ui.links import external_links

# custom_id: md:fn:<function>:<SYMBOL>
FN_TEMPLATE = r"md:fn:(?P<fn>gp|des|fa|cn|phdc|anr|ern|dvd|opt|short):(?P<symbol>[A-Za-z0-9^.=_\-]{1,32})"
# Manual refresh on a live pill
REFRESH_TEMPLATE = r"md:ref:(?P<symbol>[A-Za-z0-9^.=_\-]{1,32})"


def _tick_marker(last: float | None, previous_last: float | None) -> str:
    if last is None or previous_last is None:
        return ""
    if last > previous_last:
        return " · tick ▲"
    if last < previous_last:
        return " · tick ▼"
    return " · ="


def pill_text(
    sec: Security,
    *,
    previous_last: float | None = None,
    live: bool = True,
    as_of: datetime | None = None,
) -> str:
    change = fmt.signed(sec.change) if sec.change is not None else "—"
    change_pct = fmt.pct(sec.change_pct, already_percent=True) if sec.change_pct is not None else "—"
    day_up = (sec.change or 0) > 0
    day_down = (sec.change or 0) < 0
    arrow = "▲" if day_up else "▼" if day_down else "•"
    price = fmt.number(sec.last, 4 if (sec.last or 0) < 10 else 2)
    tick = _tick_marker(sec.last, previous_last)

    # IB-style: day direction owns the headline; last tick called out separately.
    when = (as_of or datetime.now(timezone.utc)).astimezone().strftime("%H:%M:%S")
    live_bit = f" · LIVE {when}" if live else f" · as of {when}"

    lines = [
        f"# {sec.yahoo} · {sec.asset_label}",
        f"**{sec.name}**",
        f"{arrow} `{price}` **{change} ({change_pct})**{tick} · {sec.currency or ''}".rstrip()
        + live_bit,
    ]

    meta: list[str] = []
    if sec.exchange:
        meta.append(sec.exchange)
    if sec.sector:
        meta.append(sec.sector)
    if sec.industry:
        meta.append(sec.industry)
    if meta:
        lines.append(" · ".join(meta))

    stats: list[str] = []
    if sec.is_option:
        stats.append(f"Strike `{fmt.number(sec.strike)}`")
        stats.append(f"{sec.option_side or 'Option'} exp `{sec.expiry or '—'}`")
        if sec.bid is not None or sec.ask is not None:
            stats.append(f"Bid/Ask `{fmt.number(sec.bid)}/{fmt.number(sec.ask)}`")
        if sec.open_interest is not None:
            stats.append(f"OI `{fmt.compact(sec.open_interest)}`")
        if sec.underlying:
            stats.append(f"Underlying `{sec.underlying}`")
    elif sec.is_fx:
        stats.append(f"Open `{fmt.number(sec.open, 4)}`")
        stats.append(f"Day `{fmt.number(sec.day_low, 4)}–{fmt.number(sec.day_high, 4)}`")
        stats.append(f"52w `{fmt.number(sec.year_low, 4)}–{fmt.number(sec.year_high, 4)}`")
    elif sec.is_crypto or sec.is_future:
        if sec.market_cap:
            stats.append(f"Mkt cap `{fmt.money(sec.market_cap, sec.currency)}`")
        stats.append(f"Vol `{fmt.compact(sec.volume)}`")
        stats.append(f"Day `{fmt.number(sec.day_low)}–{fmt.number(sec.day_high)}`")
        stats.append(f"52w `{fmt.number(sec.year_low)}–{fmt.number(sec.year_high)}`")
    elif sec.is_index or sec.is_rate_like:
        stats.append(f"Open `{fmt.number(sec.open)}`")
        stats.append(f"Day `{fmt.number(sec.day_low)}–{fmt.number(sec.day_high)}`")
        stats.append(f"52w `{fmt.number(sec.year_low)}–{fmt.number(sec.year_high)}`")
    else:
        if sec.market_cap:
            stats.append(f"Mkt cap `{fmt.money(sec.market_cap, sec.currency)}`")
        if sec.trailing_pe:
            stats.append(f"P/E `{fmt.number(sec.trailing_pe)}`")
        if sec.yield_ is not None:
            # yield_ is always stored as a fraction (0.003 = 0.3%)
            stats.append(f"Yield `{fmt.pct(sec.yield_)}`")
        stats.append(f"Vol `{fmt.compact(sec.volume)}`")
        stats.append(f"52w `{fmt.number(sec.year_low)}–{fmt.number(sec.year_high)}`")

    if stats:
        lines.append(" · ".join(stats))

    if sec.summary and sec.is_equity_like:
        lines.append("")
        lines.append(fmt.truncate(sec.summary, 280))

    return "\n".join(lines)


def function_buttons(sec: Security) -> list[ui.Button]:
    symbol = sec.yahoo
    buttons: list[ui.Button] = [
        ui.Button(
            label="Refresh",
            style=discord.ButtonStyle.success
            if (sec.change or 0) >= 0
            else discord.ButtonStyle.danger,
            custom_id=f"md:ref:{symbol}",
        ),
        ui.Button(label="GP Chart", style=discord.ButtonStyle.primary, custom_id=f"md:fn:gp:{symbol}"),
        ui.Button(label="DES", style=discord.ButtonStyle.secondary, custom_id=f"md:fn:des:{symbol}"),
    ]
    if sec.is_equity_like:
        buttons.extend(
            [
                ui.Button(label="FA", style=discord.ButtonStyle.secondary, custom_id=f"md:fn:fa:{symbol}"),
                ui.Button(label="CN News", style=discord.ButtonStyle.secondary, custom_id=f"md:fn:cn:{symbol}"),
            ]
        )
    elif sec.is_option:
        buttons.extend(
            [
                ui.Button(
                    label="Underlying",
                    style=discord.ButtonStyle.secondary,
                    custom_id=f"md:fn:des:{sec.underlying or symbol}",
                ),
                ui.Button(
                    label="Chain",
                    style=discord.ButtonStyle.secondary,
                    custom_id=f"md:fn:opt:{sec.underlying or symbol}",
                ),
            ]
        )
    elif sec.is_crypto or sec.is_fx or sec.is_future or sec.is_index:
        buttons.append(
            ui.Button(label="News", style=discord.ButtonStyle.secondary, custom_id=f"md:fn:cn:{symbol}")
        )
    return buttons[:5]


def extra_function_buttons(sec: Security) -> list[ui.Button]:
    if not sec.is_equity_like:
        return []
    symbol = sec.yahoo
    return [
        ui.Button(label="PHDC", style=discord.ButtonStyle.secondary, custom_id=f"md:fn:phdc:{symbol}"),
        ui.Button(label="ANR", style=discord.ButtonStyle.secondary, custom_id=f"md:fn:anr:{symbol}"),
        ui.Button(label="ERN", style=discord.ButtonStyle.secondary, custom_id=f"md:fn:ern:{symbol}"),
        ui.Button(label="DVD", style=discord.ButtonStyle.secondary, custom_id=f"md:fn:dvd:{symbol}"),
        ui.Button(label="Options", style=discord.ButtonStyle.secondary, custom_id=f"md:fn:opt:{symbol}"),
    ]


class TickerPill(ui.LayoutView):
    """Bloomberg/IB-style quote card — green/red day accent, optional live tick."""

    def __init__(
        self,
        sec: Security,
        *,
        previous_last: float | None = None,
        live: bool = True,
        timeout: float | None = 900,
    ) -> None:
        super().__init__(timeout=timeout)
        links = [
            ui.Button(style=discord.ButtonStyle.link, label=label, url=url)
            for label, url in external_links(sec)[:4]
        ]
        children: list[ui.Item] = [
            ui.TextDisplay(
                pill_text(sec, previous_last=previous_last, live=live)
            ),
            ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
            ui.ActionRow(*function_buttons(sec)),
        ]
        extras = extra_function_buttons(sec)
        if extras:
            children.append(ui.ActionRow(*extras))
        if links:
            children.append(ui.ActionRow(*links))
        # Day performance owns the accent strip (IB-style green / red).
        self.add_item(
            ui.Container(
                *children,
                accent_colour=fmt.accent(sec.change),
            )
        )


def simple_embed(title: str, description: str, *, colour: int = 0x5865F2) -> discord.Embed:
    embed = discord.Embed(title=title[:256], description=description[:4096], colour=colour)
    return embed
