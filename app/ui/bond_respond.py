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
    interaction: discord.Interaction,
    bond: BondQuote,
    *,
    ephemeral: bool = False,
) -> None:
    try:
        await interaction.followup.send(view=BondPill(bond), ephemeral=ephemeral)
        return
    except Exception as exc:
        log.warning("BondPill send failed (%s); falling back to embed", exc)
    await interaction.followup.send(embed=bond_embed(bond), ephemeral=ephemeral)
