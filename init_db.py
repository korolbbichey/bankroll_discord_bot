"""
Database initialization script for BankRoll Discord Bot.
This script can be run standalone to create the database tables.
Note: The main bot (main.py) also initializes the database on startup.
"""

from bot.config import DB_FILE
from bot.database import init_db


if __name__ == "__main__":
    init_db()
    print(f"Database '{DB_FILE}' initialized.")
