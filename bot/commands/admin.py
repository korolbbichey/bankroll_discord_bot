"""
Admin commands for the BankRoll Discord Bot.

Balances are global across every server the bot is in, so these commands are
restricted to the bot owner(s), not to server administrators.
"""

import discord
from discord import app_commands

from ..config import OWNER_IDS
from ..database import credit, try_debit, get_balance


def setup(client):
    """Setup admin commands."""

    async def is_bot_owner(interaction: discord.Interaction) -> bool:
        if interaction.user.id in OWNER_IDS or await client.is_owner(interaction.user):
            return True
        await interaction.response.send_message("❌ Only the bot owner can use this command.", ephemeral=True)
        return False

    @client.tree.command(name="add_balance", description="(Owner) Add virtual currency to a player's balance")
    @app_commands.describe(user="The user to add balance to", amount="Amount to add")
    @app_commands.default_permissions(administrator=True)
    async def add_balance(interaction: discord.Interaction, user: discord.User, amount: app_commands.Range[int, 1, 1_000_000]):
        if not await is_bot_owner(interaction):
            return

        new_balance = credit(user.id, amount)
        await interaction.response.send_message(
            f"✅ Added 💰 {amount} to {user.name}'s balance. New balance: 💰 {new_balance}", ephemeral=True
        )

    @client.tree.command(name="remove_balance", description="(Owner) Remove virtual currency from a player's balance")
    @app_commands.describe(user="The user to remove balance from", amount="Amount to remove")
    @app_commands.default_permissions(administrator=True)
    async def remove_balance(interaction: discord.Interaction, user: discord.User, amount: app_commands.Range[int, 1, 1_000_000]):
        if not await is_bot_owner(interaction):
            return

        if not try_debit(user.id, amount):
            await interaction.response.send_message(
                f"❌ {user.name} only has 💰 {get_balance(user.id)}.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"✅ Removed 💰 {amount} from {user.name}'s balance. New balance: 💰 {get_balance(user.id)}", ephemeral=True
        )
