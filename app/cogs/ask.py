from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from app.db import db
from app.services import gemini
from app.services.dispatch import run_blocking
from app.ui.pill import simple_embed


class Ask(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="ask", description="Ask Gemini about markets (needs GEMINI_API_KEY)")
    async def ask(self, interaction: discord.Interaction, question: str) -> None:
        if not gemini.available():
            await interaction.response.send_message(
                "Add `GEMINI_API_KEY` to `.env` and restart the bot to enable `/ask`.",
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        context = None
        if interaction.guild_id and interaction.channel_id:
            last = db.get_last_ticker(interaction.guild_id, interaction.channel_id)
            if last:
                context = f"Last ticker discussed in this channel: {last}"
        try:
            answer = await run_blocking(gemini.ask, question, context=context)
        except Exception as exc:
            await interaction.followup.send(f"Gemini error: {exc}", ephemeral=True)
            return
        await interaction.followup.send(embed=simple_embed("Ask", answer[:4000]))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Ask(bot))
