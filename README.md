# BankRoll Discord Bot

A fun entertainment Discord bot featuring casino-style games with virtual currency. Users can play slots, blackjack, and coinflip while tracking their stats and competing on the leaderboard.

## Features

### Interactive Games
- **Slots** (`/slots <bet>`) - 3x3 slot machine with animated spins, 8 paying lines, and adjustable bets (~95% return)
- **Blackjack** (`/blackjack <bet>`) - Classic 21 with Hit/Stand/Double actions, natural blackjack pays 3:2
- **Coin Flip** (`/coinflip <guess> <bet>`) - Simple heads/tails game with 2x payout

`<bet>` can be a number (`500`, `1,000`, `2.5k`), `all` or `half` of your balance (capped at the maximum bet). Discord suggests `all` / `half` with the actual amounts while typing.

### Economy System
- **Balance** (`/balance [@user]`) - Check your own or another player's coins
- **Daily Reward** (`/daily_reward`) - Claim coins every day; consecutive days build a 🔥 streak (50 → 55 → 60 → 70 → 80 → 90 → 100 coins, configurable via `DAILY_STREAK_REWARDS`). Missing a day resets the streak
- **Pay** (`/pay <@user> <amount>`) - Send coins to another player
- **Leaderboard** (`/leaderboard`) - Top 10 richest players and your own position
- **Help** (`/help`) - Command list, slot payouts and Terms of Service

### User Profiles
- **Profile** (`/profile [@user]`) - A player card with:
  - **Level and title** — every game gives XP (10, +5 for a win). Titles: 🪙 Rookie (1) → 🎲 Gambler (3) → 💼 High Roller (6) → 🎩 Card Shark (10) → 👑 Casino King (15) → 💎 Legend (25). The card color follows the title
  - **Badges** — 13 achievements (first win, 100 spins, 💎💎💎 line, natural 21, 7-day streak, 10,000 coins, top 3, ...) plus a hint for the next one
  - **Stats** — games, win rate and best win per game, total won, favorite game and lucky symbol, playing since

Level-ups and new badges are announced to the player privately right after the game. Rules live in `bot/progression.py`.

### Admin Commands
Balances are shared across every server, so admin commands are restricted to the **bot owner** (the application owner in the Developer Portal, plus anyone listed in `OWNER_IDS`). They are registered **only in the server set by `ADMIN_GUILD_ID`**, so they don't appear anywhere else or on the bot's profile. If `ADMIN_GUILD_ID` is not set, they are disabled.
- `/admin give <user> <amount>` - add coins to a player
- `/admin take <user> <amount>` - remove coins from a player
- `/admin set <user> <amount>` - set an exact balance

## Project Structure

```
bankroll_discord_bot/
├── main.py                 # Entry point
├── requirements.txt        # Dependencies
├── bot_key.env            # Bot token (create this)
├── bot_data.db            # SQLite database (auto-created)
│
├── bot/                   # Main bot package
│   ├── __init__.py
│   ├── config.py          # Configuration settings
│   ├── database.py        # Database operations
│   ├── utils.py           # Utility functions
│   │
│   ├── commands/          # Command modules
│   │   ├── __init__.py
│   │   ├── economy.py     # Balance, daily, pay, leaderboard, profile
│   │   ├── admin.py       # /admin give|take|set (private server only)
│   │   └── general.py     # Help
│   │
│   └── games/             # Game modules
│       ├── __init__.py
│       ├── slots.py       # Slot machine game
│       ├── blackjack.py   # Blackjack game
│       └── coinflip.py    # Coin flip game
```

## Installation

### Prerequisites
- Python 3.10 or higher
- A Discord Bot Token ([Create one here](https://discord.com/developers/applications))

### Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/korolbbichey/bankroll_discord_bot.git
   cd bankroll_discord_bot
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment variables**

   Create a file named `bot_key.env` in the project root:
   ```env
   DISCORD_BOT_TOKEN=your_bot_token_here
   ```

4. **Run the bot**
   ```bash
   python main.py
   ```

## Installing the Bot

Bankroll supports both install types (Developer Portal → **Installation**):
- **Guild Install** (scopes `applications.commands` + `bot`) — a server admin adds the bot to a server.
- **User Install** (scope `applications.commands`) — any user adds the bot to their own profile and can use every public command on any server, in DMs and in group chats, even where the bot isn't installed. In large servers (over 25 members) where the bot isn't installed, Discord shows its replies only to the player.

The `/admin` commands are always limited to the `ADMIN_GUILD_ID` server.

## Deploying to Railway

1. Push the repo to GitHub and create a new Railway project from it. `railway.json` sets the start command (`python main.py`) and restart policy.
2. In the service **Variables**, add `DISCORD_BOT_TOKEN` (and optionally `ADMIN_GUILD_ID` / `OWNER_IDS`).
3. **Attach a Volume** to the service (e.g. mount path `/data`). The bot automatically stores `bot_data.db` in the volume via `RAILWAY_VOLUME_MOUNT_PATH`. Without a volume, all balances are wiped on every redeploy.
4. No public domain or port is needed — the bot only makes outbound connections.

To move an existing database, upload `bot_data.db` into the volume (for example with `railway ssh`) before the first start.

## Configuration

Environment variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_BOT_TOKEN` | yes | Bot token |
| `OWNER_IDS` | no | Comma-separated user IDs allowed to use admin commands |
| `ADMIN_GUILD_ID` | no | ID of your private server where `/admin` commands appear (disabled if unset) |
| `DB_PATH` | no | Full path to the SQLite file (overrides the Railway volume default) |

Edit `bot/config.py` to customize settings:

| Setting | Default | Description |
|---------|---------|-------------|
| `MAX_BET` | 10000 | Maximum bet amount |
| `MIN_BET` | 1 | Minimum bet amount |
| `DAILY_REWARD` | 50 | Daily reward amount |
| `STARTING_BALANCE` | 100 | Initial balance for new users |
| `GAME_TIMEOUT` | 60 | Game session timeout in seconds |

### Slot Machine Payouts
Every line (3 rows, 3 columns, 2 diagonals) is checked and all winning lines are paid.

| Symbol | Payout per line |
|--------|--------|
| 3x Lemon (🍋) | 1x bet |
| 3x Cherry (🍒) | 2x bet |
| 3x Watermelon (🍉) | 3x bet |
| 3x Bell (🔔) | 10x bet |
| 3x Star (⭐) | 25x bet |
| 3x Diamond (💎) | 50x bet |

## Adding New Games

To add a new game, create a file in `bot/games/` following this pattern:

```python
# bot/games/my_game.py
import discord
from discord import app_commands

def setup(client):
    """Setup my_game command."""

    @client.tree.command(name="my_game", description="Play my game!")
    async def my_game(interaction: discord.Interaction, bet: int):
        # Your game logic here
        pass
```

Then import and register it in `main.py`:
```python
from bot.games import slots, blackjack, coinflip, my_game

# In setup_hook():
my_game.setup(self)
```

## Running Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

The tests use a temporary database and fake Discord interactions — they never touch `bot_data.db` and never connect to Discord. They cover the slot payouts and expected return, blackjack rules, balance atomicity, the daily reward, stats, the leaderboard, and the update announcement.

## Tech Stack

- **discord.py** - Discord API wrapper
- **SQLite** - Lightweight database for persistent storage
- **python-dotenv** - Environment variable management

## Database Schema

The bot uses SQLite with these tables:
- `currency` - User balances, daily claim tracking and cached display names (for the leaderboard)
- `stats` - Slots and coinflip statistics
- `blackjack_stats` - Blackjack-specific statistics
- `symbol_counts` - Per-user slot symbol counts (for "most common symbol")
- `announcements_shown` - Which servers have already seen the current update announcement

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is open source and available under the MIT License.

> **Note:** This bot uses virtual currency only. No real money is involved, and users cannot lose actual funds. This is purely for entertainment purposes.
