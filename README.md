# BankRoll Discord Bot

A fun entertainment Discord bot featuring casino-style games with virtual currency. Users can play slots, blackjack, and coinflip while tracking their stats and competing on the leaderboard.

## Features

### Interactive Games
- **Slots** (`/slots <bet>`) - 3x3 slot machine with animated spins, 8 paying lines, and adjustable bets (~95% return)
- **Blackjack** (`/blackjack <bet>`) - Classic 21 with Hit/Stand/Double actions, natural blackjack pays 3:2
- **Coin Flip** (`/coinflip <guess> <bet>`) - Simple heads/tails game with 2x payout

### Economy System
- **Balance** (`/balance`) - Check your virtual currency
- **Daily Reward** (`/daily_reward`) - Claim 50 coins daily
- **Leaderboard** (`/leaderboard`) - View top 5 richest players

### User Profiles
- **Profile** (`/profile [@user]`) - View comprehensive stats including:
  - Games played, wins, losses, win rate
  - Total earned, largest win
  - Separate Blackjack statistics

### Admin Commands
Balances are shared across every server, so these are restricted to the **bot owner** (the application owner in the Developer Portal, plus anyone listed in `OWNER_IDS`):
- **Add Balance** (`/add_balance <user> <amount>`) - add currency to a player
- **Remove Balance** (`/remove_balance <user> <amount>`) - remove currency from a player

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
│   │   ├── economy.py     # Balance, daily, leaderboard, profile
│   │   ├── admin.py       # Admin commands
│   │   └── general.py     # Help, ToS
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

## Deploying to Railway

1. Push the repo to GitHub and create a new Railway project from it. `railway.json` sets the start command (`python main.py`) and restart policy.
2. In the service **Variables**, add `DISCORD_BOT_TOKEN` (and optionally `OWNER_IDS`).
3. **Attach a Volume** to the service (e.g. mount path `/data`). The bot automatically stores `bot_data.db` in the volume via `RAILWAY_VOLUME_MOUNT_PATH`. Without a volume, all balances are wiped on every redeploy.
4. No public domain or port is needed — the bot only makes outbound connections.

To move an existing database, upload `bot_data.db` into the volume (for example with `railway ssh`) before the first start.

## Configuration

Environment variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_BOT_TOKEN` | yes | Bot token |
| `OWNER_IDS` | no | Comma-separated user IDs allowed to use admin commands |
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
| 3x Cherry (🍒) | 2x bet |
| 3x Watermelon (🍉) | 5x bet |
| 3x Bell (🔔) | 15x bet |
| 3x Star (⭐) | 30x bet |
| 3x Diamond (💎) | 75x bet |

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

## Tech Stack

- **discord.py** - Discord API wrapper
- **SQLite** - Lightweight database for persistent storage
- **python-dotenv** - Environment variable management

## Database Schema

The bot uses SQLite with these tables:
- `currency` - User balances and daily claim tracking
- `stats` - Slots and coinflip statistics
- `blackjack_stats` - Blackjack-specific statistics
- `symbol_counts` - Per-user slot symbol counts (for "most common symbol")

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is open source and available under the MIT License.

> **Note:** This bot uses virtual currency only. No real money is involved, and users cannot lose actual funds. This is purely for entertainment purposes.
