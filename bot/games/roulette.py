"""
Roulette game for the BankRoll Discord Bot: a European wheel with one zero.

Payouts are the real ones, so the house edge is the zero alone (return ~97.3%):
red/black, odd/even and 1-18/19-36 pay 2x, a dozen pays 3x and a single number pays 36x (the total returned).
"""

import asyncio
import io
import logging
import random
from dataclasses import dataclass

import discord
from discord import app_commands

from ..config import RESULT_DELAY_MARGIN
from ..database import credit, get_balance, try_debit, update_stats
from ..progression import send_notice, track_game
from ..roulette_gif import RED_NUMBERS, animation_seconds, color_of, render_spin_gif
from ..utils import Bet, DRAW_SLOTS, InvalidBet, confirm_big_bet, fmt, validate_bet

logger = logging.getLogger(__name__)

GIF_NAME = "roulette.gif"
COLOR_EMOJI = {"red": "🔴", "black": "⚫", "green": "🟢"}


@dataclass(frozen=True)
class RouletteBet:
    key: str             # what the option sends: 'red', 'dozen2', '17', ...
    name: str            # shown to the player
    numbers: frozenset   # winning numbers
    multiplier: int      # total returned for each coin bet

    @property
    def label(self) -> str:
        """Short upper-case name for the GIF."""
        return self.name.upper()


OUTSIDE_BETS = [
    RouletteBet("red", "Red", frozenset(RED_NUMBERS), 2),
    RouletteBet("black", "Black", frozenset(set(range(1, 37)) - RED_NUMBERS), 2),
    RouletteBet("odd", "Odd", frozenset(range(1, 37, 2)), 2),
    RouletteBet("even", "Even", frozenset(range(2, 37, 2)), 2),
    RouletteBet("low", "1-18", frozenset(range(1, 19)), 2),
    RouletteBet("high", "19-36", frozenset(range(19, 37)), 2),
    RouletteBet("dozen1", "1st 12", frozenset(range(1, 13)), 3),
    RouletteBet("dozen2", "2nd 12", frozenset(range(13, 25)), 3),
    RouletteBet("dozen3", "3rd 12", frozenset(range(25, 37)), 3),
]
OUTSIDE_BY_KEY = {bet.key: bet for bet in OUTSIDE_BETS}
# Other ways players are likely to type the same bets
ALIASES = {
    "r": "red", "b": "black", "1-18": "low", "1–18": "low", "19-36": "high", "19–36": "high",
    "1st12": "dozen1", "first12": "dozen1", "1stdozen": "dozen1",
    "2nd12": "dozen2", "second12": "dozen2", "2nddozen": "dozen2",
    "3rd12": "dozen3", "third12": "dozen3", "3rddozen": "dozen3",
}


def number_bet(number: int) -> RouletteBet:
    return RouletteBet(str(number), f"Number {number}", frozenset({number}), 36)


def parse_roulette_bet(text: str) -> RouletteBet:
    """Turn the 'on' option into a bet: an outside bet name or a number from 0 to 36."""
    value = text.strip().lower()
    compact = value.replace(" ", "")
    key = ALIASES.get(value) or ALIASES.get(compact) or compact
    if key in OUTSIDE_BY_KEY:
        return OUTSIDE_BY_KEY[key]
    if key.isdigit() and 0 <= int(key) <= 36:
        return number_bet(int(key))
    raise InvalidBet("❌ Bet on `red`, `black`, `odd`, `even`, `1-18`, `19-36`, a dozen (`1st 12`...) or a number from 0 to 36.")


def describe(bet: RouletteBet) -> str:
    return f"{bet.name} — pays {bet.multiplier}x"


class RouletteBetTransformer(app_commands.Transformer):
    """The `on` option: an outside bet or a single number, with suggestions as you type."""

    @property
    def type(self) -> discord.AppCommandOptionType:
        return discord.AppCommandOptionType.string

    async def transform(self, interaction: discord.Interaction, value: str) -> RouletteBet:
        return parse_roulette_bet(value)

    async def autocomplete(self, interaction: discord.Interaction, value: str) -> list[app_commands.Choice[str]]:
        typed = value.strip().lower()
        if typed.isdigit():
            if 0 <= int(typed) <= 36:
                return [app_commands.Choice(name=describe(number_bet(int(typed))), value=str(int(typed)))]
            return []
        matches = [bet for bet in OUTSIDE_BETS if typed in bet.name.lower() or bet.key.startswith(typed)]
        choices = [app_commands.Choice(name=describe(bet), value=bet.key) for bet in matches]
        if not typed:
            # A suggestion can't leave the option empty, so the hint is a real bet: zero.
            choices.append(app_commands.Choice(name="0 (or type any number up to 36) — pays 36x", value="0"))
        return choices


RouletteOn = app_commands.Transform[RouletteBet, RouletteBetTransformer]


def payout_for(bet: RouletteBet, amount: int, number: int) -> int:
    return amount * bet.multiplier if number in bet.numbers else 0


async def start_roulette(interaction: discord.Interaction, choice: RouletteBet, bet: int):
    """Start a game from a command or a button."""
    user_id = interaction.user.id

    is_valid, error_msg = validate_bet(bet, get_balance(user_id))
    if not is_valid or not try_debit(user_id, bet):
        await interaction.response.send_message(f"❌ {error_msg or 'You do not have enough balance for that bet.'}", ephemeral=True)
        return

    # The bet is already taken, so decide and pay out before any Discord calls that could fail.
    number = random.randrange(37)
    payout = payout_for(choice, bet, number)
    win = payout > 0
    new_balance = credit(user_id, payout) if win else get_balance(user_id)
    update_stats(user_id, payout, bet)
    progress = track_game(user_id, "roulette", bet, payout,
                          bullseye=win and len(choice.numbers) == 1, zero_win=win and number == 0)

    # Drawing and uploading can take longer than Discord's 3 seconds.
    await interaction.response.defer(thinking=True)

    footer = f"You bet on: {choice.name} • Bet: {fmt(bet)}"
    embed = discord.Embed(title="🎡 Spinning...", color=discord.Color.blurple())
    embed.set_footer(text=footer)
    try:
        async with DRAW_SLOTS:
            gif = await asyncio.to_thread(render_spin_gif, number, choice.label, bet, payout)
        embed.set_image(url=f"attachment://{GIF_NAME}")
        await interaction.edit_original_response(
            embed=embed, attachments=[discord.File(io.BytesIO(gif), filename=GIF_NAME)]
        )
        await asyncio.sleep(animation_seconds(win) + RESULT_DELAY_MARGIN)
    except Exception:
        # The game is already settled, so the player just gets the result without the animation.
        logger.exception("Roulette animation failed, sending the result as text")
        embed = discord.Embed()
        embed.set_footer(text=footer)

    color = color_of(number)
    embed.title = "🎉 You won!" if win else "😢 You lost"
    embed.description = (
        f"The ball landed on **{number} {COLOR_EMOJI[color]} {color.capitalize()}**\n"
        + (f"You win **{fmt(payout - bet)}** coins" if win else f"You lost **{fmt(bet)}** coins")
        + f" • 💰 Balance: **{fmt(new_balance)}**"
    )
    embed.color = discord.Color.green() if win else discord.Color.red()
    await interaction.edit_original_response(embed=embed)
    await send_notice(interaction, progress)


def setup(client):
    """Setup roulette command."""

    @client.tree.command(name="roulette", description="Spin the roulette wheel: bet on a color, a dozen or a number")
    @app_commands.describe(
        on="red, black, odd, even, 1-18, 19-36, a dozen or a number 0-36",
        bet="Coins to bet: a number, all or half",
    )
    async def roulette(interaction: discord.Interaction, on: RouletteOn, bet: Bet):
        if not await confirm_big_bet(interaction, bet, lambda i: start_roulette(i, on, bet)):
            await start_roulette(interaction, on, bet)
