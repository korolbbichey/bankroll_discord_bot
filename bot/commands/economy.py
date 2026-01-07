"""
Economy commands for the BankRoll Discord Bot.
"""

import discord
from discord import app_commands
import asyncio
import json

from ..config import STARTING_BALANCE, DAILY_REWARD
from ..database import get_balance, get_leaderboard, claim_daily_reward, get_user_profile


def setup(client):
    """Setup economy commands."""

    @client.tree.command(name="balance", description="Check your virtual currency balance")
    async def balance(interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        user_balance = get_balance(user_id)
        await interaction.response.defer(thinking=True)
        await asyncio.sleep(0.5)
        await interaction.followup.send(f"{interaction.user.name}, your balance is 💰 {user_balance}")

    @client.tree.command(name="daily_reward", description="Claim your daily reward")
    async def daily_reward(interaction: discord.Interaction):
        user_id = str(interaction.user.id)
        success, new_balance, message = claim_daily_reward(user_id)

        if success:
            await interaction.response.send_message(f"✅ {message} Your new balance is 💰 {new_balance}.", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ {message}", ephemeral=True)

    @client.tree.command(name="leaderboard", description="Show the top users with the most virtual currency")
    async def leaderboard(interaction: discord.Interaction):
        rows = get_leaderboard(5)

        if not rows:
            await interaction.response.send_message("No currency data available yet.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🏆 Leaderboard — Top Richest Players",
            description="Here are the top 5 users with the highest balance!",
            color=discord.Color.gold()
        )

        for i, (user_id, user_balance) in enumerate(rows, start=1):
            try:
                user = await client.fetch_user(int(user_id))
                embed.add_field(
                    name=f"{i}. {user.name}",
                    value=f"💰 {user_balance} coins",
                    inline=False
                )
            except discord.NotFound:
                embed.add_field(
                    name=f"{i}. Unknown User ({user_id})",
                    value=f"💰 {user_balance} coins",
                    inline=False
                )

        await interaction.response.send_message(embed=embed)

    @client.tree.command(name="profile", description="View your game stats and balance")
    @app_commands.describe(user="The user to view (leave empty for yourself)")
    async def profile(interaction: discord.Interaction, user: discord.User = None):
        target = user or interaction.user
        uid = target.id

        profile_data = get_user_profile(uid)
        balance = profile_data["balance"]
        stats_row = profile_data["stats"]
        blackjack_row = profile_data["blackjack"]

        if not stats_row:
            await interaction.response.send_message(f"{target.name} hasn't played any games yet!", ephemeral=True)
            return

        games, wins, losses, total_earned, most_common_symbol, largest_win = stats_row
        blackjack_wins, blackjack_losses, blackjack_total_earned, blackjack_largest_win = blackjack_row
        win_rate = (wins / games * 100) if games > 0 else 0

        try:
            most_common = json.loads(most_common_symbol)
            most_common_sorted = sorted(most_common.items(), key=lambda x: x[1], reverse=True)
            common_symbol_text = most_common_sorted[0][0] if most_common_sorted else "N/A"
        except Exception:
            common_symbol_text = most_common_symbol if most_common_symbol else "N/A"

        embed = discord.Embed(
            title=f"{target.name}'s Game Stats 🎮",
            color=discord.Color.gold()
        )
        embed.set_thumbnail(url=target.display_avatar.url)

        # General stats
        embed.add_field(name="💰 Balance", value=str(balance), inline=True)
        embed.add_field(name="🎮 Games Played", value=str(games), inline=True)
        embed.add_field(name="✅ Wins", value=str(wins), inline=True)
        embed.add_field(name="❌ Losses", value=str(losses), inline=True)
        embed.add_field(name="📈 Win Rate", value=f"{win_rate:.2f}%", inline=True)
        embed.add_field(name="💸 Total Earned", value=str(total_earned), inline=True)
        embed.add_field(name="⭐ Most Common Symbol", value=common_symbol_text, inline=True)
        embed.add_field(name="🏆 Largest Win", value=str(largest_win), inline=True)

        embed.add_field(name="\u200b", value="\u200b", inline=False)

        # Blackjack stats
        embed.add_field(name="♠️ Blackjack Wins", value=str(blackjack_wins), inline=True)
        embed.add_field(name="♦️ Blackjack Losses", value=str(blackjack_losses), inline=True)
        embed.add_field(name="💵 Blackjack Total Earned", value=str(blackjack_total_earned), inline=True)
        embed.add_field(name="🎯 Blackjack Largest Win", value=str(blackjack_largest_win), inline=True)

        await interaction.response.send_message(embed=embed)
