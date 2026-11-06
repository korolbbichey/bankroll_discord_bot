"""
Slots game for the BankRoll Discord Bot.

A spin is shown as an animated GIF. Autoplay plays several spins in a row with still pictures instead,
stopping early on a big win, at the player's stop-loss, when the coins run out or when they press Stop.
"""

import discord
from discord import app_commands
import random
import asyncio
import io
import logging

from ..config import (
    SLOT_SYMBOLS, SYMBOL_WEIGHTS, SLOT_PAYOUTS, MIN_BET, MAX_BET, GAME_TIMEOUT, SLOTS_RESULT_DELAY_MARGIN,
    AUTOPLAY_MAX_SPINS, AUTOPLAY_BUTTON_SPINS, AUTOPLAY_DELAY, AUTOPLAY_STOP_MULTIPLIER,
)
from ..database import get_balance, try_debit, credit, update_stats
from ..utils import validate_bet, fmt, Bet, DRAW_SLOTS, confirm_big_bet
from ..progression import Progress, track_game, send_notice
from ..slots_gif import animation_seconds, render_result_png, render_spin_gif

logger = logging.getLogger(__name__)

_WEIGHTS = [SYMBOL_WEIGHTS[s] for s in SLOT_SYMBOLS]
SPIN_COLOR = discord.Color.blurple()
GIF_NAME = "spin.gif"
STILL_NAME = "autoplay.png"


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


def roll_grid() -> list[list[str]]:
    """A random 3x3 grid; each reel (column) is drawn separately."""
    columns = [random.choices(SLOT_SYMBOLS, weights=_WEIGHTS, k=3) for _ in range(3)]
    return [[columns[col][row] for col in range(3)] for row in range(3)]


def signed(amount: int) -> str:
    return f"+{fmt(amount)}" if amount > 0 else fmt(amount)


def merge_progress(items: list[Progress | None]) -> Progress | None:
    """Several games' progress as one notice: the level change over all of them and every new badge."""
    items = [item for item in items if item]
    if not items:
        return None
    return Progress(items[0].level_before, items[-1].level_after, [b for item in items for b in item.new_badges],
                    sum(item.coins for item in items))


def line_cells(name: str) -> list[tuple[int, int]]:
    """The (row, column) cells of a named winning line."""
    index = LINE_NAMES.index(name)
    if index < 3:
        return [(index, col) for col in range(3)]
    if index < 6:
        return [(row, index - 3) for row in range(3)]
    return [(i, i if index == 6 else 2 - i) for i in range(3)]


class SlotView(discord.ui.View):
    def __init__(self, user_id: int, bet: int):
        super().__init__(timeout=GAME_TIMEOUT)
        self.user_id = user_id
        self.bet = bet
        self.spinning = False
        self.autoplaying = False
        self.stop_requested = False
        self.result: discord.Embed | None = None  # embed of the last finished spin
        self.last_interaction: discord.Interaction | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your game!", ephemeral=True)
            return False
        if self.autoplaying and (interaction.data or {}).get("custom_id") == self.stop_game.custom_id:
            return True
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

    @discord.ui.button(label=f"Auto ×{AUTOPLAY_BUTTON_SPINS} 🔁", style=discord.ButtonStyle.primary)
    async def auto_spin(self, interaction: discord.Interaction, _):
        await interaction.response.defer()
        await self.autoplay(interaction, AUTOPLAY_BUTTON_SPINS)

    @discord.ui.button(label="Stop 🚫", style=discord.ButtonStyle.danger)
    async def stop_game(self, interaction: discord.Interaction, _):
        if self.autoplaying:
            self.stop_requested = True
            await interaction.response.send_message("⏹️ Autoplay stops after this spin.", ephemeral=True)
            return
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
        final_grid = roll_grid()
        winning_lines = find_winning_lines(final_grid)
        payout = sum(multiplier for _, _, multiplier in winning_lines) * self.bet

        try:
            cells = {cell for name, _, _ in winning_lines for cell in line_cells(name)}
            async with DRAW_SLOTS:
                gif = await asyncio.to_thread(render_spin_gif, final_grid, cells, self.bet, payout)
            spinning = discord.Embed(title="🎰 Spinning...", color=SPIN_COLOR)
            spinning.set_image(url=f"attachment://{GIF_NAME}")
            spinning.set_footer(text=f"Bet: {fmt(self.bet)}")
            await interaction.edit_original_response(
                content=None, embed=spinning, view=self,
                attachments=[discord.File(io.BytesIO(gif), filename=GIF_NAME)],
            )
        except Exception:
            # Nothing has been paid out yet, so refunding the bet is safe.
            logger.exception("Slots spin failed, refunding bet")
            credit(self.user_id, self.bet)
            self.spinning = False
            self.stop()
            try:
                await interaction.followup.send("❌ Something went wrong. Your bet was refunded.", ephemeral=True)
            except discord.HTTPException:
                pass
            return

        # The player can already see the spin, so pay out now and show the numbers when the reels have stopped.
        try:
            new_balance = credit(self.user_id, payout) if payout else get_balance(self.user_id)
            update_stats(self.user_id, payout, self.bet, final_grid)
        except Exception:
            self.spinning = False
            raise
        progress = track_game(self.user_id, "slots", self.bet, payout,
                              winning_combos=[combo for _, combo, _ in winning_lines])
        await asyncio.sleep(animation_seconds(bool(winning_lines)) + SLOTS_RESULT_DELAY_MARGIN)
        self.spinning = False

        if payout > self.bet:
            title, color = f"🎉 You won {fmt(payout - self.bet)}!", discord.Color.green()
        elif payout == self.bet:
            title, color = "🔁 Bet returned", discord.Color.gold()
        else:
            title, color = f"😢 You lost {fmt(self.bet)}", discord.Color.red()

        self.result = discord.Embed(title=title, color=color)
        self.result.set_image(url=f"attachment://{GIF_NAME}")  # the GIF already in the message
        self.result.add_field(name="🎲 Next bet", value=fmt(self.bet), inline=True)  # updated by render()
        self.result.add_field(name="🏆 Payout", value=fmt(payout), inline=True)
        self.result.add_field(name="💰 Balance", value=fmt(new_balance), inline=True)
        if winning_lines:
            self.result.add_field(name="✨ Winning lines", value="\n".join(
                f"{name} — {combo} **{multiplier}x**" for name, combo, multiplier in winning_lines
            ), inline=False)

        self.set_disabled(False)
        await interaction.edit_original_response(embed=self.render(), view=self)
        await send_notice(interaction, progress)

    async def draw_still(self, grid: list, winning_lines: list, payout: int) -> bytes | None:
        """The spin's final picture, or None if it can't be drawn (the spin is already paid, so autoplay goes on)."""
        try:
            cells = {cell for name, _, _ in winning_lines for cell in line_cells(name)}
            async with DRAW_SLOTS:
                return await asyncio.to_thread(render_result_png, grid, cells, self.bet, payout)
        except Exception:
            logger.exception("Failed to draw an autoplay spin")
            return None

    async def autoplay(self, interaction: discord.Interaction, spins: int, stop_loss: int | None = None):
        """Play up to `spins` spins in a row. The interaction must already be responded to (or deferred)."""
        self.last_interaction = interaction
        self.autoplaying = self.spinning = True
        self.stop_requested = False
        self.set_disabled(True)
        self.stop_game.disabled = False  # the one button that works during autoplay
        played = net = best = 0
        progress = []
        reason = f"all {spins} spins played"
        try:
            for number in range(1, spins + 1):
                if self.stop_requested:
                    reason = "stopped"
                    break
                if not try_debit(self.user_id, self.bet):
                    reason = "not enough coins for the next spin"
                    break
                grid = roll_grid()
                winning_lines = find_winning_lines(grid)
                payout = sum(multiplier for _, _, multiplier in winning_lines) * self.bet
                balance = credit(self.user_id, payout) if payout else get_balance(self.user_id)
                update_stats(self.user_id, payout, self.bet, grid)
                progress.append(track_game(self.user_id, "slots", self.bet, payout,
                                           winning_combos=[combo for _, combo, _ in winning_lines]))
                played += 1
                net += payout - self.bet
                best = max(best, payout - self.bet)
                self.timeout = GAME_TIMEOUT  # keeps the Stop button alive however long autoplay runs

                embed = discord.Embed(title=f"🔁 Autoplay — spin {number}/{spins}", color=SPIN_COLOR)
                embed.add_field(name="📈 Net", value=signed(net), inline=True)
                embed.add_field(name="💰 Balance", value=fmt(balance), inline=True)
                embed.add_field(name="🎲 Bet", value=fmt(self.bet), inline=True)
                embed.set_footer(text="Press Stop to end autoplay"
                                      + (f" • Stop-loss: {fmt(stop_loss)}" if stop_loss else ""))
                picture = await self.draw_still(grid, winning_lines, payout)
                if picture:
                    embed.set_image(url=f"attachment://{STILL_NAME}")
                    files = [discord.File(io.BytesIO(picture), filename=STILL_NAME)]
                else:
                    embed.description = "\n".join(" ".join(row) for row in grid)
                    files = []
                try:
                    await interaction.edit_original_response(content=None, embed=embed, view=self, attachments=files)
                except discord.HTTPException:
                    logger.exception("Failed to show an autoplay spin")

                if payout >= self.bet * AUTOPLAY_STOP_MULTIPLIER:
                    reason = f"big win, +{fmt(payout - self.bet)}!"
                    break
                if stop_loss and -net >= stop_loss:
                    reason = "stop-loss reached"
                    break
                if number < spins:
                    await asyncio.sleep(AUTOPLAY_DELAY)
        finally:
            self.autoplaying = self.spinning = False

        if not played:
            error = f"❌ You don't have enough coins for a {fmt(self.bet)} bet (balance: {fmt(get_balance(self.user_id))})."
            if self.result:
                self.set_disabled(False)
                await interaction.edit_original_response(embed=self.render(), view=self)
                await interaction.followup.send(error, ephemeral=True)
            else:
                self.stop()
                await interaction.edit_original_response(content=error, embed=None, view=None)
            return

        color = discord.Color.green() if net > 0 else discord.Color.red() if net < 0 else discord.Color.gold()
        self.result = discord.Embed(title=f"🔁 Autoplay over: {reason}", color=color)
        self.result.add_field(name="🎲 Next bet", value=fmt(self.bet), inline=True)  # updated by render()
        self.result.add_field(name="📈 Net", value=signed(net), inline=True)
        self.result.add_field(name="💰 Balance", value=fmt(get_balance(self.user_id)), inline=True)
        self.result.add_field(name="🔢 Spins", value=fmt(played), inline=True)
        self.result.add_field(name="🏆 Best win", value=signed(best) if best > 0 else "—", inline=True)
        self.result.set_image(url=f"attachment://{STILL_NAME}")  # the last spin's picture, already in the message
        self.set_disabled(False)
        await interaction.edit_original_response(embed=self.render(), view=self)
        await send_notice(interaction, merge_progress(progress))


async def start_slots(interaction: discord.Interaction, bet: int, spins: int | None = None,
                      stop_loss: int | None = None):
    """Start a game from a command or a button. With spins or a stop-loss it starts with autoplay."""
    user_id = interaction.user.id
    is_valid, error_msg = validate_bet(bet, get_balance(user_id))
    if not is_valid:
        await interaction.response.send_message(f"❌ {error_msg}", ephemeral=True)
        return

    view = SlotView(user_id, bet)
    if spins or stop_loss:
        await interaction.response.send_message("🔁 Starting autoplay...")
        await view.autoplay(interaction, spins or AUTOPLAY_MAX_SPINS, stop_loss)
        return
    await interaction.response.send_message("🎰 Spinning...")
    await view.spin(interaction)


def setup(client):
    """Setup slots command."""

    @client.tree.command(name="slots", description="Play a slot machine with a bet, or autoplay several spins")
    @app_commands.describe(
        bet="Coins to bet: a number, all or half",
        spins=f"Autoplay: how many spins in a row (2-{AUTOPLAY_MAX_SPINS})",
        stop_loss="Autoplay: stop once you've lost this many coins",
    )
    async def slots(interaction: discord.Interaction, bet: Bet,
                    spins: app_commands.Range[int, 2, AUTOPLAY_MAX_SPINS] = None,
                    stop_loss: app_commands.Range[int, 1, 1_000_000_000] = None):
        if not await confirm_big_bet(interaction, bet, lambda i: start_slots(i, bet, spins, stop_loss)):
            await start_slots(interaction, bet, spins, stop_loss)
