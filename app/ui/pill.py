from __future__ import annotations

from datetime import datetime, timezone

import discord
from discord import ui

from app import format as fmt
from app.security import Security
from app.ui.links import external_links

# custom_id: md:fn:<function>:<SYMBOL>[:YYYY-MM-DD]  (optional expiry for opt/chain)
FN_TEMPLATE = (
    r"md:fn:(?P<fn>gp|des|fa|cn|phdc|anr|ern|dvd|opt|short):"
    r"(?P<symbol>[A-Za-z0-9^.=_\-]{1,32})"
    r"(?::(?P<expiry>\d{4}-\d{2}-\d{2}))?"
)
# Manual refresh on a live pill
REFRESH_TEMPLATE = r"md:ref:(?P<symbol>[A-Za-z0-9^.=_\-]{1,32})"
# Expand / collapse — state in custom_id: 0=collapsed (button expands), 1=expanded (button collapses)
EXPAND_TEMPLATE = r"md:xp:(?P<state>[01]):(?P<symbol>[A-Za-z0-9^.=_\-]{1,32})"


def _tick_marker(last: float | None, previous_last: float | None) -> str:
    if last is None or previous_last is None:
        return ""
    if last > previous_last:
        return " · tick ▲"
    if last < previous_last:
        return " · tick ▼"
    return " · ="


# Discord ansi code-block colors (only reliable way to paint quote text red/green).
_ANSI_GREEN = "\u001b[1;32m"
_ANSI_RED = "\u001b[1;31m"
_ANSI_GRAY = "\u001b[0;37m"
_ANSI_RESET = "\u001b[0m"


def _px(value: float | None, *, digits: int | None = None) -> str:
    if value is None:
        return "—"
    if digits is None:
        digits = 4 if abs(value) < 10 else 2
    return fmt.number(value, digits)


def _size(value: float | None) -> str:
    if value is None:
        return ""
    if float(value).is_integer():
        return str(int(value))
    return fmt.compact(value)


def _book_line(sec: Security) -> str | None:
    """Bid / ask / spread — IB-style top of book when Yahoo provides it."""
    if not sec.has_book:
        return None
    digits = 4 if (sec.last or sec.bid or 0) < 10 else 2
    bid = _px(sec.bid, digits=digits)
    ask = _px(sec.ask, digits=digits)
    bid_s = f"Bid `{bid}`"
    if sec.bid_size is not None and sec.bid_size > 0:
        bid_s = f"Bid `{bid}` x{_size(sec.bid_size)}"
    ask_s = f"Ask `{ask}`"
    if sec.ask_size is not None and sec.ask_size > 0:
        ask_s = f"Ask `{ask}` x{_size(sec.ask_size)}"
    parts = [bid_s, ask_s]
    if sec.spread is not None:
        parts.append(f"Spr `{_px(sec.spread, digits=digits)}`")
    if sec.mid is not None:
        parts.append(f"Mid `{_px(sec.mid, digits=digits)}`")
    return " · ".join(parts)


def _quote_ansi_block(
    sec: Security,
    *,
    previous_last: float | None,
    live: bool,
    as_of: datetime | None,
) -> str:
    """IB-style colored last / day change line via Discord ```ansi```."""
    change = fmt.signed(sec.change) if sec.change is not None else "—"
    change_pct = fmt.pct(sec.change_pct, already_percent=True) if sec.change_pct is not None else "—"
    day_up = (sec.change or 0) > 0
    day_down = (sec.change or 0) < 0
    arrow = "▲" if day_up else "▼" if day_down else "•"
    price = _px(sec.last)
    tick = _tick_marker(sec.last, previous_last)
    colour = _ANSI_GREEN if day_up else _ANSI_RED if day_down else _ANSI_GRAY

    when = (as_of or datetime.now(timezone.utc)).astimezone().strftime("%H:%M:%S")
    live_bit = f" · LIVE {when}" if live else f" · as of {when}"
    currency = f" · {sec.currency}" if sec.currency else ""

    body = f"{arrow} {price}  {change} ({change_pct}){tick}{currency}{live_bit}"
    return f"```ansi\n{colour}{body}{_ANSI_RESET}\n```"


def pill_text(
    sec: Security,
    *,
    previous_last: float | None = None,
    live: bool = True,
    as_of: datetime | None = None,
    expanded: bool = False,
) -> str:
    quote = _quote_ansi_block(sec, previous_last=previous_last, live=live, as_of=as_of)

    # Collapsed: last + day move only. Bid/ask stays off until Expand or a book ask.
    if not expanded:
        return "\n".join(
            [
                f"# {sec.yahoo} · {sec.asset_label}",
                quote,
            ]
        )

    lines = [
        f"# {sec.yahoo} · {sec.asset_label}",
        f"**{sec.name}**",
        quote,
    ]
    book = _book_line(sec)
    if book:
        lines.append(book)

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
        stats.append(f"Strike `{_px(sec.strike)}`")
        stats.append(f"{sec.option_side or 'Option'} exp `{sec.expiry or '—'}`")
        if sec.open_interest is not None:
            stats.append(f"OI `{fmt.compact(sec.open_interest)}`")
        if sec.underlying:
            stats.append(f"Underlying `{sec.underlying}`")
    elif sec.is_fx:
        stats.append(f"Open `{_px(sec.open, digits=4)}`")
        stats.append(f"Day `{_px(sec.day_low, digits=4)}–{_px(sec.day_high, digits=4)}`")
        stats.append(f"52w `{_px(sec.year_low, digits=4)}–{_px(sec.year_high, digits=4)}`")
    elif sec.is_crypto or sec.is_future:
        if sec.market_cap:
            stats.append(f"Mkt cap `{fmt.money(sec.market_cap, sec.currency)}`")
        stats.append(f"Vol `{fmt.compact(sec.volume)}`")
        stats.append(f"Day `{_px(sec.day_low)}–{_px(sec.day_high)}`")
        stats.append(f"52w `{_px(sec.year_low)}–{_px(sec.year_high)}`")
    elif sec.is_index or sec.is_rate_like:
        stats.append(f"Open `{_px(sec.open)}`")
        stats.append(f"Day `{_px(sec.day_low)}–{_px(sec.day_high)}`")
        stats.append(f"52w `{_px(sec.year_low)}–{_px(sec.year_high)}`")
    else:
        if sec.market_cap:
            stats.append(f"Mkt cap `{fmt.money(sec.market_cap, sec.currency)}`")
        if sec.trailing_pe:
            stats.append(f"P/E `{fmt.number(sec.trailing_pe)}`")
        if sec.yield_ is not None:
            stats.append(f"Yield `{fmt.pct_frac(sec.yield_)}`")
        stats.append(f"Vol `{fmt.compact(sec.volume)}` shares")
        if sec.avg_volume_10d is not None:
            stats.append(f"10d avg vol `{fmt.compact(sec.avg_volume_10d)}`")
        elif sec.avg_volume is not None:
            stats.append(f"Avg vol `{fmt.compact(sec.avg_volume)}`")
        stats.append(f"Day `{_px(sec.day_low)}–{_px(sec.day_high)}`")
        stats.append(f"52w `{_px(sec.year_low)}–{_px(sec.year_high)}`")
        if sec.pre_market is not None:
            stats.append(f"Pre `{_px(sec.pre_market)}`")
        if sec.post_market is not None:
            stats.append(f"Post `{_px(sec.post_market)}`")

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
        under = sec.underlying or symbol
        chain_id = f"md:fn:opt:{under}"
        if sec.expiry:
            chain_id = f"md:fn:opt:{under}:{sec.expiry}"
        buttons.extend(
            [
                ui.Button(
                    label="Underlying",
                    style=discord.ButtonStyle.secondary,
                    custom_id=f"md:fn:des:{under}",
                ),
                ui.Button(
                    label="Chain",
                    style=discord.ButtonStyle.secondary,
                    custom_id=chain_id,
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


def _expand_toggle_button(sec: Security, *, expanded: bool) -> ui.Button:
    """custom_id state mirrors current view: 0=collapsed, 1=expanded."""
    if expanded:
        return ui.Button(
            label="Collapse",
            style=discord.ButtonStyle.secondary,
            custom_id=f"md:xp:1:{sec.yahoo}",
        )
    return ui.Button(
        label="Expand",
        style=discord.ButtonStyle.primary,
        custom_id=f"md:xp:0:{sec.yahoo}",
    )


def _collapsed_action_buttons(sec: Security) -> list[ui.Button]:
    return [
        _expand_toggle_button(sec, expanded=False),
        ui.Button(
            label="Refresh",
            style=discord.ButtonStyle.success
            if (sec.change or 0) >= 0
            else discord.ButtonStyle.danger,
            custom_id=f"md:ref:{sec.yahoo}",
        ),
    ]


class TickerPill(ui.LayoutView):
    """Bloomberg/IB-style quote card — collapsed by default; Expand unpacks tools."""

    def __init__(
        self,
        sec: Security,
        *,
        previous_last: float | None = None,
        live: bool = True,
        expanded: bool = False,
        timeout: float | None = 900,
    ) -> None:
        super().__init__(timeout=timeout)
        self.expanded = expanded
        children: list[ui.Item] = [
            ui.TextDisplay(
                pill_text(sec, previous_last=previous_last, live=live, expanded=expanded)
            ),
            ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
        ]
        if expanded:
            fns = function_buttons(sec)
            # Row 1: Collapse + Refresh + primary research (max 5).
            children.append(
                ui.ActionRow(
                    _expand_toggle_button(sec, expanded=True),
                    *fns[:4],
                )
            )
            rest = fns[4:] + extra_function_buttons(sec)
            if rest:
                children.append(ui.ActionRow(*rest[:5]))
            links = [
                ui.Button(style=discord.ButtonStyle.link, label=label, url=url)
                for label, url in external_links(sec)[:4]
            ]
            if links:
                children.append(ui.ActionRow(*links))
        else:
            children.append(ui.ActionRow(*_collapsed_action_buttons(sec)))

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
