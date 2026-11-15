"""Publish and refresh live ticker pills (IB-style ticking quotes)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import discord

from app.config import LIVE_PILL_MAX, LIVE_PILL_TTL_SEC
from app.db import db
from app.market.quotes import get_security
from app.security import Security
from app.ui.pill import TickerPill

log = logging.getLogger("market-desk.live")


async def publish_ticker_pill(
    destination: discord.abc.Messageable | discord.Interaction,
    sec: Security,
    *,
    ephemeral: bool = False,
    live: bool = True,
    expanded: bool = False,
) -> discord.Message | None:
    # Don't advertise LIVE when there's no last (or it's an option contract).
    effective_live = bool(live and sec.last is not None and not sec.is_option)
    view = TickerPill(sec, live=effective_live, expanded=expanded)
    msg: discord.Message | Any | None = None
    if isinstance(destination, discord.Interaction):
        if destination.response.is_done():
            msg = await destination.followup.send(view=view, ephemeral=ephemeral, wait=True)
        else:
            await destination.response.send_message(view=view, ephemeral=ephemeral)
            msg = await destination.original_response()
    else:
        msg = await destination.send(view=view)

    # Only live-tick liquid cash quotes — skip empty shells and option contracts
    # (OCC symbols don't have reliable Yahoo intraday ticks).
    if effective_live and msg is not None and not ephemeral:
        guild_id = 0
        channel_id = getattr(msg, "channel", None) and msg.channel.id
        if isinstance(destination, discord.Interaction):
            guild_id = destination.guild_id or 0
            channel_id = destination.channel_id or channel_id
        elif getattr(msg, "guild", None):
            guild_id = msg.guild.id
        if channel_id and guild_id:
            try:
                db.live_pill_register(
                    message_id=msg.id,
                    channel_id=int(channel_id),
                    guild_id=int(guild_id),
                    symbol=sec.yahoo,
                    last_price=sec.last,
                    ttl_seconds=LIVE_PILL_TTL_SEC,
                    max_active=LIVE_PILL_MAX,
                    expanded=expanded,
                )
            except Exception:
                log.exception("failed to register live pill %s", getattr(msg, "id", None))
    return msg if isinstance(msg, discord.Message) else None


async def refresh_ticker_message(
    message: discord.Message,
    symbol: str,
    *,
    previous_last: float | None = None,
    extend_live: bool = False,
    expanded: bool | None = None,
) -> Security | None:
    row = db.live_pill_get(message.id)
    if expanded is None:
        expanded = bool(dict(row).get("expanded")) if row else False
    sec = await asyncio.to_thread(get_security, symbol)
    is_live = sec.last is not None and not sec.is_option
    await message.edit(
        view=TickerPill(
            sec, previous_last=previous_last, live=is_live, expanded=expanded
        )
    )
    if not is_live:
        if row:
            db.live_pill_remove(message.id)
        return sec

    if row:
        db.live_pill_touch(
            message.id,
            last_price=sec.last,
            # Manual Refresh extends TTL; background poll only updates last.
            extend_seconds=LIVE_PILL_TTL_SEC if extend_live else None,
        )
    else:
        # Row missing (TTL expired) — Refresh or poll restart re-registers.
        guild_id = message.guild.id if message.guild else 0
        if guild_id:
            db.live_pill_register(
                message_id=message.id,
                channel_id=message.channel.id,
                guild_id=guild_id,
                symbol=sec.yahoo,
                last_price=sec.last,
                ttl_seconds=LIVE_PILL_TTL_SEC,
                max_active=LIVE_PILL_MAX,
                expanded=expanded,
            )
    return sec


async def set_ticker_pill_expanded(
    message: discord.Message,
    symbol: str,
    *,
    expanded: bool,
) -> Security | None:
    """Expand / collapse in place; keep live registration + last price."""
    row = db.live_pill_get(message.id)
    previous = float(row["last_price"]) if row and row["last_price"] is not None else None
    sec = await asyncio.to_thread(get_security, symbol)
    await message.edit(
        view=TickerPill(sec, previous_last=previous, live=True, expanded=expanded)
    )
    if row:
        db.live_pill_set_expanded(message.id, expanded)
        db.live_pill_touch(message.id, last_price=sec.last, extend_seconds=LIVE_PILL_TTL_SEC)
    return sec
