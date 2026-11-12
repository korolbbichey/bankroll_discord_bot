"""
/feedback for the BankRoll Discord Bot: players send ideas and bug reports to the developer.

Each message is saved first, then sent to the bot owner(s) as a DM, so nothing is lost if a DM fails
(the owner needs a server in common with the bot and DMs from server members allowed).
The owner can read the latest ones with /admin feedback.
"""

import logging

import discord
from discord import app_commands

from ..config import OWNER_IDS
from ..database import save_feedback
from ..utils import display_name

logger = logging.getLogger(__name__)

FEEDBACK_COOLDOWN = 300  # seconds between two messages from one player
KINDS = {"idea": "💡 Idea", "bug": "🐞 Bug", "other": "💬 Other"}
KIND_COLORS = {"idea": discord.Color.gold(), "bug": discord.Color.red(), "other": discord.Color.blurple()}


def place_of(interaction: discord.Interaction) -> str:
    """Where the command was used, for the owner."""
    if interaction.guild:
        return interaction.guild.name
    if interaction.guild_id:
        return f"a server without the bot ({interaction.guild_id})"
    return "DMs"


async def owner_ids(client: discord.Client) -> set[int]:
    """OWNER_IDS plus the application owner (or every team member) from the Developer Portal."""
    ids = set(OWNER_IDS)
    try:
        app = await client.application_info()
        ids |= {member.id for member in app.team.members} if app.team else {app.owner.id}
    except discord.HTTPException:
        logger.exception("Failed to look up the application owner")
    return ids


def feedback_embed(number: int, kind: str, message: str, user: discord.abc.User, place: str) -> discord.Embed:
    embed = discord.Embed(title=f"{KINDS[kind]} #{number}", description=message, color=KIND_COLORS[kind])
    embed.add_field(name="From", value=f"{display_name(user)} (`{user.id}`)", inline=True)
    embed.add_field(name="Where", value=place, inline=True)
    return embed


def setup(client):
    """Setup the feedback command."""

    @client.tree.command(name="feedback", description="Send an idea or a bug report to the developer")
    @app_commands.describe(kind="What it is", message="Your idea, the bug you found, or anything else")
    @app_commands.choices(kind=[app_commands.Choice(name=name, value=value) for value, name in KINDS.items()])
    async def feedback(interaction: discord.Interaction, kind: app_commands.Choice[str],
                       message: app_commands.Range[str, 5, 1000]):
        place = place_of(interaction)
        number = save_feedback(interaction.user.id, display_name(interaction.user), kind.value, place, message,
                               FEEDBACK_COOLDOWN)
        if number is None:
            await interaction.response.send_message(
                "⏳ You just sent feedback. You can send more in a few minutes.", ephemeral=True)
            return
        await interaction.response.send_message(
            "✅ Thanks! Your feedback was sent to the developer.", ephemeral=True)

        embed = feedback_embed(number, kind.value, message, interaction.user, place)
        for owner_id in await owner_ids(client):
            try:
                owner = client.get_user(owner_id) or await client.fetch_user(owner_id)
                await owner.send(embed=embed)
            except discord.HTTPException:
                logger.warning("Couldn't DM feedback #%d to %d; it's saved for /admin feedback", number, owner_id)
