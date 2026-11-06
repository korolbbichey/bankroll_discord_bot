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
BOT_STATUS = os.getenv("BOT_STATUS", "🎡 New: Roulette! Type /help to start")

# One-time update notice, posted publicly once per server after the first command used there.
# The embed itself is built in bot/commands/general.py (build_announcement_embed).
# Change ANNOUNCEMENT_ID to show a new announcement to everyone again; set it to "" to disable.
ANNOUNCEMENT_ID = "2026-11-roulette-update"

# Economy settings
MAX_BET = 10000
MIN_BET = 1
DAILY_REWARD = 50
# Daily reward by streak day (claiming on consecutive UTC days). Day 1 = DAILY_REWARD,
# after the last entry the reward stays at the maximum. Missing a day resets the streak.
DAILY_STREAK_REWARDS = [DAILY_REWARD, 55, 60, 70, 80, 90, 100]
STARTING_BALANCE = 100
# Help for players who ran out of coins: once per UTC day, only with an empty balance.
BAILOUT_AMOUNT = 25
# Bet used by the quick-play buttons under the daily reward.
QUICK_PLAY_BET = 10
# Wins and transfers of at least this size are logged, so /admin stats can show where big balances came from.
COIN_EVENT_MIN = 1000
DUEL_TIMEOUT = 120  # seconds to accept a duel
MAX_TRANSFER = 1_000_000

# Progression: XP per finished game (any game) and bonus XP for a win.
XP_PER_GAME = 10
XP_PER_WIN = 5
# Coins for reaching a level: the new level times this.
LEVEL_UP_REWARD = 25

# How hard each badge is to get: sets the color of its medal and the coins it gives once.
BADGE_RARITY = {
    "first_win": "common", "explorer": "common", "generous": "common", "coin_10": "common", "double_win": "common",
    "spins_100": "rare", "natural": "rare", "week_streak": "rare", "duelist": "rare", "multi_line": "rare",
    "max_bet": "rare",
    "rich": "epic", "grand_tour": "epic", "bullseye": "epic", "duel_5": "epic", "jackpot": "epic",
    "diamond_line": "legendary", "podium": "legendary", "zero": "legendary", "veteran": "legendary",
    "month_streak": "legendary",
}
BADGE_REWARDS = {"common": 50, "rare": 150, "epic": 500, "legendary": 1500}
# The day badges started paying. Badges earned before it are paid once when the bot starts (badge_backpay).
BADGE_REWARDS_SINCE = "2026-11-06"

# /work: a short task once per WORK_COOLDOWN seconds. A right answer pays the full amount, a wrong one a little.
WORK_COOLDOWN = 3600
WORK_PAY = (20, 35)
WORK_PAY_WRONG = 8
WORK_ANSWER_SECONDS = 20
# (shifts needed, job title, bonus coins per shift)
WORK_RANKS = [(0, "Trainee", 0), (10, "Dealer", 5), (30, "Pit Boss", 10), (75, "Casino Manager", 20)]

# Bets over half the balance ask for a confirmation first, unless the player turned it off.
CONFIRM_BET_SHARE = 0.5
CONFIRM_BET_MIN_BALANCE = 100

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
# Slots are played many times in a row, so their result waits less.
SLOTS_RESULT_DELAY_MARGIN = 1.0

# Slots autoplay: spins on its own, each with the normal animation, AUTOPLAY_DELAY seconds apart after the result.
AUTOPLAY_MAX_SPINS = 50
AUTOPLAY_BUTTON_SPINS = 10      # spins started by the "Auto" button
AUTOPLAY_DELAY = 0.8           # a moment to see the result before the next spin
AUTOPLAY_STOP_MULTIPLIER = 10   # autoplay pauses on a win of this many bets, so the player sees it
AUTOPLAY_LOG_SIZE = 5           # recent spins listed under the picture
AUTOPLAY_MAX_PER_PLAYER = 3     # autoplays one player can run at the same time (each draws a GIF per spin)

# Game timeouts (in seconds)
GAME_TIMEOUT = 60
