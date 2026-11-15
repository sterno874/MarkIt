from __future__ import annotations

import json
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from app.autocomplete import suggest_bug_commands
from app.db import db
from app.services import gemini
from app.ui.pill import simple_embed

Severity = Literal["low", "normal", "high", "critical"]
Status = Literal["open", "claimed", "fixed", "closed", "wontfix", "all"]


def format_ticket(row) -> str:  # type: ignore[no-untyped-def]
    bits = [
        f"**Status:** `{row['status']}` · **Severity:** `{row['severity']}`",
        f"**Reporter:** <@{row['user_id']}>",
    ]
    if row["command"]:
        bits.append(f"**Command / area:** `{row['command']}`")
    if row["assignee_id"]:
        bits.append(f"**Assignee:** <@{row['assignee_id']}>")
    bits.append("")
    bits.append(row["description"])
    if row["resolution"]:
        bits.append("")
        bits.append(f"**Resolution:** {row['resolution']}")
    bits.append("")
    bits.append(f"_Ticket file:_ `data/tickets/{row['id']:05d}.json`")
    return "\n".join(bits)


class Bugs(commands.Cog):
    """Structured bug tickets for the community — agent-friendly JSON on disk."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    bugs = app_commands.Group(name="bugs", description="List and manage Market Desk tickets")

    async def _post_ticket_card(
        self,
        interaction: discord.Interaction,
        ticket_id: int,
        *,
        title: str | None = None,
    ) -> discord.Message | None:
        row = db.bug_get(ticket_id)
        if not row:
            return None
        embed = simple_embed(
            title or f"Bug #{ticket_id} · {row['status']}",
            format_ticket(row),
            colour=0xE67E22 if row["status"] == "open" else 0x95A5A6,
        )
        channel = await self._bugs_channel(interaction)
        if channel is None:
            return None
        return await channel.send(embed=embed)

    async def _bugs_channel(self, interaction: discord.Interaction) -> discord.TextChannel | None:
        if not interaction.guild:
            return None
        raw = db.get_setting(interaction.guild.id, "bugs_channel_id")
        if not raw:
            return None
        channel = interaction.guild.get_channel(int(raw))
        return channel if isinstance(channel, discord.TextChannel) else None

    @app_commands.command(name="bug", description="Report a Market Desk bug / broken command")
    @app_commands.describe(
        description="What broke? Include the ticker or command if you can.",
        command="Optional: chart, quote, bond, alert, ask…",
        severity="How bad is it?",
    )
    async def bug(
        self,
        interaction: discord.Interaction,
        description: str,
        command: str | None = None,
        severity: Severity = "normal",
    ) -> None:
        await self._create(interaction, description, command, severity)

    @app_commands.command(name="report-bug", description="Alias for /bug")
    async def report_bug(
        self,
        interaction: discord.Interaction,
        description: str,
        command: str | None = None,
        severity: Severity = "normal",
    ) -> None:
        await self._create(interaction, description, command, severity)

    async def _create(
        self,
        interaction: discord.Interaction,
        description: str,
        command: str | None,
        severity: Severity,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Use this in a server.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        context = {
            "channel_id": interaction.channel_id,
            "guild_id": interaction.guild_id,
            "user": str(interaction.user),
            "last_ticker": db.get_last_ticker(interaction.guild.id, interaction.channel_id or 0),
        }
        ticket_id = db.bug_create(
            guild_id=interaction.guild.id,
            channel_id=interaction.channel_id or 0,
            user_id=interaction.user.id,
            description=description.strip(),
            command=(command or "").strip().lower() or None,
            severity=severity,
            context=context,
        )
        summary = description
        if gemini.available():
            try:
                summary = await discord.utils.maybe_coroutine(
                    gemini.summarize_bug, description, command, context
                )
            except Exception:
                summary = description

        msg = await self._post_ticket_card(
            interaction,
            ticket_id,
            title=f"Bug #{ticket_id} · open",
        )
        if msg:
            db.bug_update(ticket_id, message_id=msg.id)
            # Enrich the posted card with Gemini summary when available.
            if summary and summary != description:
                embed = simple_embed(
                    f"Bug #{ticket_id} · open",
                    format_ticket(db.bug_get(ticket_id)) + f"\n\n**Triage notes:**\n{summary[:1500]}",
                    colour=0xE67E22,
                )
                await msg.edit(embed=embed)

        await interaction.followup.send(
            f"Logged **bug #{ticket_id}**. "
            + (
                f"Posted in {msg.channel.mention}."
                if msg
                else "Set a channel with `/bugs channel` so the whole desk can see tickets."
            ),
            ephemeral=True,
        )

    @bugs.command(name="channel", description="Set the channel where bug tickets are posted")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def bugs_channel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Server only.", ephemeral=True)
            return
        db.set_setting(interaction.guild.id, "bugs_channel_id", str(channel.id))
        await interaction.response.send_message(
            f"Bug tickets will post in {channel.mention}.", ephemeral=True
        )

    @bugs.command(name="list", description="List bug tickets")
    async def bugs_list(
        self,
        interaction: discord.Interaction,
        status: Status = "open",
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Server only.", ephemeral=True)
            return
        rows = db.bug_list(guild_id=interaction.guild.id, status=status, limit=20)
        if not rows:
            await interaction.response.send_message(f"No `{status}` tickets.", ephemeral=True)
            return
        lines = [
            f"#{r['id']} `{r['status']}`/{r['severity']} — {(r['command'] or 'general')}: "
            f"{r['description'][:80]}"
            for r in rows
        ]
        await interaction.response.send_message(
            embed=simple_embed(f"Bugs · {status}", "\n".join(lines)),
            ephemeral=True,
        )

    @bugs.command(name="show", description="Show one ticket")
    async def bugs_show(self, interaction: discord.Interaction, id: app_commands.Range[int, 1, 1_000_000]) -> None:
        row = db.bug_get(id)
        if not row or (interaction.guild and row["guild_id"] != interaction.guild.id):
            await interaction.response.send_message("Ticket not found.", ephemeral=True)
            return
        await interaction.response.send_message(
            embed=simple_embed(f"Bug #{id}", format_ticket(row)),
            ephemeral=True,
        )

    @bugs.command(name="claim", description="Claim a ticket (you or an automation bot)")
    async def bugs_claim(
        self,
        interaction: discord.Interaction,
        id: app_commands.Range[int, 1, 1_000_000],
    ) -> None:
        row = db.bug_get(id)
        if not row:
            await interaction.response.send_message("Ticket not found.", ephemeral=True)
            return
        db.bug_update(id, status="claimed", assignee_id=interaction.user.id)
        await interaction.response.send_message(f"Claimed **bug #{id}**.", ephemeral=True)
        await self._refresh_card(interaction, id)

    @bugs.command(name="resolve", description="Mark a ticket fixed / closed")
    async def bugs_resolve(
        self,
        interaction: discord.Interaction,
        id: app_commands.Range[int, 1, 1_000_000],
        note: str,
        status: Literal["fixed", "closed", "wontfix"] = "fixed",
    ) -> None:
        row = db.bug_get(id)
        if not row:
            await interaction.response.send_message("Ticket not found.", ephemeral=True)
            return
        db.bug_update(id, status=status, resolution=note, assignee_id=interaction.user.id)
        await interaction.response.send_message(f"Bug #{id} → `{status}`.", ephemeral=True)
        await self._refresh_card(interaction, id)

    @bugs.command(
        name="pickup",
        description="Export open tickets as JSON for an agent / autofix loop",
    )
    async def bugs_pickup(
        self,
        interaction: discord.Interaction,
        limit: app_commands.Range[int, 1, 50] = 10,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Server only.", ephemeral=True)
            return
        rows = db.bug_list(guild_id=interaction.guild.id, status="open", limit=limit)
        claimed = db.bug_list(guild_id=interaction.guild.id, status="claimed", limit=limit)
        payload = []
        for row in [*rows, *claimed][:limit]:
            payload.append({k: row[k] for k in row.keys()})
            if row["status"] == "open":
                db.bug_update(row["id"], status="claimed", assignee_id=interaction.user.id)
        text = json.dumps(payload, indent=2)
        if len(text) > 1900:
            from io import BytesIO

            await interaction.response.send_message(
                content=f"Picked up {len(payload)} ticket(s). JSON attached.",
                file=discord.File(BytesIO(text.encode()), filename="bugs-pickup.json"),
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"Picked up {len(payload)} ticket(s):\n```json\n{text}\n```",
                ephemeral=True,
            )

    async def _refresh_card(self, interaction: discord.Interaction, ticket_id: int) -> None:
        row = db.bug_get(ticket_id)
        if not row or not row["message_id"]:
            return
        channel = await self._bugs_channel(interaction)
        if not channel:
            return
        try:
            msg = await channel.fetch_message(int(row["message_id"]))
            await msg.edit(
                embed=simple_embed(
                    f"Bug #{ticket_id} · {row['status']}",
                    format_ticket(row),
                    colour=0x2ECC71 if row["status"] in {"fixed", "closed"} else 0xE67E22,
                )
            )
        except discord.HTTPException:
            pass


async def setup(bot: commands.Bot) -> None:
    cog = Bugs(bot)
    await bot.add_cog(cog)
    cog.bug.autocomplete("command")(suggest_bug_commands)
    cog.report_bug.autocomplete("command")(suggest_bug_commands)
