"""
Player progression for the BankRoll Discord Bot: XP levels, titles and badges.

Every finished game goes through record_game(), which updates XP and per-game stats,
awards any badges the game unlocked and returns what's new so the game can tell the player.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import discord

from .config import XP_PER_GAME, XP_PER_WIN, DAILY_XP_LIMIT, BADGE_RARITY, BADGE_REWARDS, LEVEL_UP_REWARD
from .database import (
    record_game_result, get_game_stats, award_badges, get_balance, get_rank, get_player_count, credit,
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
    Badge("max_bet", "💸", "Big Spender", "Bet 10,000 or more in one game"),
    Badge("week_streak", "🔥", "On Fire", "Claim the daily reward 7 days in a row"),
    Badge("generous", "🤝", "Generous", "Send coins to another player"),
    Badge("rich", "🤑", "Five Figures", "Have 10,000 coins"),
    Badge("podium", "🏆", "Podium", "Reach the top 3 of the leaderboard"),
    Badge("duelist", "⚔️", "Duelist", "Win a duel"),
    Badge("duel_5", "🥇", "Champion", "Win 5 duels"),
    Badge("bullseye", "🎯", "Bullseye", "Win a roulette bet on a single number"),
    Badge("zero", "🟢", "Green Zero", "Win when the roulette ball lands on 0"),
    Badge("jackpot", "💰", "Jackpot", "Win 25 times your bet or more in one game"),
    Badge("grand_tour", "🗺️", "Grand Tour", "Play every game: slots, blackjack, coinflip, roulette and a duel"),
    Badge("veteran", "🎖️", "Veteran", "Play 500 games"),
    Badge("month_streak", "⚡", "Unstoppable", "Claim the daily reward 30 days in a row"),
    Badge("full_house", "💯", "Full House", "Fill the whole slot grid with one symbol: all 8 lines"),
]
BADGES_BY_ID = {badge.id: badge for badge in BADGES}

RICH_BALANCE = 10_000
BIG_SPENDER_BET = 10_000  # fixed: the badge was "bet the maximum" when the maximum was 10,000
PODIUM_MIN_PLAYERS = 10  # the podium only counts once there is some competition
JACKPOT_MULTIPLIER = 25
VETERAN_GAMES = 500
ALL_GAMES = {"slots", "coinflip", "blackjack", "roulette", "duel"}


# ---------- Recording progress ----------

@dataclass
class Progress:
    """What changed for the player after an action."""
    level_before: int = 1
    level_after: int = 1
    new_badges: list[Badge] = field(default_factory=list)
    coins: int = 0  # reward for the new level and badges, already paid
    xp_limit_reached: bool = False  # this game used up the day's XP from games

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
        if self.coins:
            lines.append(f"🎁 **+{self.coins:,} coins** reward!")
        if self.xp_limit_reached:
            lines.append(f"📊 You've earned today's {DAILY_XP_LIMIT:,} XP from games. "
                         "Keep playing, XP comes back tomorrow (UTC).")
        return "\n".join(lines) or None


def reward_for(level_before: int, level_after: int, badge_ids: list[str]) -> int:
    """Coins for every level reached (the level times LEVEL_UP_REWARD) and for each new badge by its rarity."""
    levels = sum(level * LEVEL_UP_REWARD for level in range(level_before + 1, level_after + 1))
    return levels + sum(BADGE_REWARDS[BADGE_RARITY[badge]] for badge in badge_ids)


def _progress(user_id, level_before: int, level_after: int, new: list[str]) -> Progress:
    """Pay the reward and describe what changed."""
    coins = reward_for(level_before, level_after, new)
    if coins:
        credit(user_id, coins)
    return Progress(level_before, level_after, [BADGES_BY_ID[b] for b in new], coins)


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
                natural: bool = False, doubled: bool = False, bullseye: bool = False,
                zero_win: bool = False) -> Progress:
    """
    Record a finished game ('slots', 'coinflip', 'blackjack', 'roulette' or 'duel') and award what it unlocked.
    payout is the total returned to the player (0 on a loss, bet on a push).
    """
    today = _today()
    won = payout > bet
    xp_before, xp_after, xp_today = record_game_result(user_id, game, won, payout - bet,
                                                       XP_PER_GAME + (XP_PER_WIN if won else 0), today, DAILY_XP_LIMIT)
    limit_reached = xp_after > xp_before and xp_today >= DAILY_XP_LIMIT

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
    if len(winning_combos) >= 8:  # every row, column and diagonal
        candidates.append("full_house")
    if any(combo.startswith("💎") for combo in winning_combos):
        candidates.append("diamond_line")
    if natural:
        candidates.append("natural")
    if doubled and won:
        candidates.append("double_win")
    if stats.get("coinflip", (0, 0, 0))[1] >= 10:
        candidates.append("coin_10")
    if bet >= BIG_SPENDER_BET:
        candidates.append("max_bet")
    duel_wins = stats.get("duel", (0, 0, 0))[1]
    if duel_wins >= 1:
        candidates.append("duelist")
    if duel_wins >= 5:
        candidates.append("duel_5")
    if bullseye:
        candidates.append("bullseye")
    if zero_win:
        candidates.append("zero")
    if payout >= bet * JACKPOT_MULTIPLIER:
        candidates.append("jackpot")
    if ALL_GAMES <= stats.keys():
        candidates.append("grand_tour")
    if sum(games for games, _, _ in stats.values()) >= VETERAN_GAMES:
        candidates.append("veteran")
    candidates += _wealth_badges(user_id)

    new = award_badges(user_id, candidates, today)
    progress = _progress(user_id, level_for_xp(xp_before), level_for_xp(xp_after), new)
    progress.xp_limit_reached = limit_reached
    return progress


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
    return _progress(user_id, 1, 1, new)


async def send_notice(interaction: discord.Interaction, progress: Progress | None):
    """Tell the player privately about a level-up or new badges. The interaction must already be responded to."""
    message = progress.notice() if progress else None
    if message:
        try:
            await interaction.followup.send(message, ephemeral=True)
        except discord.HTTPException:
            pass
