"""
Database operations for the BankRoll Discord Bot.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime

from .config import DB_FILE, STARTING_BALANCE, DAILY_REWARD


@contextmanager
def get_connection():
    """Context manager for database connections."""
    conn = sqlite3.connect(DB_FILE)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """Initialize all database tables."""
    with get_connection() as conn:
        cursor = conn.cursor()

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

        cursor.execute('''CREATE TABLE IF NOT EXISTS challenges (
            user_id INTEGER PRIMARY KEY,
            daily_wins INTEGER DEFAULT 0,
            weekly_wins INTEGER DEFAULT 0,
            last_daily_reset INTEGER DEFAULT 0,
            last_weekly_reset INTEGER DEFAULT 0
        )''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS blackjack_stats (
            user_id INTEGER PRIMARY KEY,
            blackjack_wins INTEGER DEFAULT 0,
            blackjack_losses INTEGER DEFAULT 0,
            blackjack_total_earned INTEGER DEFAULT 0,
            blackjack_largest_win INTEGER DEFAULT 0
        )''')


# ============== Currency Operations ==============

def get_balance(user_id) -> int:
    """Get user balance, creating account if needed."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM currency WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        if result is None:
            cursor.execute("INSERT INTO currency (user_id, balance) VALUES (?, ?)",
                          (user_id, STARTING_BALANCE))
            return STARTING_BALANCE
        return result[0]


def update_balance(user_id, new_balance: int):
    """Update user's balance."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("REPLACE INTO currency (user_id, balance) VALUES (?, ?)",
                      (user_id, new_balance))


def get_leaderboard(limit: int = 5) -> list:
    """Get top users by balance."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, balance FROM currency ORDER BY balance DESC LIMIT ?",
                      (limit,))
        return cursor.fetchall()


def claim_daily_reward(user_id) -> tuple[bool, int, str]:
    """
    Attempt to claim daily reward.
    Returns: (success, new_balance, message)
    """
    today = datetime.today().date()

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT balance, last_claim_date FROM currency WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()

        if result:
            balance, last_claim_str = result

            if last_claim_str:
                last_claim_date = datetime.strptime(last_claim_str, "%Y-%m-%d").date()
                if last_claim_date == today:
                    return False, balance, "You've already claimed your daily reward today. Try again tomorrow!"

            new_balance = balance + DAILY_REWARD
            cursor.execute("UPDATE currency SET balance = ?, last_claim_date = ? WHERE user_id = ?",
                          (new_balance, today.strftime("%Y-%m-%d"), user_id))
            return True, new_balance, f"You've claimed your daily reward of 💰 {DAILY_REWARD}!"
        else:
            # New user
            new_balance = STARTING_BALANCE + DAILY_REWARD
            cursor.execute("INSERT INTO currency (user_id, balance, last_claim_date) VALUES (?, ?, ?)",
                          (user_id, new_balance, today.strftime("%Y-%m-%d")))
            return True, new_balance, f"Welcome! You've received 💰 {STARTING_BALANCE} starting balance + 💰 {DAILY_REWARD} daily reward!"


# ============== Stats Operations ==============

def update_stats(user_id, winnings: int, bet: int, final_grid=None):
    """Update user's game statistics."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM stats WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()

        most_common_symbol = None
        if final_grid is not None:
            most_common_counts = {}
            for row in final_grid:
                for symbol in row:
                    most_common_counts[symbol] = most_common_counts.get(symbol, 0) + 1
            most_common_symbol = max(most_common_counts, key=most_common_counts.get)

        profit = max(0, winnings - bet)
        win = winnings > bet

        if result:
            _, _, wins, losses, total_earned, _, largest_win = result
            wins += 1 if win else 0
            losses += 0 if win else 1
            total_earned += profit
            largest_win = max(largest_win, profit)

            cursor.execute("""
                UPDATE stats SET
                    games_played = games_played + 1,
                    wins = ?,
                    losses = ?,
                    total_earned = ?,
                    most_common_symbol = ?,
                    largest_win = ?
                WHERE user_id = ?
            """, (wins, losses, total_earned, most_common_symbol or "", largest_win, user_id))
        else:
            cursor.execute("""
                INSERT INTO stats (user_id, games_played, wins, losses, total_earned, most_common_symbol, largest_win)
                VALUES (?, 1, ?, ?, ?, ?, ?)
            """, (user_id, 1 if win else 0, 0 if win else 1, profit, most_common_symbol or "", profit))


def update_blackjack_stats(user_id, winnings: int, is_win: bool):
    """Update user's blackjack statistics."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM blackjack_stats WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()

        if result:
            bj_wins, bj_losses, bj_total, bj_largest = result[1:]
            if is_win:
                bj_wins += 1
                bj_total += winnings
                bj_largest = max(bj_largest, winnings)
            else:
                bj_losses += 1

            cursor.execute("""
                UPDATE blackjack_stats SET
                    blackjack_wins = ?,
                    blackjack_losses = ?,
                    blackjack_total_earned = ?,
                    blackjack_largest_win = ?
                WHERE user_id = ?
            """, (bj_wins, bj_losses, bj_total, bj_largest, user_id))
        else:
            cursor.execute("""
                INSERT INTO blackjack_stats (user_id, blackjack_wins, blackjack_losses, blackjack_total_earned, blackjack_largest_win)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, 1 if is_win else 0, 0 if is_win else 1, winnings if is_win else 0, winnings if is_win else 0))


def get_user_profile(user_id) -> dict:
    """Get comprehensive user profile data."""
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT games_played, wins, losses, total_earned, most_common_symbol, largest_win FROM stats WHERE user_id = ?", (user_id,))
        stats_row = cursor.fetchone()

        cursor.execute("SELECT blackjack_wins, blackjack_losses, blackjack_total_earned, blackjack_largest_win FROM blackjack_stats WHERE user_id = ?", (user_id,))
        blackjack_row = cursor.fetchone()

        cursor.execute("SELECT balance FROM currency WHERE user_id = ?", (user_id,))
        balance_row = cursor.fetchone()

    return {
        "balance": balance_row[0] if balance_row else STARTING_BALANCE,
        "stats": stats_row,
        "blackjack": blackjack_row if blackjack_row else (0, 0, 0, 0)
    }
