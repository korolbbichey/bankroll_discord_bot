"""
Economy commands for the BankRoll Discord Bot.
"""

import asyncio
import io
import logging
from datetime import datetime

import discord
from discord import app_commands

from ..config import MAX_TRANSFER, STARTING_BALANCE
from ..database import (
    get_balance, get_leaderboard, get_rank, get_player_count, claim_daily_reward, get_daily_streak,
    get_leaderboard_row, get_user_profile, transfer, save_username, get_player_progress, get_game_stats, get_badges,
)
from ..leaderboard_card import LeaderboardEntry, render_leaderboard_card
from ..profile_card import CardData, render_profile_card
from ..utils import fmt, display_name, avatar_hash, DRAW_SLOTS
from ..progression import (
    BADGES, BADGES_BY_ID, level_for_xp, level_progress, progress_bar, title_for_level, record_badges, send_notice,
)

LEADERBOARD_SIZE = 10
GAME_NAMES = {"slots": "Slots", "coinflip": "Coinflip", "blackjack": "Blackjack"}
WEEK_STREAK = 7
AVATAR_TIMEOUT = 3  # seconds per avatar

logger = logging.getLogger(__name__)


def streak_text(days: int) -> str:
    return f"{days} day{'s' if days != 1 else ''}"


def games_text(count: int) -> str:
    return f"{fmt(count)} game{'s' if count != 1 else ''}"


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
        save_username(user.id, display_name(user), avatar_hash(user))
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

    async def resolve_unknown_players(rows: list) -> list:
        """
        Look up players whose name or avatar hash isn't stored yet (e.g. they only received /pay, or haven't
        played since avatars started being stored). Each player is only looked up once, then it comes from the database.
        """
        unknown = [row[0] for row in rows if not row[2] or row[3] is None]
        for user_id in unknown:
            try:
                user = client.get_user(user_id) or await client.fetch_user(user_id)
            except discord.HTTPException:
                continue
            save_username(user_id, display_name(user), avatar_hash(user))
        return get_leaderboard(LEADERBOARD_SIZE) if unknown else rows

    def leaderboard_embed(rows: list, viewer_id: int) -> discord.Embed:
        """The text version of the leaderboard, used when the image card can't be drawn."""
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        lines = []
        for i, (_, user_balance, username, _, _) in enumerate(rows, start=1):
            name = discord.utils.escape_markdown(username or "Unknown player")
            lines.append(f"{medals.get(i, f'`{i}.`')} **{name}** — {fmt(user_balance)} coins")

        embed = discord.Embed(
            title="🏆 Leaderboard — Top Richest Players",
            description="\n".join(lines),
            color=discord.Color.gold()
        )
        footer = f"👥 Total players: {fmt(get_player_count())}"
        rank = get_rank(viewer_id)
        if rank:
            footer = f"Your position: #{rank} • 💰 {fmt(get_balance(viewer_id))}\n" + footer
        embed.set_footer(text=footer)
        return embed

    async def download_avatar(user_id: int, avatar_key: str | None) -> bytes | None:
        """Download an avatar for one card, directly from Discord's CDN. It is never stored."""
        if not avatar_key:
            return None
        url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_key}.png?size=128"
        try:
            return await asyncio.wait_for(client.http.get_from_cdn(url), AVATAR_TIMEOUT)
        except Exception:
            return None  # a changed avatar or a slow network: the card shows the first letter instead

    async def draw_leaderboard(rows: list, viewer: discord.abc.User) -> bytes:
        viewer_row = get_leaderboard_row(viewer.id)
        viewer_rank = get_rank(viewer.id)
        viewer_outside = viewer_row is not None and viewer_rank > len(rows)

        avatars = await asyncio.gather(*[download_avatar(row[0], row[3]) for row in rows])
        viewer_avatar = await download_avatar(viewer.id, avatar_hash(viewer)) if viewer_outside else None

        entries = [
            LeaderboardEntry(rank, username or "Player", user_balance, level_for_xp(xp), avatar, user_id == viewer.id)
            for rank, ((user_id, user_balance, username, _, xp), avatar) in enumerate(zip(rows, avatars), start=1)
        ]
        viewer_entry = None
        if viewer_outside:
            viewer_entry = LeaderboardEntry(viewer_rank, display_name(viewer), viewer_row[1],
                                            level_for_xp(viewer_row[4]), viewer_avatar, True)

        async with DRAW_SLOTS:
            return await asyncio.to_thread(render_leaderboard_card, entries, get_player_count(), viewer_entry)

    @client.tree.command(name="leaderboard", description="Show the top users with the most virtual currency")
    async def leaderboard(interaction: discord.Interaction):
        rows = get_leaderboard(LEADERBOARD_SIZE)

        if not rows:
            await interaction.response.send_message("No currency data available yet.", ephemeral=True)
            return

        # Downloading avatars and drawing can take longer than Discord's 3 seconds.
        await interaction.response.defer()
        rows = await resolve_unknown_players(rows)
        try:
            png = await draw_leaderboard(rows, interaction.user)
        except Exception:
            logger.exception("Failed to draw the leaderboard card, sending text instead")
            await interaction.followup.send(embed=leaderboard_embed(rows, interaction.user.id))
            return
        await interaction.followup.send(file=discord.File(io.BytesIO(png), filename="leaderboard.png"))

    def profile_embed(target, profile_data) -> discord.Embed:
        """The text version of the profile, used when the image card can't be drawn."""
        games, wins, losses, total_earned, largest_win = profile_data["stats"] or (0, 0, 0, 0, 0)
        bj_wins, bj_losses, bj_total_earned, bj_largest_win = profile_data["blackjack"] or (0, 0, 0, 0)
        xp, first_played = get_player_progress(target.id)
        level, xp_into_level, level_span = level_progress(xp)
        title = title_for_level(level)

        embed = discord.Embed(
            title=f"{title.emoji} {display_name(target)}",
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
            f"🎰 **Slots & Coinflip** — {games_text(games)} · {win_rate(wins, losses)} wins · best +{fmt(largest_win)}",
            f"🃏 **Blackjack** — {games_text(bj_wins + bj_losses)} · {win_rate(bj_wins, bj_losses)} wins · best +{fmt(bj_largest_win)}",
            f"💸 Total won: **{fmt(total_earned + bj_total_earned)}** coins",
        ]
        favorites = []
        game_stats = get_game_stats(target.id)
        if game_stats:
            favorite_game = max(game_stats, key=lambda game: game_stats[game][0])
            favorites.append(f"❤️ Favorite game: **{GAME_NAMES[favorite_game]}**")
        if profile_data["most_common_symbol"]:
            favorites.append(f"Lucky symbol {profile_data['most_common_symbol']}")
        if favorites:
            stat_lines.append(" · ".join(favorites))
        if first_played:
            since = datetime.strptime(first_played, "%Y-%m-%d").strftime("%b %d, %Y")
            stat_lines.append(f"📅 Playing since **{since}**")
        embed.add_field(name="📊 Stats", value="\n".join(stat_lines), inline=False)
        return embed

    def profile_card_data(target, profile_data) -> CardData:
        games, wins, losses, _, largest_win = profile_data["stats"] or (0, 0, 0, 0, 0)
        bj_wins, bj_losses, _, bj_largest_win = profile_data["blackjack"] or (0, 0, 0, 0)
        level, xp_into_level, level_span = level_progress(get_player_progress(target.id)[0])
        title = title_for_level(level)
        return CardData(
            name=display_name(target),
            title=title.name,
            accent=title.color.to_rgb(),
            level=level,
            xp_into_level=xp_into_level,
            level_span=level_span,
            balance=profile_data["balance"],
            rank=get_rank(target.id),
            games=games + bj_wins + bj_losses,
            win_rate=win_rate(wins + bj_wins, losses + bj_losses),
            best_win=max(largest_win, bj_largest_win),
            streak=get_daily_streak(target.id),
            earned_badges=get_badges(target.id),
        )

    async def read_avatar(target) -> bytes | None:
        """Download the avatar for this one card. It is never stored."""
        try:
            return await target.display_avatar.with_format("png").with_size(256).read()
        except (discord.DiscordException, ValueError):
            return None

    @client.tree.command(name="profile", description="View a player's level, badges and stats")
    @app_commands.describe(user="The user to view (leave empty for yourself)")
    async def profile(interaction: discord.Interaction, user: discord.User = None):
        target = user or interaction.user
        if target.bot:
            await interaction.response.send_message("❌ Bots don't play games.", ephemeral=True)
            return

        profile_data = get_user_profile(target.id)
        if not profile_data["stats"] and not profile_data["blackjack"]:
            await interaction.response.send_message(f"{display_name(target)} hasn't played any games yet!", ephemeral=True)
            return

        # Downloading the avatar and drawing can take longer than Discord's 3 seconds.
        await interaction.response.defer()
        try:
            data = profile_card_data(target, profile_data)
            avatar = await read_avatar(target)
            async with DRAW_SLOTS:
                png = await asyncio.to_thread(render_profile_card, data, avatar)
        except Exception:
            logger.exception("Failed to draw the profile card, sending text instead")
            await interaction.followup.send(embed=profile_embed(target, profile_data))
            return
        await interaction.followup.send(
            "Badge details: `/badges`",
            file=discord.File(io.BytesIO(png), filename="profile.png"),
        )

    @client.tree.command(name="badges", description="See every badge and how to earn it")
    @app_commands.describe(user="The user to view (leave empty for yourself)")
    async def badges(interaction: discord.Interaction, user: discord.User = None):
        target = user or interaction.user
        earned = get_badges(target.id)
        embed = discord.Embed(
            title=f"🏅 {display_name(target)}'s badges — {len(earned & BADGES_BY_ID.keys())} / {len(BADGES)}",
            description="\n".join(
                f"{badge.emoji if badge.id in earned else '🔒'} **{badge.name}** — {badge.description}"
                for badge in BADGES
            ),
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
