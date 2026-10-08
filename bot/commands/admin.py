"""
Admin commands for the BankRoll Discord Bot.

Balances are global across every server the bot is in, so these commands are
restricted to the bot owner(s), not to server administrators. They are only
registered in ADMIN_GUILD_ID, so nobody else even sees them.
"""

import logging

import discord
from discord import app_commands

from ..config import OWNER_IDS, ADMIN_GUILD_ID
from ..database import credit, try_debit, get_balance, set_balance

logger = logging.getLogger(__name__)

Amount = app_commands.Range[int, 1, 1_000_000_000]


def setup(client):
    """Setup admin commands."""
    if ADMIN_GUILD_ID is None:
        logger.warning("ADMIN_GUILD_ID is not set, /admin commands are disabled.")
        return

    admin = app_commands.Group(
        name="admin",
        description="Bot owner tools",
        guild_ids=[ADMIN_GUILD_ID],
        default_permissions=discord.Permissions(administrator=True),
    )

    @admin.command(name="give", description="Add coins to a player")
    @app_commands.describe(user="Player", amount="Amount to add")
    async def give(interaction: discord.Interaction, user: discord.User, amount: Amount):
        new_balance = credit(user.id, amount)
        logger.info("%s gave %d to %s", interaction.user, amount, user.id)
        await interaction.response.send_message(f"✅ Gave 💰 {amount} to {user.mention}. New balance: 💰 {new_balance}", ephemeral=True)

    @admin.command(name="take", description="Remove coins from a player")
    @app_commands.describe(user="Player", amount="Amount to remove")
    async def take(interaction: discord.Interaction, user: discord.User, amount: Amount):
        if not try_debit(user.id, amount):
            await interaction.response.send_message(f"❌ {user.mention} only has 💰 {get_balance(user.id)}.", ephemeral=True)
            return
        logger.info("%s took %d from %s", interaction.user, amount, user.id)
        await interaction.response.send_message(f"✅ Took 💰 {amount} from {user.mention}. New balance: 💰 {get_balance(user.id)}", ephemeral=True)

    @admin.command(name="set", description="Set a player's balance to an exact amount")
    @app_commands.describe(user="Player", amount="New balance")
    async def set_(interaction: discord.Interaction, user: discord.User, amount: app_commands.Range[int, 0, 1_000_000_000]):
        set_balance(user.id, amount)
        logger.info("%s set balance of %s to %d", interaction.user, user.id, amount)
        await interaction.response.send_message(f"✅ {user.mention}'s balance is now 💰 {amount}", ephemeral=True)

    async def owner_only(interaction: discord.Interaction) -> bool:
        # A False result raises CheckFailure, which the tree error handler reports to the user.
        return interaction.user.id in OWNER_IDS or await client.is_owner(interaction.user)

    admin.interaction_check = owner_only
    client.tree.add_command(admin)
