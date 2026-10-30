"""
Player progression for the BankRoll Discord Bot: XP levels, titles and badges.

Every finished game goes through record_game(), which updates XP and per-game stats,
awards any badges the game unlocked and returns what's new so the game can tell the player.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import discord

from .config import XP_PER_GAME, XP_PER_WIN, MAX_BET
from .database import (
    record_game_result, get_game_stats, award_badges, get_balance, get_rank, get_player_count,
)

logger = logging.getLogger(__name__)

# ---------- Levels ----------

def xp_for_level(level: int) -> int:
    """Total XP needed to reach a level: 0, 100, 300, 600, 1000, ... (each level needs 100 more than the last)."""
    return 50 * level * (level - 1)


def level_for_xp(xp: int) -> int:
    level = 1
    while xp >= xp_for_level(level + 1):
        level += 1
    return level


def level_progress(xp: int) -> tuple[int, int, int]:
    """(level, XP earned inside the current level, XP the current level takes)."""
    level = level_for_xp(xp)
    start = xp_for_level(level)
    return level, xp - start, xp_for_level(level + 1) - start


def progress_bar(current: int, total: int, length: int = 10) -> str:
    filled = min(length, current * length // total) if total else length
    return "▰" * filled + "▱" * (length - filled)


# ---------- Titles ----------

@dataclass(frozen=True)
class Title:
    min_level: int
    emoji: str
    name: str
    color: discord.Color


TITLES = [
    Title(1, "🪙", "Rookie", discord.Color.light_grey()),
    Title(3, "🎲", "Gambler", discord.Color.green()),
    Title(6, "💼", "High Roller", discord.Color.blue()),
    Title(10, "🎩", "Card Shark", discord.Color.purple()),
    Title(15, "👑", "Casino King", discord.Color.gold()),
    Title(25, "💎", "Legend", discord.Color.teal()),
]


def title_for_level(level: int) -> Title:
    return [t for t in TITLES if level >= t.min_level][-1]


# ---------- Badges ----------

@dataclass(frozen=True)
class Badge:
    id: str
    emoji: str
    name: str
    description: str


BADGES = [
    Badge("first_win", "🍀", "First Win", "Win any game"),
    Badge("explorer", "🧭", "Explorer", "Play slots, blackjack and coinflip"),
    Badge("spins_100", "🎰", "Spin Master", "Spin the slots 100 times"),
    Badge("multi_line", "🌈", "Combo Breaker", "Hit 3 or more winning lines in one spin"),
    Badge("diamond_line", "💎", "Diamond Hands", "Hit a 💎💎💎 line"),
    Badge("natural", "🃏", "Natural 21", "Get a blackjack on the deal"),
    Badge("double_win", "✌️", "Double Trouble", "Win after doubling down"),
    Badge("coin_10", "🪙", "Coin Collector", "Win 10 coinflips"),
    Badge("max_bet", "💸", "Big Spender", "Bet the maximum in one game"),
    Badge("week_streak", "🔥", "On Fire", "Claim the daily reward 7 days in a row"),
    Badge("generous", "🤝", "Generous", "Send coins to another player"),
    Badge("rich", "🤑", "Five Figures", "Have 10,000 coins"),
    Badge("podium", "🏆", "Podium", "Reach the top 3 of the leaderboard"),
]
BADGES_BY_ID = {badge.id: badge for badge in BADGES}

RICH_BALANCE = 10_000
PODIUM_MIN_PLAYERS = 10  # the podium only counts once there is some competition


# ---------- Recording progress ----------

@dataclass
class Progress:
    """What changed for the player after an action."""
    level_before: int = 1
    level_after: int = 1
    new_badges: list[Badge] = field(default_factory=list)

    @property
    def leveled_up(self) -> bool:
        return self.level_after > self.level_before

    def notice(self) -> str | None:
        """A short message about level-ups and new badges, or None if nothing changed."""
        lines = []
        if self.leveled_up:
            title = title_for_level(self.level_after)
            line = f"⬆️ **Level up! You're now level {self.level_after}.**"
            if title != title_for_level(self.level_before):
                line += f"\nNew title: {title.emoji} **{title.name}**"
            lines.append(line)
        for badge in self.new_badges:
            lines.append(f"🏅 **New badge:** {badge.emoji} {badge.name} — {badge.description}")
        return "\n".join(lines) or None


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _wealth_badges(user_id) -> list[str]:
    earned = []
    if get_balance(user_id) >= RICH_BALANCE:
        earned.append("rich")
    rank = get_rank(user_id)
    if rank is not None and rank <= 3 and get_player_count() >= PODIUM_MIN_PLAYERS:
        earned.append("podium")
    return earned


def record_game(user_id, game: str, bet: int, payout: int, *, winning_combos: list[str] = (),
                natural: bool = False, doubled: bool = False) -> Progress:
    """
    Record a finished game ('slots', 'coinflip' or 'blackjack') and award what it unlocked.
    payout is the total returned to the player (0 on a loss, bet on a push).
    """
    today = _today()
    won = payout > bet
    xp_before, xp_after = record_game_result(user_id, game, won, payout - bet,
                                             XP_PER_GAME + (XP_PER_WIN if won else 0), today)

    stats = get_game_stats(user_id)
    candidates = []
    if won:
        candidates.append("first_win")
    if {"slots", "coinflip", "blackjack"} <= stats.keys():
        candidates.append("explorer")
    if stats.get("slots", (0, 0, 0))[0] >= 100:
        candidates.append("spins_100")
    if len(winning_combos) >= 3:
        candidates.append("multi_line")
    if any(combo.startswith("💎") for combo in winning_combos):
        candidates.append("diamond_line")
    if natural:
        candidates.append("natural")
    if doubled and won:
        candidates.append("double_win")
    if stats.get("coinflip", (0, 0, 0))[1] >= 10:
        candidates.append("coin_10")
    if bet >= MAX_BET:
        candidates.append("max_bet")
    candidates += _wealth_badges(user_id)

    new = award_badges(user_id, candidates, today)
    return Progress(level_for_xp(xp_before), level_for_xp(xp_after), [BADGES_BY_ID[b] for b in new])


def track_game(user_id, game: str, bet: int, payout: int, **details) -> Progress | None:
    """record_game() for use inside games: progression errors are logged and never break the game."""
    try:
        return record_game(user_id, game, bet, payout, **details)
    except Exception:
        logger.exception("Failed to record progression for %s", game)
        return None


def record_badges(user_id, badge_ids: list[str], check_wealth: bool = False) -> Progress:
    """Award badges earned outside games (daily streak, /pay). XP and level don't change."""
    candidates = list(badge_ids) + (_wealth_badges(user_id) if check_wealth else [])
    new = award_badges(user_id, candidates, _today())
    return Progress(new_badges=[BADGES_BY_ID[b] for b in new])


async def send_notice(interaction: discord.Interaction, progress: Progress | None):
    """Tell the player privately about a level-up or new badges. The interaction must already be responded to."""
    message = progress.notice() if progress else None
    if message:
        try:
            await interaction.followup.send(message, ephemeral=True)
        except discord.HTTPException:
            pass
