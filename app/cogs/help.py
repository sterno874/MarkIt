from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from app.autocomplete import suggest_help_topics
from app.help_text import HELP_OVERVIEW, HELP_TOPICS, topic_list
from app.ui.pill import simple_embed


class Help(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="help", description="How to use Market Desk")
    @app_commands.describe(topic=f"Optional topic: {', '.join(HELP_TOPICS)}")
    async def help_cmd(self, interaction: discord.Interaction, topic: str | None = None) -> None:
        if topic:
            key = topic.lower().strip()
            body = HELP_TOPICS.get(key)
            if not body:
                await interaction.response.send_message(
                    f"Unknown topic `{topic}`. Try: {topic_list()}",
                    ephemeral=True,
                )
                return
            await interaction.response.send_message(
                embed=simple_embed(f"Help · {key}", body),
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            embed=simple_embed("Market Desk", HELP_OVERVIEW + f"\n\nTopics: {topic_list()}"),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    cog = Help(bot)
    await bot.add_cog(cog)
    cog.help_cmd.autocomplete("topic")(suggest_help_topics)
