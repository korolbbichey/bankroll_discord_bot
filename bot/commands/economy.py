"""
Economy commands for the BankRoll Discord Bot.
"""

import logging
from datetime import datetime

import discord
from discord import app_commands

from ..config import MAX_TRANSFER, STARTING_BALANCE
from ..database import (
    get_balance, get_leaderboard, get_rank, get_player_count, claim_daily_reward, get_daily_streak,
    get_user_profile, transfer, save_username, get_player_progress, get_game_stats, get_badges,
)
from ..utils import fmt, display_name
from ..progression import (
    BADGES, level_progress, progress_bar, title_for_level, record_badges, send_notice,
)

LEADERBOARD_SIZE = 10
GAME_NAMES = {"slots": "Slots", "coinflip": "Coinflip", "blackjack": "Blackjack"}
WEEK_STREAK = 7

logger = logging.getLogger(__name__)


def streak_text(days: int) -> str:
    return f"{days} day{'s' if days != 1 else ''}"


def safe_badges(user_id, badge_ids: list[str], check_wealth: bool = False):
    """Award badges without ever breaking the command that triggered them."""
    try:
        return record_badges(user_id, badge_ids, check_wealth)
    except Exception:
        logger.exception("Failed to award badges")
        return None


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
        await send_notice(interaction, safe_badges(interaction.user.id, ["generous"]))

    @client.tree.command(name="daily_reward", description="Claim your daily reward — keep a streak for bigger rewards")
    async def daily_reward(interaction: discord.Interaction):
        claim = claim_daily_reward(interaction.user.id)
        hours, minutes = divmod(claim.seconds_left // 60, 60)
        wait = f"{hours}h {minutes}m"

        if not claim.claimed:
            embed = discord.Embed(
                title="⏳ Already claimed today",
                description=f"Your next reward of **{fmt(claim.next_reward)}** coins is ready in **{wait}**.",
                color=discord.Color.light_grey(),
            )
            embed.add_field(name="🔥 Streak", value=streak_text(claim.streak), inline=True)
            embed.add_field(name="💰 Balance", value=fmt(claim.balance), inline=True)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(title=f"🎁 +{fmt(claim.reward)} coins!", color=discord.Color.green())
        if claim.is_new:
            embed.description = f"Welcome to Bankroll! You also got **{fmt(STARTING_BALANCE)}** starting coins."
        embed.add_field(name="🔥 Streak", value=streak_text(claim.streak), inline=True)
        embed.add_field(name="💰 Balance", value=fmt(claim.balance), inline=True)
        embed.set_footer(text=f"Come back in {wait} for {fmt(claim.next_reward)} coins. Miss a day and the streak resets.")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await send_notice(interaction, safe_badges(
            interaction.user.id, ["week_streak"] if claim.streak >= WEEK_STREAK else [], check_wealth=True))

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

    @client.tree.command(name="profile", description="View a player's level, badges and stats")
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
        xp, first_played = get_player_progress(target.id)
        level, xp_into_level, level_span = level_progress(xp)
        title = title_for_level(level)

        embed = discord.Embed(
            title=f"{title.emoji} {name}",
            description=(
                f"**{title.name}** · Level {level}\n"
                f"{progress_bar(xp_into_level, level_span)}  {fmt(xp_into_level)} / {fmt(level_span)} XP"
            ),
            color=title.color,
        )
        embed.set_thumbnail(url=target.display_avatar.url)

        rank = get_rank(target.id)
        streak = get_daily_streak(target.id)
        embed.add_field(
            name="💰 Wallet",
            value=f"**{fmt(profile_data['balance'])}** coins"
                  + (f" · Rank #{rank}" if rank else "")
                  + (f" · 🔥 {streak_text(streak)} streak" if streak else ""),
            inline=False,
        )

        earned = get_badges(target.id)
        unlocked = [badge for badge in BADGES if badge.id in earned]
        locked = [badge for badge in BADGES if badge.id not in earned]
        badge_lines = ["  ".join(f"{b.emoji} {b.name}" for b in unlocked) or "None yet — win a game to earn your first!"]
        if locked:
            badge_lines.append(f"🔒 Next: {locked[0].emoji} **{locked[0].name}** — {locked[0].description}")
        embed.add_field(name=f"🏅 Badges ({len(unlocked)}/{len(BADGES)})", value="\n".join(badge_lines), inline=False)

        stat_lines = [
            f"🎰 **Slots & Coinflip** — {fmt(games)} games · {win_rate(wins, losses)} wins · best +{fmt(largest_win)}",
            f"🃏 **Blackjack** — {fmt(bj_wins + bj_losses)} games · {win_rate(bj_wins, bj_losses)} wins · best +{fmt(bj_largest_win)}",
            f"💸 Total won: **{fmt(total_earned + bj_total_earned)}** coins",
        ]
        favorites = []
        game_stats = get_game_stats(target.id)
        if game_stats:
            favorite_game = max(game_stats, key=lambda game: game_stats[game][0])
            favorites.append(f"❤️ Favorite game: **{GAME_NAMES[favorite_game]}**")
        if profile_data["most_common_symbol"]:
            favorites.append(f"lucky symbol {profile_data['most_common_symbol']}")
        if favorites:
            stat_lines.append(" · ".join(favorites))
        if first_played:
            since = datetime.strptime(first_played, "%Y-%m-%d").strftime("%b %d, %Y")
            stat_lines.append(f"📅 Playing since **{since}**")
        embed.add_field(name="📊 Stats", value="\n".join(stat_lines), inline=False)

        await interaction.response.send_message(embed=embed)
