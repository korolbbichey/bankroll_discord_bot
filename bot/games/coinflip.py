"""
Coinflip game for the BankRoll Discord Bot.
"""

import discord
from discord import app_commands
import random
import asyncio

from ..config import MIN_BET, MAX_BET
from ..database import get_balance, try_debit, credit, update_stats
from ..utils import validate_bet


def setup(client):
    """Setup coinflip command."""

    @client.tree.command(name="coinflip", description="Flip a coin and win double your bet if you guess right!")
    @app_commands.describe(guess="Your guess - heads or tails", bet=f"Amount to bet ({MIN_BET}-{MAX_BET})")
    @app_commands.choices(guess=[
        app_commands.Choice(name="Heads", value="heads"),
        app_commands.Choice(name="Tails", value="tails")
    ])
    async def coinflip(interaction: discord.Interaction, guess: app_commands.Choice[str], bet: int):
        user_id = interaction.user.id
        guess_value = guess.value

        is_valid, error_msg = validate_bet(bet, get_balance(user_id))
        if not is_valid or not try_debit(user_id, bet):
            await interaction.response.send_message(f"❌ {error_msg or 'You do not have enough balance for that bet.'}", ephemeral=True)
            return

        # The bet is already taken, so decide and pay out before any Discord calls that could fail.
        outcome = random.choice(["heads", "tails"])
        win = guess_value == outcome
        payout = bet * 2 if win else 0
        new_balance = credit(user_id, payout) if win else get_balance(user_id)
        update_stats(user_id, payout, bet)

        embed = discord.Embed(
            title="🪙 Coin Flip!",
            description="Flipping the coin...",
            color=discord.Color.random()
        )
        embed.set_footer(text="You guessed: " + guess_value.capitalize())
        await interaction.response.send_message(embed=embed)

        for flip in ["Heads 🟤", "Tails ⚪", "Heads 🟤", "Tails ⚪"]:
            embed.description = f"Flipping the coin...\n**{flip}**"
            await interaction.edit_original_response(embed=embed)
            await asyncio.sleep(0.5)

        emoji = "🟤" if outcome == "heads" else "⚪"
        if win:
            result = f"🎉 It landed on **{outcome.capitalize()} {emoji}**!\nYou win **{bet}** coins!"
        else:
            result = f"😢 It landed on **{outcome.capitalize()} {emoji}**!\nYou lost **{bet}** coins."

        embed.title = "🪙 Coin Flip Result"
        embed.description = result + f"\n\n💰 New Balance: **{new_balance}**"
        embed.color = discord.Color.green() if win else discord.Color.red()
        await interaction.edit_original_response(embed=embed)
