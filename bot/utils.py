"""
Utility functions for the BankRoll Discord Bot.
"""

from .config import MIN_BET, MAX_BET


def validate_bet(bet: int, balance: int) -> tuple[bool, str]:
    """
    Validate a bet amount.
    Returns: (is_valid, error_message)
    """
    if bet < MIN_BET:
        return False, f"Minimum bet is {MIN_BET} coins."
    if bet > MAX_BET:
        return False, f"Maximum bet is {MAX_BET} coins."
    if bet > balance:
        return False, "You don't have enough balance for that bet."
    return True, ""
