"""
Utility functions for the BankRoll Discord Bot.
"""

import asyncio
import io
import logging

import discord
from discord import app_commands
from PIL import Image

from .config import MIN_BET, MAX_BET, CONFIRM_BET_SHARE, CONFIRM_BET_MIN_BALANCE
from .database import get_balance, set_bet_confirmation, wants_bet_confirmation


# Drawing images briefly takes tens of MB of memory, so only a couple are drawn at once.
DRAW_SLOTS = asyncio.Semaphore(2)

logger = logging.getLogger(__name__)


def last_frame_png(gif: bytes) -> bytes:
    """A game GIF's final picture as a PNG. Our GIFs draw every frame in full, so the last one is complete."""
    with Image.open(io.BytesIO(gif)) as image:
        image.seek(image.n_frames - 1)
        output = io.BytesIO()
        image.convert("RGB").save(output, format="PNG", optimize=True)
    return output.getvalue()


async def still_of(gif: bytes, filename: str) -> discord.File | None:
    """
    The GIF's last frame as a file to show with the result. Discord plays a GIF again whenever its message is
    edited, so the result swaps the animation for this still. None if it can't be drawn (keep the GIF then).
    """
    try:
        return discord.File(io.BytesIO(await asyncio.to_thread(last_frame_png, gif)), filename=filename)
    except Exception:
        logger.exception("Failed to draw the still picture")
        return None


def fmt(amount: int) -> str:
    """Format a coin amount with thousands separators: 1234567 -> '1,234,567'."""
    return f"{amount:,}"


def display_name(user: discord.abc.User) -> str:
    """The user's global display name, falling back to their username (server nicknames are ignored)."""
    return user.global_name or user.name


def avatar_hash(user: discord.abc.User) -> str:
    """The hash of the user's own avatar, or "" if they use a default one."""
    return user.avatar.key if user.avatar else ""


class InvalidBet(app_commands.AppCommandError):
    """A bet that isn't a number, 'all' or 'half'. The message is shown to the player."""


def parse_bet(text: str, balance: int) -> int:
    """
    Turn a bet option into coins:
    'all' -> the whole balance, 'half' -> half of it (both capped at MAX_BET),
    or a number such as '500', '1,000' or '2.5k'.
    Results below MIN_BET become MIN_BET, so validate_bet can report a too-small balance clearly.
    """
    value = text.strip().lower().replace(",", "").replace("_", "").replace(" ", "")
    if value == "all":
        bet = balance
    elif value == "half":
        bet = balance // 2
    else:
        multiplier = 1000 if value.endswith("k") else 1
        try:
            amount = float(value.removesuffix("k")) * multiplier
        except ValueError:
            raise InvalidBet("❌ Bet must be a number, `all` or `half`.") from None
        if amount != amount or amount in (float("inf"), float("-inf")) or amount != int(amount):
            raise InvalidBet("❌ Bet must be a whole number of coins.")
        return int(amount)
    return max(MIN_BET, min(bet, MAX_BET))


class BetTransformer(app_commands.Transformer):
    """The `bet` option of the games: a number, `all` or `half`, with live suggestions."""

    @property
    def type(self) -> discord.AppCommandOptionType:
        return discord.AppCommandOptionType.string

    async def transform(self, interaction: discord.Interaction, value: str) -> int:
        return parse_bet(value, get_balance(interaction.user.id))

    async def autocomplete(self, interaction: discord.Interaction, value: str) -> list[app_commands.Choice[str]]:
        """Suggest 'all' and 'half' with the actual amounts; echo a typed number back formatted."""
        balance = get_balance(interaction.user.id)
        typed = value.strip().lower()
        keywords = [word for word in ("all", "half") if word.startswith(typed)]
        if keywords:
            return [app_commands.Choice(name=f"{word} — {fmt(parse_bet(word, balance))} coins", value=word)
                    for word in keywords]
        try:
            return [app_commands.Choice(name=f"{fmt(parse_bet(typed, balance))} coins", value=value.strip())]
        except InvalidBet:
            return []


Bet = app_commands.Transform[int, BetTransformer]


class ConfirmBetView(discord.ui.View):
    """Asks once before a bet of more than half the balance. Nothing is taken until the player confirms."""

    def __init__(self, user_id: int, start):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.start = start  # async function that starts the game for an interaction
        self.used = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.used:
            await interaction.response.send_message("You already answered.", ephemeral=True)
            return False
        self.used = True
        self.stop()
        return True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, _):
        await self.start(interaction)

    @discord.ui.button(label="Confirm, don't ask again", style=discord.ButtonStyle.secondary)
    async def confirm_always(self, interaction: discord.Interaction, _):
        set_bet_confirmation(self.user_id, False)
        await self.start(interaction)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, _):
        await interaction.response.edit_message(content="👍 Bet cancelled.", view=None)


async def confirm_big_bet(interaction: discord.Interaction, bet: int, start) -> bool:
    """
    Ask before a bet of more than half the balance (from CONFIRM_BET_MIN_BALANCE coins).
    Returns True if the question was asked: the caller stops, and `start(interaction)` runs on Confirm.
    """
    user_id = interaction.user.id
    balance = get_balance(user_id)
    if (balance < CONFIRM_BET_MIN_BALANCE or bet <= balance * CONFIRM_BET_SHARE or bet > balance
            or not wants_bet_confirmation(user_id)):
        return False
    share = "all" if bet == balance else f"{bet / balance:.0%}"
    await interaction.response.send_message(
        f"⚠️ That's **{share}** of your coins: bet **{fmt(bet)}** of **{fmt(balance)}**?",
        view=ConfirmBetView(user_id, start), ephemeral=True)
    return True


def validate_bet(bet: int, balance: int) -> tuple[bool, str]:
    """
    Validate a bet amount.
    Returns: (is_valid, error_message)
    """
    if bet < MIN_BET:
        return False, f"Minimum bet is {fmt(MIN_BET)} coins."
    if bet > MAX_BET:
        return False, f"Maximum bet is {fmt(MAX_BET)} coins."
    if bet > balance:
        hint = " Try `/daily_reward` or `/bailout`." if balance < MIN_BET else ""
        return False, f"You don't have enough coins for that bet (balance: {fmt(balance)}).{hint}"
    return True, ""
