"""Send a bond card — LayoutView first, embed fallback so Discord always gets a reply."""

from __future__ import annotations

import logging

import discord

from app.market.bonds import BondQuote, bond_card_text, bond_links
from app.ui.bond_pill import BondPill
from app.ui.pill import simple_embed

log = logging.getLogger("market-desk.bond")


def bond_embed(bond: BondQuote) -> discord.Embed:
    lines = [bond_card_text(bond)]
    links = bond_links(bond)
    if links:
        lines.append("")
        lines.append(" · ".join(f"[{label}]({url})" for label, url in links[:5]))
    return simple_embed(f"{bond.display} · Bond", "\n".join(lines), colour=0xF39C12)


async def send_bond_card(
    destination: discord.abc.Messageable | discord.Interaction,
    bond: BondQuote,
    *,
    ephemeral: bool = False,
) -> None:
    view = BondPill(bond)
    try:
        if isinstance(destination, discord.Interaction):
            if destination.response.is_done():
                await destination.followup.send(view=view, ephemeral=ephemeral)
            else:
                await destination.response.send_message(view=view, ephemeral=ephemeral)
        else:
            await destination.send(view=view)
        return
    except Exception as exc:
        log.warning("BondPill send failed (%s); falling back to embed", exc)

    embed = bond_embed(bond)
    if isinstance(destination, discord.Interaction):
        if destination.response.is_done():
            await destination.followup.send(embed=embed, ephemeral=ephemeral)
        else:
            await destination.response.send_message(embed=embed, ephemeral=ephemeral)
    else:
        await destination.send(embed=embed)
