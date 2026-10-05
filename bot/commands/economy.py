"""
Economy commands for the BankRoll Discord Bot.
"""

import discord
from discord import app_commands

from ..database import get_balance, get_leaderboard, claim_daily_reward, get_user_profile


def setup(client):
    """Setup economy commands."""

    @client.tree.command(name="balance", description="Check your virtual currency balance")
    async def balance(interaction: discord.Interaction):
        user_balance = get_balance(interaction.user.id)
        await interaction.response.send_message(f"{interaction.user.name}, your balance is 💰 {user_balance}")

    @client.tree.command(name="daily_reward", description="Claim your daily reward")
    async def daily_reward(interaction: discord.Interaction):
        success, new_balance, message = claim_daily_reward(interaction.user.id)

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

        # Fetching uncached users can take a while; defer so the interaction doesn't expire.
        await interaction.response.defer()

        embed = discord.Embed(
            title="🏆 Leaderboard — Top Richest Players",
            description="Here are the top 5 users with the highest balance!",
            color=discord.Color.gold()
        )

        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        for i, (user_id, user_balance) in enumerate(rows, start=1):
            user = client.get_user(user_id)
            if user is None:
                try:
                    user = await client.fetch_user(user_id)
                except discord.HTTPException:
                    user = None
            name = user.name if user else f"Unknown User ({user_id})"
            embed.add_field(name=f"{medals.get(i, f'{i}.')} {name}", value=f"💰 {user_balance} coins", inline=False)

        await interaction.followup.send(embed=embed)

    @client.tree.command(name="profile", description="View your game stats and balance")
    @app_commands.describe(user="The user to view (leave empty for yourself)")
    async def profile(interaction: discord.Interaction, user: discord.User = None):
        target = user or interaction.user

        profile_data = get_user_profile(target.id)
        stats_row = profile_data["stats"]
        blackjack_row = profile_data["blackjack"]

        if not stats_row and not blackjack_row:
            await interaction.response.send_message(f"{target.name} hasn't played any games yet!", ephemeral=True)
            return

        games, wins, losses, total_earned, largest_win = stats_row or (0, 0, 0, 0, 0)
        blackjack_wins, blackjack_losses, blackjack_total_earned, blackjack_largest_win = blackjack_row or (0, 0, 0, 0)
        win_rate = (wins / games * 100) if games > 0 else 0

        embed = discord.Embed(
            title=f"{target.name}'s Game Stats 🎮",
            color=discord.Color.gold()
        )
        embed.set_thumbnail(url=target.display_avatar.url)

        embed.add_field(name="💰 Balance", value=str(profile_data["balance"]), inline=True)
        embed.add_field(name="🎮 Slots & Coinflip Played", value=str(games), inline=True)
        embed.add_field(name="✅ Wins", value=str(wins), inline=True)
        embed.add_field(name="❌ Losses", value=str(losses), inline=True)
        embed.add_field(name="📈 Win Rate", value=f"{win_rate:.2f}%", inline=True)
        embed.add_field(name="💸 Total Earned", value=str(total_earned), inline=True)
        embed.add_field(name="⭐ Most Common Symbol", value=profile_data["most_common_symbol"] or "N/A", inline=True)
        embed.add_field(name="🏆 Largest Win", value=str(largest_win), inline=True)

        embed.add_field(name="​", value="​", inline=False)

        embed.add_field(name="♠️ Blackjack Wins", value=str(blackjack_wins), inline=True)
        embed.add_field(name="♦️ Blackjack Losses", value=str(blackjack_losses), inline=True)
        embed.add_field(name="💵 Blackjack Total Earned", value=str(blackjack_total_earned), inline=True)
        embed.add_field(name="🎯 Blackjack Largest Win", value=str(blackjack_largest_win), inline=True)

        await interaction.response.send_message(embed=embed)
