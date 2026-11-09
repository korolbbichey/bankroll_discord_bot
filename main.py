"""
BankRoll Discord Bot - Main Entry Point

A fun entertainment Discord bot featuring casino-style games with virtual currency.
"""

import os
import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# Import bot modules
from bot.config import DB_FILE, ADMIN_GUILD_ID, BOT_STATUS, ANNOUNCEMENT_ID
from bot.database import (
    init_db, mark_announcement_shown, refund_pending_duels, save_username, take_backpay_notice,
    get_changelog_seen, mark_changelog_seen,
)
from bot import changelog
from bot.utils import display_name, avatar_hash, InvalidBet
from bot.commands import economy, admin, general, work
from bot.games import slots, blackjack, coinflip, duel, roulette

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
# Duels left waiting by the last shutdown can't be answered any more: their buttons died with the old process.
if refunded := refund_pending_duels():
    logger.info("Refunded %d unanswered duel(s) from before the restart.", refunded)


class BankRollBot(commands.Bot):
    """Custom bot class for BankRoll."""

    def __init__(self):
        # Slash commands only — no privileged intents needed
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=discord.Intents.default(),
            help_command=None,
            activity=discord.CustomActivity(name=BOT_STATUS) if BOT_STATUS else None,
            # Commands work when the bot is added to a server *or* to a user's profile (User Install),
            # and can be used in servers, DMs and group chats.
            allowed_installs=app_commands.AppInstallationType(guild=True, user=True),
            allowed_contexts=app_commands.AppCommandContext(guild=True, dm_channel=True, private_channel=True),
        )
        self.known_names: dict[int, tuple[str, str]] = {}

    async def setup_hook(self):
        """Register and sync commands once at startup (on_ready can fire on every reconnect)."""
        economy.setup(self)
        admin.setup(self)
        general.setup(self)
        work.setup(self)

        slots.setup(self)
        blackjack.setup(self)
        coinflip.setup(self)
        roulette.setup(self)
        duel.setup(self)

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
        await self.maybe_tell_backpay(interaction)
        await self.maybe_tell_changes(interaction)

    def remember_name(self, user: discord.abc.User):
        """Keep the player's name and avatar hash in the database for the leaderboard (DB write only when they change)."""
        known = (display_name(user), avatar_hash(user))
        if self.known_names.get(user.id) == known:
            return
        try:
            if save_username(user.id, *known):
                self.known_names[user.id] = known
        except Exception:
            logger.exception("Failed to save username")

    async def maybe_announce(self, interaction: discord.Interaction):
        """
        Post the current update announcement once per server, publicly, in the channel the command was used in.
        This only happens in servers where the bot is installed: when it is used through a user's profile
        (User Install), Discord may hide replies from the rest of the server, so it is shown once per user, privately.
        """
        if not ANNOUNCEMENT_ID or not interaction.response.is_done():
            return
        public = interaction.is_guild_integration()
        try:
            if mark_announcement_shown(interaction.guild_id if public else interaction.user.id, ANNOUNCEMENT_ID):
                await interaction.followup.send(embed=general.build_announcement_embed(), ephemeral=not public)
        except Exception:
            logger.exception("Failed to send announcement")

    async def maybe_tell_backpay(self, interaction: discord.Interaction):
        """Tell a player, privately and once, about the coins paid for the badges they collected before rewards."""
        if not interaction.response.is_done():
            return
        try:
            paid = take_backpay_notice(interaction.user.id)
            if paid:
                coins, badges = paid
                await interaction.followup.send(
                    f"🎁 Badges pay coins now! You got **+{coins:,} coins** for the {badges} "
                    f"badge{'s' if badges != 1 else ''} you collected before. Thanks for playing!", ephemeral=True)
        except Exception:
            logger.exception("Failed to tell about the badge backpay")

    async def maybe_tell_changes(self, interaction: discord.Interaction):
        """Tell a player, privately and once, what changed since they were last told (bot/changelog.py)."""
        if not interaction.response.is_done() or (interaction.command and interaction.command.name == "updates"):
            return
        try:
            user_id = interaction.user.id
            last_seen, first_played, veteran = get_changelog_seen(user_id)
            if last_seen == changelog.latest_id():
                return
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            entries = changelog.unseen_entries(last_seen, first_played, veteran, today)
            # Marked first, so two commands at once can't both send it.
            if mark_changelog_seen(user_id, changelog.latest_id()) and entries:
                await interaction.followup.send(changelog.notice_text(entries), ephemeral=True)
        except Exception:
            logger.exception("Failed to tell about the changes")

    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, InvalidBet):
            message = str(error)
        elif isinstance(error, app_commands.CheckFailure):
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
