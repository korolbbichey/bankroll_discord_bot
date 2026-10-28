"""
Utility functions for the BankRoll Discord Bot.
"""

import discord

from .config import MIN_BET, MAX_BET


def fmt(amount: int) -> str:
    """Format a coin amount with thousands separators: 1234567 -> '1,234,567'."""
    return f"{amount:,}"


def display_name(user: discord.abc.User) -> str:
    """The user's global display name, falling back to their username (server nicknames are ignored)."""
    return user.global_name or user.name


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
