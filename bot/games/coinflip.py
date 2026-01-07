"""
Coinflip game for the BankRoll Discord Bot.
"""

import discord
from discord import app_commands
import random
import asyncio

from ..database import get_balance, update_balance
from ..utils import validate_bet


def setup(client):
    """Setup coinflip command."""

    @client.tree.command(name="coinflip", description="Flip a coin and win double your bet if you guess right!")
    @app_commands.describe(guess="Your guess - heads or tails", bet="Amount to bet (1-10000)")
    @app_commands.choices(guess=[
        app_commands.Choice(name="Heads", value="heads"),
        app_commands.Choice(name="Tails", value="tails")
    ])
    async def coinflip(interaction: discord.Interaction, guess: app_commands.Choice[str], bet: int):
        user_id = str(interaction.user.id)
        guess_value = guess.value

        balance = get_balance(user_id)
        is_valid, error_msg = validate_bet(bet, balance)
        if not is_valid:
            await interaction.response.send_message(f"❌ {error_msg}", ephemeral=True)
            return

        embed = discord.Embed(
            title="🪙 Coin Flip!",
            description="Flipping the coin...",
            color=discord.Color.random()
        )
        embed.set_footer(text="You guessed: " + guess_value.capitalize())
        await interaction.response.send_message(embed=embed)
        message = await interaction.original_response()

        flip_sequence = ["Heads 🟤", "Tails ⚪", "Heads 🟤", "Tails ⚪", "Heads 🟤", "Tails ⚪"]
        for flip in flip_sequence:
            embed.description = f"Flipping the coin...\n**{flip}**"
            await message.edit(embed=embed)
            await asyncio.sleep(0.5)

        outcome = random.choice(["heads", "tails"])
        emoji = "🟤" if outcome == "heads" else "⚪"
        win = guess_value == outcome

        if win:
            update_balance(user_id, balance + bet)
            result = f"🎉 It landed on **{outcome.capitalize()} {emoji}**!\nYou win **{bet}** coins!"
        else:
            update_balance(user_id, balance - bet)
            result = f"😢 It landed on **{outcome.capitalize()} {emoji}**!\nYou lost **{bet}** coins."

        embed.title = "🪙 Coin Flip Result"
        embed.description = result + f"\n\n💰 New Balance: **{get_balance(user_id)}**"
        embed.color = discord.Color.green() if win else discord.Color.red()

        await message.edit(embed=embed)
