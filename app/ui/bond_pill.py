from __future__ import annotations

import discord
from discord import ui

from app import format as fmt
from app.market.bonds import BondQuote, bond_card_text, bond_links


class BondPill(ui.LayoutView):
    def __init__(self, bond: BondQuote, *, timeout: float | None = 600) -> None:
        super().__init__(timeout=timeout)
        links = [
            ui.Button(style=discord.ButtonStyle.link, label=label, url=url)
            for label, url in bond_links(bond)[:5]
        ]
        children: list[ui.Item] = [
            ui.TextDisplay(bond_card_text(bond)),
            ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
        ]
        if links:
            children.append(ui.ActionRow(*links))
        self.add_item(
            ui.Container(
                *children,
                accent_colour=fmt.accent(bond.price_change),
            )
        )
