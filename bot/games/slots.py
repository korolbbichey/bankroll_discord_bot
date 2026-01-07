"""
Slots game for the BankRoll Discord Bot.
"""

import discord
from discord import app_commands
import random
import asyncio

from ..config import SLOT_SYMBOLS, SYMBOL_WEIGHTS, SLOT_PAYOUTS, MAX_BET, GAME_TIMEOUT
from ..database import get_balance, update_balance, update_stats
from ..utils import validate_bet


def calculate_winnings(grid: list, bet: int) -> int:
    """Calculate winnings from a slot grid."""
    # Check rows, columns, and diagonals
    lines = grid + list(zip(*grid)) + [[grid[i][i] for i in range(3)], [grid[i][2-i] for i in range(3)]]
    for line in lines:
        line_str = "".join(line)
        if line_str in SLOT_PAYOUTS:
            return SLOT_PAYOUTS[line_str] * bet
    return 0


def format_grid(grid: list) -> str:
    """Format a slot grid for display."""
    return "```\n" + "\n".join([" | ".join(row) for row in grid]) + "\n```"


def setup(client):
    """Setup slots command."""

    @client.tree.command(name="slots", description="Play a slot machine with a bet")
    @app_commands.describe(bet="Amount to bet (1-10000)")
    async def slots(interaction: discord.Interaction, bet: int):
        user_id = str(interaction.user.id)
        balance = get_balance(user_id)

        is_valid, error_msg = validate_bet(bet, balance)
        if not is_valid:
            await interaction.response.send_message(f"❌ {error_msg}", ephemeral=True)
            return

        class SlotView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=GAME_TIMEOUT)
                self.message = None
                self.bet = bet
                self.keep_spinning = True
                self.active = True

            def freeze(self):
                for item in self.children:
                    item.disabled = True

            def unfreeze(self):
                for item in self.children:
                    item.disabled = False

            async def disable_view(self):
                self.active = False
                self.freeze()
                if self.message:
                    await self.message.edit(view=self)

            @discord.ui.button(label="⬆ Increase Bet", style=discord.ButtonStyle.secondary)
            async def increase_bet(self, interaction_button: discord.Interaction, button: discord.ui.Button):
                if not self.active:
                    await interaction_button.response.send_message("This game has ended.", ephemeral=True)
                    return
                if str(interaction_button.user.id) != user_id:
                    await interaction_button.response.send_message("This isn't your game!", ephemeral=True)
                    return
                if self.bet >= MAX_BET:
                    await interaction_button.response.send_message(f"Maximum bet is {MAX_BET}!", ephemeral=True)
                    return
                if self.bet + 1 <= get_balance(user_id):
                    self.bet += 1
                    await interaction_button.response.defer()
                    await self.message.edit(content=f"🎲 Bet increased to {self.bet}", view=self)
                else:
                    await interaction_button.response.send_message("Not enough balance to increase bet!", ephemeral=True)

            @discord.ui.button(label="⬇ Decrease Bet", style=discord.ButtonStyle.secondary)
            async def decrease_bet(self, interaction_button: discord.Interaction, button: discord.ui.Button):
                if not self.active:
                    await interaction_button.response.send_message("This game has ended.", ephemeral=True)
                    return
                if str(interaction_button.user.id) != user_id:
                    await interaction_button.response.send_message("This isn't your game!", ephemeral=True)
                    return
                if self.bet > 1:
                    self.bet -= 1
                    await interaction_button.response.defer()
                    await self.message.edit(content=f"🎲 Bet decreased to {self.bet}", view=self)
                else:
                    await interaction_button.response.send_message("Minimum bet is 1!", ephemeral=True)

            @discord.ui.button(label="Spin Again 🎰", style=discord.ButtonStyle.success)
            async def spin_again(self, interaction_button: discord.Interaction, button: discord.ui.Button):
                if not self.active:
                    await interaction_button.response.send_message("This game has ended.", ephemeral=True)
                    return
                if str(interaction_button.user.id) != user_id:
                    await interaction_button.response.send_message("This isn't your game!", ephemeral=True)
                    return
                await self.spin(interaction_button)

            @discord.ui.button(label="Stop 🚫", style=discord.ButtonStyle.danger)
            async def stop(self, interaction_button: discord.Interaction, button: discord.ui.Button):
                if not self.active:
                    await interaction_button.response.send_message("This game has already ended.", ephemeral=True)
                    return
                if str(interaction_button.user.id) != user_id:
                    await interaction_button.response.send_message("This isn't your game!", ephemeral=True)
                    return
                self.keep_spinning = False
                await self.disable_view()
                await interaction_button.response.edit_message(content="🎰 Game ended.", view=self)

            async def animate_vertical_spin(self):
                rows, columns = 3, 3
                lock_steps = [1, 2, 3]
                final_symbols = [
                    [random.choices(SLOT_SYMBOLS, weights=[SYMBOL_WEIGHTS[s] for s in SLOT_SYMBOLS])[0] for _ in range(rows)]
                    for _ in range(columns)
                ]

                for step in range(4):
                    grid = []
                    for row in range(rows):
                        current_row = []
                        for col in range(columns):
                            if step >= lock_steps[col]:
                                current_row.append(final_symbols[col][row])
                            else:
                                current_row.append(random.choice(SLOT_SYMBOLS))
                        grid.append(current_row)

                    content = f"🎰 Spinning...\n{format_grid(grid)}\n🎲 Current Bet: {self.bet}"
                    await self.message.edit(content=content)
                    await asyncio.sleep(0.4)

                final_grid = [[final_symbols[col][row] for col in range(columns)] for row in range(rows)]
                return final_grid

            async def spin(self, interaction_obj):
                current_balance = get_balance(user_id)
                if current_balance < self.bet:
                    await interaction_obj.followup.send("❌ You don't have enough coins to spin again!", ephemeral=True)
                    self.keep_spinning = False
                    if self.message:
                        await self.disable_view()
                    return

                update_balance(user_id, current_balance - self.bet)

                if not self.message:
                    await interaction_obj.response.defer()
                    self.message = await interaction_obj.followup.send("🎰 Spinning...")

                self.freeze()
                await self.message.edit(view=self)

                final_grid = await self.animate_vertical_spin()
                winnings = calculate_winnings(final_grid, self.bet)

                update_balance(user_id, get_balance(user_id) + winnings)
                update_stats(user_id, winnings, self.bet, final_grid)

                new_balance = get_balance(user_id)
                result_text = (
                    f"🎰 Final Result!\n{format_grid(final_grid)}\n"
                    f"You {'won' if winnings > 0 else 'lost'} {abs(winnings - self.bet)} coins!\n"
                    f"New balance: 💰 {new_balance}\n"
                    f"🎲 Current Bet: {self.bet}"
                )

                self.unfreeze()
                await self.message.edit(content=result_text, view=self)

        view = SlotView()
        await view.spin(interaction)
