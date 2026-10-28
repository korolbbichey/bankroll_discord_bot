"""
Utility functions for the BankRoll Discord Bot.
"""

import discord
from discord import app_commands

from .config import MIN_BET, MAX_BET
from .database import get_balance


def fmt(amount: int) -> str:
    """Format a coin amount with thousands separators: 1234567 -> '1,234,567'."""
    return f"{amount:,}"


def display_name(user: discord.abc.User) -> str:
    """The user's global display name, falling back to their username (server nicknames are ignored)."""
    return user.global_name or user.name


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
        return False, f"You don't have enough coins for that bet (balance: {fmt(balance)})."
    return True, ""
