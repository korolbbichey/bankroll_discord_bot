"""
Database initialization script for BankRoll Discord Bot.
This script can be run standalone to initialize/reset the database.
Note: The main bot (main.py) also initializes the database on startup.
"""

import sqlite3

DB_FILE = "bot_data.db"

def init_database():
    """Initialize all database tables."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS currency (
        user_id INTEGER PRIMARY KEY,
        balance INTEGER DEFAULT 100,
        last_claim_date TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS stats (
        user_id INTEGER PRIMARY KEY,
        games_played INTEGER DEFAULT 0,
        wins INTEGER DEFAULT 0,
        losses INTEGER DEFAULT 0,
        total_earned INTEGER DEFAULT 0,
        most_common_symbol TEXT DEFAULT '{}',
        largest_win INTEGER DEFAULT 0
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS blackjack_stats (
        user_id INTEGER PRIMARY KEY,
        blackjack_wins INTEGER DEFAULT 0,
        blackjack_losses INTEGER DEFAULT 0,
        blackjack_total_earned INTEGER DEFAULT 0,
        blackjack_largest_win INTEGER DEFAULT 0
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS challenges (
        user_id INTEGER PRIMARY KEY,
        daily_wins INTEGER DEFAULT 0,
        weekly_wins INTEGER DEFAULT 0,
        last_daily_reset INTEGER DEFAULT 0,
        last_weekly_reset INTEGER DEFAULT 0
    )
    """)

    conn.commit()
    conn.close()

    print(f"Database '{DB_FILE}' initialized with tables: currency, stats, blackjack_stats, challenges")


if __name__ == "__main__":
    init_database()
