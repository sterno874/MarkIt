"""Unified reply target for slash `/markit` and chat `@MarkIt …`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import discord


@dataclass
class DeskCtx:
    guild_id: int | None
    channel_id: int | None
    user_id: int
    guild: discord.Guild | None
    user: discord.abc.User | discord.Member
    channel: discord.abc.Messageable
    interaction: discord.Interaction | None = None
    message: discord.Message | None = None

    @classmethod
    def from_interaction(cls, interaction: discord.Interaction) -> DeskCtx:
        return cls(
            guild_id=interaction.guild_id,
            channel_id=interaction.channel_id,
            user_id=interaction.user.id,
            guild=interaction.guild,
            user=interaction.user,
            channel=interaction.channel or interaction.user,
            interaction=interaction,
        )

    @classmethod
    def from_message(cls, message: discord.Message) -> DeskCtx:
        return cls(
            guild_id=message.guild.id if message.guild else None,
            channel_id=message.channel.id,
            user_id=message.author.id,
            guild=message.guild,
            user=message.author,
            channel=message.channel,
            message=message,
        )

    async def send(
        self,
        content: str | None = None,
        *,
        embed: discord.Embed | None = None,
        file: discord.File | None = None,
        files: list[discord.File] | None = None,
        view: discord.ui.View | None = None,
        ephemeral: bool = False,
    ) -> discord.Message | None:
        kwargs: dict[str, Any] = {}
        if content is not None:
            kwargs["content"] = content
        if embed is not None:
            kwargs["embed"] = embed
        if view is not None:
            kwargs["view"] = view
        if file is not None:
            kwargs["file"] = file
        if files is not None:
            kwargs["files"] = files

        if self.interaction is not None:
            kwargs["ephemeral"] = ephemeral
            if self.interaction.response.is_done():
                msg = await self.interaction.followup.send(**kwargs, wait=True)
                return msg if isinstance(msg, discord.Message) else None
            await self.interaction.response.send_message(**kwargs)
            return await self.interaction.original_response()

        # Chat @mention path — reply in-thread when possible.
        if self.message is not None:
            try:
                return await self.message.reply(**kwargs, mention_author=False)
            except discord.HTTPException:
                pass
        return await self.channel.send(**kwargs)

    @property
    def destination(self) -> discord.abc.Messageable | discord.Interaction:
        """For helpers that already accept Interaction | Messageable."""
        if self.interaction is not None:
            return self.interaction
        return self.channel
