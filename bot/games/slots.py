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
from ..utils import validate_bet, fmt

logger = logging.getLogger(__name__)

_WEIGHTS = [SYMBOL_WEIGHTS[s] for s in SLOT_SYMBOLS]
SPIN_COLOR = discord.Color.blurple()


LINE_NAMES = ["Row 1", "Row 2", "Row 3", "Column 1", "Column 2", "Column 3", "Diagonal ↘", "Diagonal ↙"]


def find_winning_lines(grid: list) -> list[tuple[str, str, int]]:
    """All winning lines in a 3x3 grid as (line name, symbols, multiplier)."""
    lines = grid + [list(col) for col in zip(*grid)] + [[grid[i][i] for i in range(3)], [grid[i][2-i] for i in range(3)]]
    winning = []
    for name, line in zip(LINE_NAMES, lines):
        combo = "".join(line)
        if combo in SLOT_PAYOUTS:
            winning.append((name, combo, SLOT_PAYOUTS[combo]))
    return winning


def calculate_winnings(grid: list, bet: int) -> tuple[int, int]:
    """
    Calculate the payout from a slot grid.
    Every winning line (rows, columns, diagonals) pays. Returns (payout, winning_lines).
    """
    winning = find_winning_lines(grid)
    return sum(multiplier for _, _, multiplier in winning) * bet, len(winning)


def format_grid(grid: list) -> str:
    """Format a slot grid for display."""
    return "```\n" + "\n".join([" | ".join(row) for row in grid]) + "\n```"


class SlotView(discord.ui.View):
    def __init__(self, user_id: int, bet: int):
        super().__init__(timeout=GAME_TIMEOUT)
        self.user_id = user_id
        self.bet = bet
        self.spinning = False
        self.result: discord.Embed | None = None  # embed of the last finished spin
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

    def render(self, footer: str = "Spin again, change your bet or stop.") -> discord.Embed:
        """The last result with the current bet (which may have been changed since)."""
        embed = self.result.copy()
        embed.set_field_at(0, name="🎲 Next bet", value=fmt(self.bet), inline=True)
        embed.set_footer(text=footer)
        return embed

    async def on_timeout(self):
        self.set_disabled(True)
        if self.last_interaction and self.result:
            try:
                await self.last_interaction.edit_original_response(embed=self.render("⌛ Session ended."), view=self)
            except discord.HTTPException:
                pass

    async def change_bet(self, interaction: discord.Interaction, new_bet: int):
        self.bet = max(MIN_BET, min(MAX_BET, new_bet))
        self.last_interaction = interaction
        await interaction.response.edit_message(embed=self.render(), view=self)

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
        await interaction.response.edit_message(embed=self.render("🎰 Game ended. Thanks for playing!"), view=self)

    async def spin(self, interaction: discord.Interaction):
        """Run one spin. The interaction must already be responded to (or deferred)."""
        self.last_interaction = interaction
        if not try_debit(self.user_id, self.bet):
            error = f"❌ You don't have enough coins for a {fmt(self.bet)} bet (balance: {fmt(get_balance(self.user_id))})."
            if self.result:
                await interaction.followup.send(error, ephemeral=True)
            else:
                self.stop()
                await interaction.edit_original_response(content=error, embed=None, view=None)
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
                spinning = discord.Embed(title="🎰 Spinning...", description=format_grid(grid), color=SPIN_COLOR)
                spinning.set_footer(text=f"Bet: {fmt(self.bet)}")
                await interaction.edit_original_response(content=None, embed=spinning, view=self)
                await asyncio.sleep(0.4)
        except Exception:
            # Nothing has been paid out yet, so refunding the bet is safe.
            logger.exception("Slots animation failed, refunding bet")
            credit(self.user_id, self.bet)
            self.spinning = False
            self.stop()
            return

        try:
            winning_lines = find_winning_lines(final_grid)
            payout = sum(multiplier for _, _, multiplier in winning_lines) * self.bet
            new_balance = credit(self.user_id, payout) if payout else get_balance(self.user_id)
            update_stats(self.user_id, payout, self.bet, final_grid)
        finally:
            self.spinning = False

        if payout > self.bet:
            title, color = f"🎉 You won {fmt(payout - self.bet)}!", discord.Color.green()
        elif payout == self.bet:
            title, color = "🔁 Bet returned", discord.Color.gold()
        else:
            title, color = f"😢 You lost {fmt(self.bet)}", discord.Color.red()

        self.result = discord.Embed(title=title, description=format_grid(final_grid), color=color)
        self.result.add_field(name="🎲 Next bet", value=fmt(self.bet), inline=True)  # updated by render()
        self.result.add_field(name="🏆 Payout", value=fmt(payout), inline=True)
        self.result.add_field(name="💰 Balance", value=fmt(new_balance), inline=True)
        if winning_lines:
            self.result.add_field(name="✨ Winning lines", value="\n".join(
                f"{name} — {combo} **{multiplier}x**" for name, combo, multiplier in winning_lines
            ), inline=False)

        self.set_disabled(False)
        await interaction.edit_original_response(embed=self.render(), view=self)


def setup(client):
    """Setup slots command."""

    @client.tree.command(name="slots", description="Play a slot machine with a bet")
    @app_commands.describe(bet="How many coins to bet")
    async def slots(interaction: discord.Interaction, bet: app_commands.Range[int, MIN_BET, MAX_BET]):
        user_id = interaction.user.id
        is_valid, error_msg = validate_bet(bet, get_balance(user_id))
        if not is_valid:
            await interaction.response.send_message(f"❌ {error_msg}", ephemeral=True)
            return

        view = SlotView(user_id, bet)
        await interaction.response.send_message("🎰 Spinning...")
        await view.spin(interaction)
