"""
Admin commands for the BankRoll Discord Bot.
"""

import discord
from discord import app_commands

from ..database import get_balance, update_balance


def setup(client):
    """Setup admin commands."""

    @client.tree.command(name="add_balance", description="Manually add virtual currency to a player's balance")
    @app_commands.describe(user="The user to add balance to", amount="Amount to add")
    async def add_balance(interaction: discord.Interaction, user: discord.User, amount: int):
        # Check admin permission first
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
            return

        if amount <= 0:
            await interaction.response.send_message("❌ Amount must be positive!", ephemeral=True)
            return

        user_id = user.id
        current_balance = get_balance(user_id)
        new_balance = current_balance + amount
        update_balance(user_id, new_balance)

        await interaction.response.send_message(
            f"✅ Successfully added 💰 {amount} to {user.name}'s balance. New balance: 💰 {new_balance}"
        )
