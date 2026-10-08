"""
BankRoll Discord Bot - Main Entry Point

A fun entertainment Discord bot featuring casino-style games with virtual currency.
"""

import os
import logging
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# Import bot modules
from bot.config import DB_FILE, ADMIN_GUILD_ID
from bot.database import init_db
from bot.commands import economy, admin, general
from bot.games import slots, blackjack, coinflip

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Load environment variables (a local file for development; on hosting platforms
# like Railway the variable is set in the dashboard and this is a no-op)
load_dotenv("bot_key.env")

bot_token = os.getenv("DISCORD_BOT_TOKEN")
if not bot_token:
    raise ValueError("DISCORD_BOT_TOKEN is not set. Put it in bot_key.env or in the environment variables.")

# Initialize database
init_db()
logger.info("Database initialized at %s", os.path.abspath(DB_FILE))


class BankRollBot(commands.Bot):
    """Custom bot class for BankRoll."""

    def __init__(self):
        # Slash commands only — no privileged intents needed
        super().__init__(command_prefix=commands.when_mentioned, intents=discord.Intents.default(), help_command=None)

    async def setup_hook(self):
        """Register and sync commands once at startup (on_ready can fire on every reconnect)."""
        economy.setup(self)
        admin.setup(self)
        general.setup(self)

        slots.setup(self)
        blackjack.setup(self)
        coinflip.setup(self)

        self.tree.on_error = self.on_app_command_error

        synced = await self.tree.sync()
        logger.info("Synced %d command(s) globally.", len(synced))
        if ADMIN_GUILD_ID:
            synced = await self.tree.sync(guild=discord.Object(ADMIN_GUILD_ID))
            logger.info("Synced %d admin command(s) to guild %d.", len(synced), ADMIN_GUILD_ID)

    async def on_ready(self):
        logger.info("Logged on as %s (in %d servers)", self.user, len(self.guilds))

    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CheckFailure):
            message = "❌ You don't have permission to use this command."
        else:
            logger.error("Error in /%s", interaction.command.qualified_name if interaction.command else "?", exc_info=error)
            message = "❌ Something went wrong. Please try again."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            pass


def main():
    """Main entry point."""
    client = BankRollBot()
    client.run(bot_token, log_handler=None)


if __name__ == "__main__":
    main()
