"""
Configuration settings for the BankRoll Discord Bot.
"""

# Database
DB_FILE = "bot_data.db"

# Economy settings
MAX_BET = 10000
MIN_BET = 1
DAILY_REWARD = 50
STARTING_BALANCE = 100

# Slot machine configuration
SLOT_SYMBOLS = ["🍒", "🍉", "🔔", "⭐", "💎", "🤡"]

SYMBOL_WEIGHTS = {
    "🍒": 0.27,
    "🍉": 0.2,
    "🔔": 0.1,
    "⭐": 0.08,
    "💎": 0.05,
    "🤡": 0.3
}

SLOT_PAYOUTS = {
    "🍒🍒🍒": 5,
    "🍉🍉🍉": 10,
    "🔔🔔🔔": 20,
    "⭐⭐⭐": 50,
    "💎💎💎": 100
}

# Game timeouts (in seconds)
GAME_TIMEOUT = 60
