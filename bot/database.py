"""
Database operations for the BankRoll Discord Bot.

All balance changes are done with single atomic UPDATE statements so that
concurrent games can never read a stale balance and overwrite each other.
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from .config import DB_FILE, STARTING_BALANCE, DAILY_REWARD


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


def _ensure_account(cursor, user_id):
    cursor.execute("INSERT OR IGNORE INTO currency (user_id, balance) VALUES (?, ?)",
                   (user_id, STARTING_BALANCE))


# ============== Currency Operations ==============

def get_balance(user_id) -> int:
    """Get user balance, creating account if needed."""
    with get_connection() as conn:
        cursor = conn.cursor()
        _ensure_account(cursor, user_id)
        cursor.execute("SELECT balance FROM currency WHERE user_id = ?", (user_id,))
        return cursor.fetchone()[0]


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
    """1-based leaderboard position, or None if the user has no account."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM currency WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row is None:
            return None
        cursor.execute("SELECT COUNT(*) + 1 FROM currency WHERE balance > ?", (row[0],))
        return cursor.fetchone()[0]


def get_player_count() -> int:
    """Number of users who have played at least one game."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM (SELECT user_id FROM stats UNION SELECT user_id FROM blackjack_stats)")
        return cursor.fetchone()[0]


def get_leaderboard(limit: int = 5) -> list:
    """Get top users by balance."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, balance FROM currency ORDER BY balance DESC LIMIT ?",
                       (limit,))
        return cursor.fetchall()


def claim_daily_reward(user_id) -> tuple[bool, int, str]:
    """
    Attempt to claim daily reward (resets at 00:00 UTC).
    Returns: (success, new_balance, message)
    """
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM currency WHERE user_id = ?", (user_id,))
        is_new = cursor.fetchone() is None
        _ensure_account(cursor, user_id)

        cursor.execute("""
            UPDATE currency SET balance = balance + ?, last_claim_date = ?
            WHERE user_id = ? AND (last_claim_date IS NULL OR last_claim_date != ?)
        """, (DAILY_REWARD, today, user_id, today))
        claimed = cursor.rowcount == 1

        cursor.execute("SELECT balance FROM currency WHERE user_id = ?", (user_id,))
        balance = cursor.fetchone()[0]

    if not claimed:
        seconds_left = int((now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1) - now).total_seconds())
        hours, minutes = divmod(seconds_left // 60, 60)
        return False, balance, f"You've already claimed your daily reward today. Next one in **{hours}h {minutes}m**."
    if is_new:
        return True, balance, f"Welcome! You've received 💰 {STARTING_BALANCE} starting balance + 💰 {DAILY_REWARD} daily reward!"
    return True, balance, f"You've claimed your daily reward of 💰 {DAILY_REWARD}!"


# ============== Stats Operations ==============

def update_stats(user_id, payout: int, bet: int, final_grid=None):
    """
    Record a finished slots/coinflip round.
    payout is the total amount returned to the player (0 on a loss).
    """
    profit = max(0, payout - bet)
    win = payout > bet

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
        """, (user_id, int(win), int(not win), profit, profit))

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
