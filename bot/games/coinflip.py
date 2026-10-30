"""
Coinflip game for the BankRoll Discord Bot.
"""

import discord
from discord import app_commands
import random
import asyncio
import io
import logging

from ..coinflip_gif import animation_seconds, render_flip_gif
from ..config import RESULT_DELAY_MARGIN
from ..database import get_balance, try_debit, credit, update_stats
from ..utils import validate_bet, fmt, Bet, DRAW_SLOTS
from ..progression import track_game, send_notice

logger = logging.getLogger(__name__)

GIF_NAME = "flip.gif"


def setup(client):
    """Setup coinflip command."""

    @client.tree.command(name="coinflip", description="Flip a coin and win double your bet if you guess right!")
    @app_commands.describe(guess="Your guess - heads or tails", bet="Coins to bet: a number, all or half")
    @app_commands.choices(guess=[
        app_commands.Choice(name="Heads", value="heads"),
        app_commands.Choice(name="Tails", value="tails")
    ])
    async def coinflip(interaction: discord.Interaction, guess: app_commands.Choice[str], bet: Bet):
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
        progress = track_game(user_id, "coinflip", bet, payout)

        # Drawing and uploading can take longer than Discord's 3 seconds.
        await interaction.response.defer()

        embed = discord.Embed(title="🪙 Flipping...", color=discord.Color.blurple())
        embed.set_footer(text=f"You guessed: {guess_value.capitalize()} • Bet: {fmt(bet)}")
        try:
            async with DRAW_SLOTS:
                gif = await asyncio.to_thread(render_flip_gif, outcome, guess_value, bet)
            embed.set_image(url=f"attachment://{GIF_NAME}")
            await interaction.edit_original_response(
                embed=embed, attachments=[discord.File(io.BytesIO(gif), filename=GIF_NAME)]
            )
            await asyncio.sleep(animation_seconds(win) + RESULT_DELAY_MARGIN)
        except Exception:
            # The game is already settled, so the player just gets the result without the animation.
            logger.exception("Coinflip animation failed, sending the result as text")
            embed = discord.Embed()
            embed.set_footer(text=f"You guessed: {guess_value.capitalize()} • Bet: {fmt(bet)}")

        emoji = "🟤" if outcome == "heads" else "⚪"
        embed.title = "🎉 You won!" if win else "😢 You lost"
        embed.description = (
            f"It landed on **{outcome.capitalize()} {emoji}**\n"
            f"{'You win' if win else 'You lost'} **{fmt(bet)}** coins • 💰 Balance: **{fmt(new_balance)}**"
        )
        embed.color = discord.Color.green() if win else discord.Color.red()
        await interaction.edit_original_response(embed=embed)
        await send_notice(interaction, progress)
