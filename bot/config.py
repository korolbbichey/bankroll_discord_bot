"""
Configuration settings for the BankRoll Discord Bot.
"""

import os

# Database
# DB_PATH wins; otherwise use a Railway volume if one is attached; otherwise the project folder.
_volume = os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
DB_FILE = os.getenv("DB_PATH") or (os.path.join(_volume, "bot_data.db") if _volume else "bot_data.db")

# Extra bot owners allowed to use admin commands (comma-separated Discord user IDs).
# The application owner from the Developer Portal is always allowed.
OWNER_IDS = {int(x) for x in os.getenv("OWNER_IDS", "").replace(" ", "").split(",") if x}

# Private server where the /admin commands are registered. They are not registered
# anywhere else, so they don't show up in other servers or on the bot's profile.
ADMIN_GUILD_ID = int(os.getenv("ADMIN_GUILD_ID") or 0) or None

# Economy settings
MAX_BET = 10000
MIN_BET = 1
DAILY_REWARD = 50
STARTING_BALANCE = 100
MAX_TRANSFER = 1_000_000

# Slot machine configuration
SLOT_SYMBOLS = ["\U0001f352", "\U0001f349", "\U0001f514", "⭐", "\U0001f48e", "\U0001f921"]

SYMBOL_WEIGHTS = {
    "\U0001f352": 0.27,
    "\U0001f349": 0.2,
    "\U0001f514": 0.1,
    "⭐": 0.08,
    "\U0001f48e": 0.05,
    "\U0001f921": 0.3
}

# Multiplier per winning line. All 8 lines (3 rows, 3 columns, 2 diagonals) pay and are summed.
# With these weights the expected return is ~95.3% of the bet.
SLOT_PAYOUTS = {
    "\U0001f352\U0001f352\U0001f352": 2,
    "\U0001f349\U0001f349\U0001f349": 5,
    "\U0001f514\U0001f514\U0001f514": 15,
    "⭐⭐⭐": 30,
    "\U0001f48e\U0001f48e\U0001f48e": 75
}

# Game timeouts (in seconds)
GAME_TIMEOUT = 60
