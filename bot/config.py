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

# Custom status shown under the bot's name. Set BOT_STATUS to change it, or to an empty value to hide it.
BOT_STATUS = os.getenv("BOT_STATUS", "🎰 Big visual update! Type /help to start")

# One-time update notice, posted publicly once per server after the first command used there.
# The embed itself is built in bot/commands/general.py (build_announcement_embed).
# Change ANNOUNCEMENT_ID to show a new announcement to everyone again; set it to "" to disable.
ANNOUNCEMENT_ID = "2026-10-visual-update"

# Economy settings
MAX_BET = 10000
MIN_BET = 1
DAILY_REWARD = 50
# Daily reward by streak day (claiming on consecutive UTC days). Day 1 = DAILY_REWARD,
# after the last entry the reward stays at the maximum. Missing a day resets the streak.
DAILY_STREAK_REWARDS = [DAILY_REWARD, 55, 60, 70, 80, 90, 100]
STARTING_BALANCE = 100
MAX_TRANSFER = 1_000_000

# Progression: XP per finished game (any game) and bonus XP for a win.
XP_PER_GAME = 10
XP_PER_WIN = 5

# Slot machine configuration
SLOT_SYMBOLS = ["\U0001f34b", "\U0001f352", "\U0001f349", "\U0001f514", "⭐", "\U0001f48e"]

SYMBOL_WEIGHTS = {
    "\U0001f34b": 0.3,
    "\U0001f352": 0.27,
    "\U0001f349": 0.2,
    "\U0001f514": 0.1,
    "⭐": 0.08,
    "\U0001f48e": 0.05
}

# Multiplier per winning line. All 8 lines (3 rows, 3 columns, 2 diagonals) pay and are summed.
# Expected return = 8 * sum(weight^3 * multiplier) = ~95.6% of the bet.
SLOT_PAYOUTS = {
    "\U0001f34b\U0001f34b\U0001f34b": 1,
    "\U0001f352\U0001f352\U0001f352": 2,
    "\U0001f349\U0001f349\U0001f349": 3,
    "\U0001f514\U0001f514\U0001f514": 10,
    "⭐⭐⭐": 25,
    "\U0001f48e\U0001f48e\U0001f48e": 50
}

# An animated GIF starts when the player's client has loaded it, which is later than the upload finishing.
# Result text waits this much longer (seconds) so it doesn't spoil the animation.
RESULT_DELAY_MARGIN = 1.5

# Game timeouts (in seconds)
GAME_TIMEOUT = 60
