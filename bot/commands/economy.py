"""
Economy commands for the BankRoll Discord Bot.
"""

import discord
from discord import app_commands

from ..config import MAX_TRANSFER
from ..database import (
    get_balance, get_leaderboard, get_rank, get_player_count, claim_daily_reward,
    get_user_profile, transfer, save_username,
)
from ..utils import fmt, display_name

LEADERBOARD_SIZE = 10


def win_rate(wins: int, losses: int) -> str:
    decided = wins + losses
    return f"{wins / decided * 100:.0f}%" if decided else "—"


def setup(client):
    """Setup economy commands."""

    @client.tree.command(name="balance", description="Check your or another player's balance")
    @app_commands.describe(user="The player to check (leave empty for yourself)")
    async def balance(interaction: discord.Interaction, user: discord.User = None):
        target = user or interaction.user
        if target.bot:
            await interaction.response.send_message("❌ Bots don't have a balance.", ephemeral=True)
            return
        user_balance = get_balance(target.id)
        who = "Your" if target == interaction.user else f"{display_name(target)}'s"
        await interaction.response.send_message(f"💰 {who} balance: **{fmt(user_balance)}** coins")

    @client.tree.command(name="pay", description="Send coins to another player")
    @app_commands.describe(user="Who to send coins to", amount="How many coins to send")
    async def pay(interaction: discord.Interaction, user: discord.User, amount: app_commands.Range[int, 1, MAX_TRANSFER]):
        if user.id == interaction.user.id:
            await interaction.response.send_message("❌ You can't pay yourself.", ephemeral=True)
            return
        if user.bot:
            await interaction.response.send_message("❌ You can't pay a bot.", ephemeral=True)
            return
        if not transfer(interaction.user.id, user.id, amount):
            await interaction.response.send_message(
                f"❌ Not enough coins. Your balance: 💰 {fmt(get_balance(interaction.user.id))}", ephemeral=True
            )
            return
        save_username(user.id, display_name(user))
        await interaction.response.send_message(
            f"💸 {interaction.user.mention} sent **{fmt(amount)}** coins to {user.mention}!\n"
            f"Your balance: 💰 {fmt(get_balance(interaction.user.id))}"
        )

    @client.tree.command(name="daily_reward", description="Claim your daily reward")
    async def daily_reward(interaction: discord.Interaction):
        success, new_balance, message = claim_daily_reward(interaction.user.id)

        if success:
            await interaction.response.send_message(f"✅ {message} Your new balance is 💰 {fmt(new_balance)}.", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ {message}", ephemeral=True)

    @client.tree.command(name="leaderboard", description="Show the top users with the most virtual currency")
    async def leaderboard(interaction: discord.Interaction):
        rows = get_leaderboard(LEADERBOARD_SIZE)

        if not rows:
            await interaction.response.send_message("No currency data available yet.", ephemeral=True)
            return

        missing = [user_id for user_id, _, username in rows if not username]
        if missing:
            # Only players who never used a command themselves (e.g. received /pay) have no stored name.
            await interaction.response.defer()
        names = {}
        for user_id in missing:
            try:
                user = client.get_user(user_id) or await client.fetch_user(user_id)
            except discord.HTTPException:
                continue
            names[user_id] = display_name(user)
            save_username(user_id, names[user_id])

        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        lines = []
        for i, (user_id, user_balance, username) in enumerate(rows, start=1):
            name = discord.utils.escape_markdown(username or names.get(user_id) or "Unknown player")
            lines.append(f"{medals.get(i, f'`{i}.`')} **{name}** — {fmt(user_balance)} coins")

        embed = discord.Embed(
            title="🏆 Leaderboard — Top Richest Players",
            description="\n".join(lines),
            color=discord.Color.gold()
        )
        footer = f"👥 Total players: {fmt(get_player_count())}"
        rank = get_rank(interaction.user.id)
        if rank:
            footer = f"Your position: #{rank} • 💰 {fmt(get_balance(interaction.user.id))}\n" + footer
        embed.set_footer(text=footer)

        if interaction.response.is_done():
            await interaction.followup.send(embed=embed)
        else:
            await interaction.response.send_message(embed=embed)

    @client.tree.command(name="profile", description="View your game stats and balance")
    @app_commands.describe(user="The user to view (leave empty for yourself)")
    async def profile(interaction: discord.Interaction, user: discord.User = None):
        target = user or interaction.user
        name = display_name(target)
        if target.bot:
            await interaction.response.send_message("❌ Bots don't play games.", ephemeral=True)
            return

        profile_data = get_user_profile(target.id)
        stats_row = profile_data["stats"]
        blackjack_row = profile_data["blackjack"]

        if not stats_row and not blackjack_row:
            await interaction.response.send_message(f"{name} hasn't played any games yet!", ephemeral=True)
            return

        games, wins, losses, total_earned, largest_win = stats_row or (0, 0, 0, 0, 0)
        bj_wins, bj_losses, bj_total_earned, bj_largest_win = blackjack_row or (0, 0, 0, 0)

        embed = discord.Embed(title=f"🎮 {name}'s profile", color=discord.Color.gold())
        embed.set_thumbnail(url=target.display_avatar.url)

        rank = get_rank(target.id)
        embed.add_field(
            name="💰 Balance",
            value=f"**{fmt(profile_data['balance'])}** coins" + (f" • Rank #{rank}" if rank else ""),
            inline=False,
        )
        embed.add_field(name="🎰 Slots & Coinflip", value=(
            f"Games: **{fmt(games)}**\n"
            f"Wins / Losses: **{fmt(wins)}** / **{fmt(losses)}**\n"
            f"Win rate: **{win_rate(wins, losses)}**\n"
            f"Biggest win: **{fmt(largest_win)}**\n"
            f"Total earned: **{fmt(total_earned)}**\n"
            f"Favorite symbol: {profile_data['most_common_symbol'] or '—'}"
        ), inline=True)
        embed.add_field(name="🃏 Blackjack", value=(
            f"Wins / Losses: **{fmt(bj_wins)}** / **{fmt(bj_losses)}**\n"
            f"Win rate: **{win_rate(bj_wins, bj_losses)}**\n"
            f"Biggest win: **{fmt(bj_largest_win)}**\n"
            f"Total earned: **{fmt(bj_total_earned)}**"
        ), inline=True)

        await interaction.response.send_message(embed=embed)
