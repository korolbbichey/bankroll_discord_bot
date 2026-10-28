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
from bot.config import DB_FILE, ADMIN_GUILD_ID, BOT_STATUS, ANNOUNCEMENT_ID
from bot.database import init_db, mark_announcement_shown, save_username
from bot.utils import display_name
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
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=discord.Intents.default(),
            help_command=None,
            activity=discord.CustomActivity(name=BOT_STATUS) if BOT_STATUS else None,
        )
        self.known_names: dict[int, str] = {}

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

    async def on_app_command_completion(self, interaction: discord.Interaction, command):
        self.remember_name(interaction.user)
        await self.maybe_announce(interaction)

    def remember_name(self, user: discord.abc.User):
        """Keep the player's display name in the database for the leaderboard (DB write only when it changes)."""
        name = display_name(user)
        if self.known_names.get(user.id) == name:
            return
        try:
            if save_username(user.id, name):
                self.known_names[user.id] = name
        except Exception:
            logger.exception("Failed to save username")

    async def maybe_announce(self, interaction: discord.Interaction):
        """Post the current update announcement once per server, publicly, in the channel the command was used in.
        Outside servers (DMs) it is shown once per user, privately."""
        if not ANNOUNCEMENT_ID or not interaction.response.is_done():
            return
        in_server = interaction.guild_id is not None
        try:
            if mark_announcement_shown(interaction.guild_id if in_server else interaction.user.id, ANNOUNCEMENT_ID):
                await interaction.followup.send(embed=general.build_announcement_embed(), ephemeral=not in_server)
        except Exception:
            logger.exception("Failed to send announcement")

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
