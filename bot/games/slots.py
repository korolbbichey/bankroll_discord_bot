"""
Slots game for the BankRoll Discord Bot.
"""

import discord
from discord import app_commands
import random
import asyncio
import logging

from ..config import SLOT_SYMBOLS, SYMBOL_WEIGHTS, SLOT_PAYOUTS, MIN_BET, MAX_BET, GAME_TIMEOUT
from ..database import get_balance, try_debit, credit, update_stats
from ..utils import validate_bet

logger = logging.getLogger(__name__)

_WEIGHTS = [SYMBOL_WEIGHTS[s] for s in SLOT_SYMBOLS]


def calculate_winnings(grid: list, bet: int) -> tuple[int, int]:
    """
    Calculate the payout from a slot grid.
    Every winning line (rows, columns, diagonals) pays. Returns (payout, winning_lines).
    """
    lines = grid + [list(col) for col in zip(*grid)] + [[grid[i][i] for i in range(3)], [grid[i][2-i] for i in range(3)]]
    payout, winning_lines = 0, 0
    for line in lines:
        multiplier = SLOT_PAYOUTS.get("".join(line))
        if multiplier:
            payout += multiplier * bet
            winning_lines += 1
    return payout, winning_lines


def format_grid(grid: list) -> str:
    """Format a slot grid for display."""
    return "```\n" + "\n".join([" | ".join(row) for row in grid]) + "\n```"


class SlotView(discord.ui.View):
    def __init__(self, user_id: int, bet: int):
        super().__init__(timeout=GAME_TIMEOUT)
        self.user_id = user_id
        self.bet = bet
        self.spinning = False
        self.last_result = ""
        self.last_interaction: discord.Interaction | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your game!", ephemeral=True)
            return False
        if self.spinning:
            await interaction.response.send_message("Wait for the current spin to finish.", ephemeral=True)
            return False
        return True

    def set_disabled(self, disabled: bool):
        for item in self.children:
            item.disabled = disabled

    def render(self) -> str:
        return f"{self.last_result}\n🎲 Current Bet: **{self.bet}**"

    async def on_timeout(self):
        self.set_disabled(True)
        if self.last_interaction:
            try:
                await self.last_interaction.edit_original_response(content=self.render() + "\n⌛ Session ended.", view=self)
            except discord.HTTPException:
                pass

    async def change_bet(self, interaction: discord.Interaction, new_bet: int):
        self.bet = max(MIN_BET, min(MAX_BET, new_bet))
        self.last_interaction = interaction
        await interaction.response.edit_message(content=self.render(), view=self)

    @discord.ui.button(label="Bet ½", style=discord.ButtonStyle.secondary)
    async def halve_bet(self, interaction: discord.Interaction, _):
        await self.change_bet(interaction, self.bet // 2)

    @discord.ui.button(label="Bet ×2", style=discord.ButtonStyle.secondary)
    async def double_bet(self, interaction: discord.Interaction, _):
        await self.change_bet(interaction, self.bet * 2)

    @discord.ui.button(label="Spin 🎰", style=discord.ButtonStyle.success)
    async def spin_again(self, interaction: discord.Interaction, _):
        await interaction.response.defer()
        await self.spin(interaction)

    @discord.ui.button(label="Stop 🚫", style=discord.ButtonStyle.danger)
    async def stop_game(self, interaction: discord.Interaction, _):
        self.stop()
        self.set_disabled(True)
        await interaction.response.edit_message(content=self.render() + "\n🎰 Game ended.", view=self)

    async def spin(self, interaction: discord.Interaction):
        """Run one spin. The interaction must already be responded to (or deferred)."""
        self.last_interaction = interaction
        if not try_debit(self.user_id, self.bet):
            error = f"❌ You don't have enough coins for a {self.bet} bet (balance: {get_balance(self.user_id)})."
            if self.last_result:
                await interaction.followup.send(error, ephemeral=True)
            else:
                self.stop()
                await interaction.edit_original_response(content=error, view=None)
            return

        self.spinning = True
        self.set_disabled(True)
        final_symbols = [random.choices(SLOT_SYMBOLS, weights=_WEIGHTS, k=3) for _ in range(3)]  # per column
        final_grid = [[final_symbols[col][row] for col in range(3)] for row in range(3)]

        try:
            for step in range(3):
                grid = [
                    [final_symbols[col][row] if col < step else random.choice(SLOT_SYMBOLS) for col in range(3)]
                    for row in range(3)
                ]
                await interaction.edit_original_response(
                    content=f"🎰 Spinning...\n{format_grid(grid)}\n🎲 Current Bet: **{self.bet}**", view=self
                )
                await asyncio.sleep(0.4)
        except Exception:
            # Nothing has been paid out yet, so refunding the bet is safe.
            logger.exception("Slots animation failed, refunding bet")
            credit(self.user_id, self.bet)
            self.spinning = False
            self.stop()
            return

        try:
            payout, lines = calculate_winnings(final_grid, self.bet)
            new_balance = credit(self.user_id, payout) if payout else get_balance(self.user_id)
            update_stats(self.user_id, payout, self.bet, final_grid)
        finally:
            self.spinning = False

        if payout:
            outcome = f"🎉 {lines} winning line{'s' if lines > 1 else ''}! Payout **{payout}** (+{payout - self.bet})"
        else:
            outcome = f"😢 No luck. You lost **{self.bet}**."
        self.last_result = f"🎰 Final Result!\n{format_grid(final_grid)}\n{outcome}\n💰 Balance: **{new_balance}**"

        self.set_disabled(False)
        await interaction.edit_original_response(content=self.render(), view=self)


def setup(client):
    """Setup slots command."""

    @client.tree.command(name="slots", description="Play a slot machine with a bet")
    @app_commands.describe(bet=f"Amount to bet ({MIN_BET}-{MAX_BET})")
    async def slots(interaction: discord.Interaction, bet: int):
        user_id = interaction.user.id
        is_valid, error_msg = validate_bet(bet, get_balance(user_id))
        if not is_valid:
            await interaction.response.send_message(f"❌ {error_msg}", ephemeral=True)
            return

        view = SlotView(user_id, bet)
        await interaction.response.send_message("🎰 Spinning...")
        await view.spin(interaction)
