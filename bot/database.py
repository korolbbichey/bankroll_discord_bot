"""
Database operations for the BankRoll Discord Bot.

All balance changes are done with single atomic UPDATE statements so that
concurrent games can never read a stale balance and overwrite each other.
"""

import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .config import DB_FILE, STARTING_BALANCE, DAILY_STREAK_REWARDS, XP_PER_GAME, XP_PER_WIN


@contextmanager
def get_connection():
    """Context manager for database connections."""
    conn = sqlite3.connect(DB_FILE, timeout=10)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Initialize all database tables."""
    db_dir = os.path.dirname(DB_FILE)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")

        cursor.execute('''CREATE TABLE IF NOT EXISTS currency (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 100,
            last_claim_date TEXT
        )''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS stats (
            user_id INTEGER PRIMARY KEY,
            games_played INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            total_earned INTEGER DEFAULT 0,
            most_common_symbol TEXT DEFAULT '',
            largest_win INTEGER DEFAULT 0
        )''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS blackjack_stats (
            user_id INTEGER PRIMARY KEY,
            blackjack_wins INTEGER DEFAULT 0,
            blackjack_losses INTEGER DEFAULT 0,
            blackjack_total_earned INTEGER DEFAULT 0,
            blackjack_largest_win INTEGER DEFAULT 0
        )''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS symbol_counts (
            user_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            count INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, symbol)
        )''')
        # target_id is a server ID (or a user ID for commands used outside a server)
        cursor.execute('''CREATE TABLE IF NOT EXISTS announcements_shown (
            target_id INTEGER PRIMARY KEY,
            announcement_id TEXT NOT NULL
        )''')

        # Display names are cached for the leaderboard, so it doesn't need Discord API calls.
        currency_columns = [row[1] for row in cursor.execute("PRAGMA table_info(currency)")]
        if "username" not in currency_columns:
            cursor.execute("ALTER TABLE currency ADD COLUMN username TEXT")
        if "daily_streak" not in currency_columns:
            cursor.execute("ALTER TABLE currency ADD COLUMN daily_streak INTEGER DEFAULT 0")
        # Only the hash that identifies the avatar on Discord's CDN, never the picture. NULL = not known yet.
        if "avatar_hash" not in currency_columns:
            cursor.execute("ALTER TABLE currency ADD COLUMN avatar_hash TEXT")

        # The clown symbol was removed from the slots.
        cursor.execute("DELETE FROM symbol_counts WHERE symbol = ?", ("\U0001f921",))

        # ---- Progression: XP, per-game stats and badges ----
        cursor.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'players'")
        players_is_new = cursor.fetchone() is None
        cursor.execute('''CREATE TABLE IF NOT EXISTS players (
            user_id INTEGER PRIMARY KEY,
            xp INTEGER DEFAULT 0,
            first_played TEXT
        )''')
        # game is 'slots', 'coinflip' or 'blackjack'; net is total payout minus total bets
        cursor.execute('''CREATE TABLE IF NOT EXISTS game_stats (
            user_id INTEGER NOT NULL,
            game TEXT NOT NULL,
            games INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            net INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, game)
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS badges (
            user_id INTEGER NOT NULL,
            badge TEXT NOT NULL,
            earned_at TEXT NOT NULL,
            PRIMARY KEY (user_id, badge)
        )''')
        if players_is_new:
            # Existing players keep their progress: XP is rebuilt from the stats recorded so far.
            cursor.execute("""
                INSERT INTO players (user_id, xp)
                SELECT user_id, SUM(games) * ? + SUM(wins) * ? FROM (
                    SELECT user_id, games_played AS games, wins FROM stats
                    UNION ALL
                    SELECT user_id, blackjack_wins + blackjack_losses, blackjack_wins FROM blackjack_stats
                ) GROUP BY user_id
            """, (XP_PER_GAME, XP_PER_WIN))
            # The only badge the old stats can prove: anyone with a recorded win already has "First Win".
            cursor.execute("""
                INSERT OR IGNORE INTO badges (user_id, badge, earned_at)
                SELECT user_id, 'first_win', date('now') FROM stats WHERE wins > 0
                UNION
                SELECT user_id, 'first_win', date('now') FROM blackjack_stats WHERE blackjack_wins > 0
            """)


def _ensure_account(cursor, user_id):
    cursor.execute("INSERT OR IGNORE INTO currency (user_id, balance) VALUES (?, ?)",
                   (user_id, STARTING_BALANCE))


# ============== Currency Operations ==============

def get_balance(user_id) -> int:
    """
    Get a user's balance. Read-only: users without an account have the starting balance,
    but an account is only created once their coins actually change (game, daily reward, transfer).
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM currency WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        return row[0] if row else STARTING_BALANCE


def try_debit(user_id, amount: int) -> bool:
    """Atomically subtract amount if the user can afford it. Returns True on success."""
    with get_connection() as conn:
        cursor = conn.cursor()
        _ensure_account(cursor, user_id)
        cursor.execute("UPDATE currency SET balance = balance - ? WHERE user_id = ? AND balance >= ?",
                       (amount, user_id, amount))
        return cursor.rowcount == 1


def credit(user_id, amount: int) -> int:
    """Atomically add amount to the user's balance. Returns the new balance."""
    with get_connection() as conn:
        cursor = conn.cursor()
        _ensure_account(cursor, user_id)
        cursor.execute("UPDATE currency SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        cursor.execute("SELECT balance FROM currency WHERE user_id = ?", (user_id,))
        return cursor.fetchone()[0]


def transfer(from_id, to_id, amount: int) -> bool:
    """Atomically move amount between two users. Returns False if the sender can't afford it."""
    with get_connection() as conn:
        cursor = conn.cursor()
        _ensure_account(cursor, from_id)
        _ensure_account(cursor, to_id)
        cursor.execute("UPDATE currency SET balance = balance - ? WHERE user_id = ? AND balance >= ?",
                       (amount, from_id, amount))
        if cursor.rowcount != 1:
            return False
        cursor.execute("UPDATE currency SET balance = balance + ? WHERE user_id = ?", (amount, to_id))
        return True


def set_balance(user_id, amount: int):
    """Set a user's balance to an exact value (admin use)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        _ensure_account(cursor, user_id)
        cursor.execute("UPDATE currency SET balance = ? WHERE user_id = ?", (amount, user_id))


def get_rank(user_id) -> int | None:
    """1-based leaderboard position (same ordering as get_leaderboard), or None if the user has no account."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM currency WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row is None:
            return None
        cursor.execute("SELECT COUNT(*) + 1 FROM currency WHERE balance > ? OR (balance = ? AND user_id < ?)",
                       (row[0], row[0], user_id))
        return cursor.fetchone()[0]


def get_player_count() -> int:
    """Number of players on the leaderboard (everyone with an account), so it matches get_rank."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM currency")
        return cursor.fetchone()[0]


_LEADERBOARD_COLUMNS = """
    SELECT c.user_id, c.balance, c.username, c.avatar_hash, COALESCE(p.xp, 0)
    FROM currency c LEFT JOIN players p ON p.user_id = c.user_id
"""


def get_leaderboard(limit: int = 5) -> list[tuple[int, int, str | None, str | None, int]]:
    """Top users by balance as (user_id, balance, username, avatar_hash, xp). Ties keep a stable order."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(_LEADERBOARD_COLUMNS + " ORDER BY c.balance DESC, c.user_id LIMIT ?", (limit,))
        return cursor.fetchall()


def get_leaderboard_row(user_id) -> tuple[int, int, str | None, str | None, int] | None:
    """The same row as get_leaderboard, for one user. None if they have no account."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(_LEADERBOARD_COLUMNS + " WHERE c.user_id = ?", (user_id,))
        return cursor.fetchone()


def save_username(user_id, username: str, avatar_hash: str | None = None) -> bool:
    """
    Store the user's display name and avatar hash ("" = no custom avatar, None = leave as is)
    if they have an account. Only writes when something changed. Returns False if there is no account yet.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT username, avatar_hash FROM currency WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row is None:
            return False
        new_hash = row[1] if avatar_hash is None else avatar_hash
        if (row[0], row[1]) != (username, new_hash):
            cursor.execute("UPDATE currency SET username = ?, avatar_hash = ? WHERE user_id = ?",
                           (username, new_hash, user_id))
        return True


def daily_reward_for(streak: int) -> int:
    """Reward for the given streak day (1-based); stays at the maximum after the last configured day."""
    return DAILY_STREAK_REWARDS[min(max(streak, 1), len(DAILY_STREAK_REWARDS)) - 1]


@dataclass
class DailyClaim:
    claimed: bool        # False if the reward was already claimed today
    balance: int
    streak: int          # current streak in days
    reward: int          # coins given now (0 if not claimed)
    next_reward: int     # reward for tomorrow if the streak continues
    seconds_left: int    # until the next reward becomes available (00:00 UTC)
    is_new: bool = False # the claim created the account (starting balance included)


def claim_daily_reward(user_id, now: datetime | None = None) -> DailyClaim:
    """
    Claim the daily reward (resets at 00:00 UTC). Claiming on consecutive days builds a streak
    with growing rewards (DAILY_STREAK_REWARDS); missing a day starts again from day 1.
    """
    now = now or datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    seconds_left = int((now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1) - now).total_seconds())

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT balance, last_claim_date, daily_streak FROM currency WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        is_new = row is None
        last_claim, old_streak = (row[1], row[2] or 0) if row else (None, 0)

        if last_claim == today:
            return DailyClaim(False, row[0], old_streak, 0, daily_reward_for(old_streak + 1), seconds_left)

        streak = old_streak + 1 if last_claim == yesterday else 1
        reward = daily_reward_for(streak)
        _ensure_account(cursor, user_id)
        # The date condition makes the claim atomic: of two simultaneous claims only one updates the row.
        cursor.execute("""
            UPDATE currency SET balance = balance + ?, last_claim_date = ?, daily_streak = ?
            WHERE user_id = ? AND (last_claim_date IS NULL OR last_claim_date != ?)
        """, (reward, today, streak, user_id, today))
        claimed = cursor.rowcount == 1

        cursor.execute("SELECT balance, daily_streak FROM currency WHERE user_id = ?", (user_id,))
        balance, current_streak = cursor.fetchone()

    if not claimed:
        return DailyClaim(False, balance, current_streak, 0, daily_reward_for(current_streak + 1), seconds_left)
    return DailyClaim(True, balance, streak, reward, daily_reward_for(streak + 1), seconds_left, is_new)


def get_daily_streak(user_id, now: datetime | None = None) -> int:
    """The user's active streak: kept if they claimed today or yesterday, otherwise 0."""
    now = now or datetime.now(timezone.utc)
    active_dates = (now.strftime("%Y-%m-%d"), (now - timedelta(days=1)).strftime("%Y-%m-%d"))
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT last_claim_date, daily_streak FROM currency WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
    return (row[1] or 0) if row and row[0] in active_dates else 0


def mark_announcement_shown(target_id, announcement_id: str) -> bool:
    """Record that this announcement was shown to a server (or user). Returns True only the first time."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO announcements_shown (target_id, announcement_id) VALUES (?, ?)
            ON CONFLICT(target_id) DO UPDATE SET announcement_id = excluded.announcement_id
            WHERE announcement_id != excluded.announcement_id
        """, (target_id, announcement_id))
        return cursor.rowcount == 1


# ============== Stats Operations ==============

def update_stats(user_id, payout: int, bet: int, final_grid=None):
    """
    Record a finished slots/coinflip round.
    payout is the total amount returned to the player (0 on a loss).
    A payout equal to the bet counts as a game played but neither a win nor a loss.
    """
    profit = max(0, payout - bet)
    win = payout > bet
    loss = payout < bet

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO stats (user_id, games_played, wins, losses, total_earned, largest_win)
            VALUES (?, 1, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                games_played = games_played + 1,
                wins = wins + excluded.wins,
                losses = losses + excluded.losses,
                total_earned = total_earned + excluded.total_earned,
                largest_win = MAX(largest_win, excluded.largest_win)
        """, (user_id, int(win), int(loss), profit, profit))

        if final_grid is not None:
            for row in final_grid:
                for symbol in row:
                    cursor.execute("""
                        INSERT INTO symbol_counts (user_id, symbol, count) VALUES (?, ?, 1)
                        ON CONFLICT(user_id, symbol) DO UPDATE SET count = count + 1
                    """, (user_id, symbol))


def update_blackjack_stats(user_id, profit: int, is_win: bool, is_push: bool = False):
    """Record a finished blackjack round. Pushes count as neither win nor loss."""
    wins = int(is_win)
    losses = int(not is_win and not is_push)
    earned = profit if is_win else 0

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO blackjack_stats (user_id, blackjack_wins, blackjack_losses, blackjack_total_earned, blackjack_largest_win)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                blackjack_wins = blackjack_wins + excluded.blackjack_wins,
                blackjack_losses = blackjack_losses + excluded.blackjack_losses,
                blackjack_total_earned = blackjack_total_earned + excluded.blackjack_total_earned,
                blackjack_largest_win = MAX(blackjack_largest_win, excluded.blackjack_largest_win)
        """, (user_id, wins, losses, earned, earned))


def get_user_profile(user_id) -> dict:
    """Get comprehensive user profile data."""
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT games_played, wins, losses, total_earned, largest_win FROM stats WHERE user_id = ?", (user_id,))
        stats_row = cursor.fetchone()

        cursor.execute("SELECT blackjack_wins, blackjack_losses, blackjack_total_earned, blackjack_largest_win FROM blackjack_stats WHERE user_id = ?", (user_id,))
        blackjack_row = cursor.fetchone()

        cursor.execute("SELECT balance FROM currency WHERE user_id = ?", (user_id,))
        balance_row = cursor.fetchone()

        cursor.execute("SELECT symbol FROM symbol_counts WHERE user_id = ? ORDER BY count DESC LIMIT 1", (user_id,))
        symbol_row = cursor.fetchone()

    return {
        "balance": balance_row[0] if balance_row else STARTING_BALANCE,
        "stats": stats_row,
        "blackjack": blackjack_row,
        "most_common_symbol": symbol_row[0] if symbol_row else None,
    }


# ============== Progression Operations ==============

def record_game_result(user_id, game: str, won: bool, net: int, xp_gain: int, today: str) -> tuple[int, int]:
    """
    Add a finished game to the player's per-game stats and XP.
    Returns (xp_before, xp_after).
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO players (user_id, xp, first_played) VALUES (?, 0, ?)", (user_id, today))
        cursor.execute("UPDATE players SET first_played = ? WHERE user_id = ? AND first_played IS NULL", (today, user_id))
        cursor.execute("SELECT xp FROM players WHERE user_id = ?", (user_id,))
        xp_before = cursor.fetchone()[0]
        cursor.execute("UPDATE players SET xp = xp + ? WHERE user_id = ?", (xp_gain, user_id))
        cursor.execute("""
            INSERT INTO game_stats (user_id, game, games, wins, net) VALUES (?, ?, 1, ?, ?)
            ON CONFLICT(user_id, game) DO UPDATE SET
                games = games + 1,
                wins = wins + excluded.wins,
                net = net + excluded.net
        """, (user_id, game, int(won), net))
    return xp_before, xp_before + xp_gain


def get_player_progress(user_id) -> tuple[int, str | None]:
    """(xp, first_played date as YYYY-MM-DD or None)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT xp, first_played FROM players WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
    return (row[0], row[1]) if row else (0, None)


def get_game_stats(user_id) -> dict[str, tuple[int, int, int]]:
    """Per-game stats recorded since progression was added: {game: (games, wins, net)}."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT game, games, wins, net FROM game_stats WHERE user_id = ?", (user_id,))
        return {game: (games, wins, net) for game, games, wins, net in cursor.fetchall()}


def award_badges(user_id, badge_ids: list[str], today: str) -> list[str]:
    """Give badges the user doesn't have yet. Returns only the newly earned ones, in the given order."""
    new = []
    with get_connection() as conn:
        cursor = conn.cursor()
        for badge_id in badge_ids:
            cursor.execute("INSERT OR IGNORE INTO badges (user_id, badge, earned_at) VALUES (?, ?, ?)",
                           (user_id, badge_id, today))
            if cursor.rowcount == 1:
                new.append(badge_id)
    return new


def get_badges(user_id) -> set[str]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT badge FROM badges WHERE user_id = ?", (user_id,))
        return {row[0] for row in cursor.fetchall()}
