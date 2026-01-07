"""
BankRoll Discord Bot - Main Entry Point

A fun entertainment Discord bot featuring casino-style games with virtual currency.
"""

import os
import logging
import discord
from discord.ext import commands
from dotenv import load_dotenv

# Import bot modules
from bot.database import init_db
from bot.commands import economy, admin, general
from bot.games import slots, blackjack, coinflip

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv("bot_key.env")

bot_token = os.getenv("DISCORD_BOT_TOKEN")
if not bot_token:
    raise ValueError("Bot token not found in .env file. Check the file path and variable name.")

logger.info("Bot token loaded successfully.")

# Initialize database
init_db()
logger.info("Database initialized.")


class BankRollBot(commands.Bot):
    """Custom bot class for BankRoll."""

    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='/', intents=intents)

    async def setup_hook(self):
        """Setup commands when bot starts."""
        # Register all command modules
        economy.setup(self)
        admin.setup(self)
        general.setup(self)

        # Register all game modules
        slots.setup(self)
        blackjack.setup(self)
        coinflip.setup(self)

        logger.info("All commands registered.")

    async def on_ready(self):
        """Called when bot is ready."""
        logger.info(f'Logged on as {self.user}')
        try:
            synced = await self.tree.sync()
            logger.info(f"Synced {len(synced)} command(s) globally.")
        except Exception as e:
            logger.error(f"Failed to sync commands: {e}")


def main():
    """Main entry point."""
    client = BankRollBot()
    client.run(bot_token)


if __name__ == "__main__":
    main()
