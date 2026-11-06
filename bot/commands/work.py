"""
/work for the BankRoll Discord Bot: a short casino job once an hour.

Each shift is a small task with three to five answers on buttons. A right answer pays the full amount,
a wrong or late one pays a little. Players get promoted as their shifts add up, and better jobs pay more.
"""

import logging
import random
from dataclasses import dataclass

import discord

from ..config import WORK_ANSWER_SECONDS, WORK_COOLDOWN, WORK_PAY, WORK_PAY_WRONG, WORK_RANKS
from ..database import credit, start_work_shift
from ..utils import fmt

logger = logging.getLogger(__name__)


@dataclass
class Task:
    job: str          # what the shift is, shown as the title
    prompt: str       # the question
    answers: list[str]
    correct: int      # index into answers


DRINKS = {"🍸": "Martini", "🍺": "Beer", "🍷": "Wine", "🥃": "Whiskey", "🍹": "Cocktail", "🥂": "Champagne", "☕": "Coffee"}
LOOKALIKES = [("😐", "😑"), ("🙂", "🙃"), ("😀", "😃"), ("🟥", "🟧"), ("♠️", "♣️"), ("🔵", "🟣")]
SLOT_SYMBOLS = ["🍋", "🍒", "🍉", "🔔", "⭐", "💎"]
CARD_VALUES = {"2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9, "10": 10, "J": 10, "Q": 10, "K": 10}
SUITS = ["♠️", "♥️", "♦️", "♣️"]


def _near_numbers(rng: random.Random, value: int, spread: int) -> list[int]:
    """value and two different wrong numbers close to it, shuffled."""
    wrong = rng.sample([n for n in range(max(0, value - spread), value + spread + 1) if n != value], 2)
    numbers = [value] + wrong
    rng.shuffle(numbers)
    return numbers


def bartender(rng: random.Random) -> Task:
    drinks = rng.sample(list(DRINKS), 3)
    wanted = drinks[0]
    rng.shuffle(drinks)
    return Task("🍸 Bartender shift", f"A guest points at {wanted} on the menu. What do you pour?",
                [DRINKS[d] for d in drinks], drinks.index(wanted))


def cashier(rng: random.Random) -> Task:
    red, coins = rng.randint(1, 4), rng.randint(2, 9)
    total = red * 5 + coins
    chips = "🔴" * red + " " + "🪙" * coins
    numbers = _near_numbers(rng, total, 4)
    return Task("🪙 Cashier shift", f"Count the chips: {chips}\n(🔴 = 5, 🪙 = 1)",
                [str(n) for n in numbers], numbers.index(total))


def security(rng: random.Random) -> Task:
    normal, odd = rng.choice(LOOKALIKES)
    position = rng.randrange(5)
    row = " ".join(odd if i == position else normal for i in range(5))
    return Task("🕵️ Security shift", f"One player at the table is cheating. Who looks different?\n{row}",
                [str(i + 1) for i in range(5)], position)


def mechanic(rng: random.Random) -> Task:
    a, b, c = rng.sample(SLOT_SYMBOLS, 3)
    pattern = rng.choice([[a, b], [a, b, c], [a, a, b]])
    shown = (pattern * 3)[:5]
    nxt = (pattern * 3)[5]
    options = [symbol for symbol in (a, b, c) if symbol != nxt][:2] + [nxt]
    rng.shuffle(options)
    return Task("🔧 Slot mechanic shift", f"A reel is stuck. Which symbol comes next?\n{' '.join(shown)} ❓",
                options, options.index(nxt))


def dealer(rng: random.Random) -> Task:
    cards = rng.sample([(rank, suit) for rank in CARD_VALUES for suit in SUITS], rng.choice([2, 3]))
    total = sum(CARD_VALUES[rank] for rank, _ in cards)
    numbers = _near_numbers(rng, total, 3)
    hand = "  ".join(f"{rank}{suit}" for rank, suit in cards)
    return Task("🃏 Dealer shift", f"Call the blackjack hand: {hand}\nWhat's the total?",
                [str(n) for n in numbers], numbers.index(total))


TASKS = [bartender, cashier, security, mechanic, dealer]


def rank_for(shifts: int) -> tuple[str, int]:
    """(job title, bonus per shift) after this many shifts."""
    title, bonus = WORK_RANKS[0][1], WORK_RANKS[0][2]
    for needed, name, extra in WORK_RANKS:
        if shifts >= needed:
            title, bonus = name, extra
    return title, bonus


def next_rank(shifts: int) -> tuple[int, str] | None:
    """(shifts still needed, title) of the next promotion, or None at the top."""
    for needed, name, _ in WORK_RANKS:
        if shifts < needed:
            return needed - shifts, name
    return None


def wait_text(seconds: int) -> str:
    minutes = max(1, round(seconds / 60))
    return f"{minutes // 60}h {minutes % 60}m" if minutes >= 60 else f"{minutes}m"


class WorkView(discord.ui.View):
    def __init__(self, user_id: int, task: Task, shifts: int, rng: random.Random):
        super().__init__(timeout=WORK_ANSWER_SECONDS)
        self.user_id = user_id
        self.task = task
        self.shifts = shifts
        self.rng = rng
        self.done = False
        self.message_interaction: discord.Interaction | None = None
        for index, answer in enumerate(task.answers):
            button = discord.ui.Button(label=answer, style=discord.ButtonStyle.secondary)
            button.callback = self._answer(index)
            self.add_item(button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your shift!", ephemeral=True)
            return False
        return True

    def _answer(self, index: int):
        async def callback(interaction: discord.Interaction):
            await self.finish(interaction, index)
        return callback

    def pay(self, correct: bool) -> int:
        _, bonus = rank_for(self.shifts)
        return self.rng.randint(*WORK_PAY) + bonus if correct else WORK_PAY_WRONG

    def result_embed(self, correct: bool | None, earned: int, balance: int) -> discord.Embed:
        title, _ = rank_for(self.shifts)
        if correct:
            heading, color = f"✅ Great job! +{fmt(earned)} coins", discord.Color.green()
        elif correct is None:
            heading, color = f"⌛ Too slow! +{fmt(earned)} coins", discord.Color.light_grey()
        else:
            heading, color = f"❌ Not quite. +{fmt(earned)} coins", discord.Color.orange()
        embed = discord.Embed(title=heading, color=color)
        if correct is not True:
            embed.description = f"The answer was **{self.task.answers[self.task.correct]}**."
        promoted = self.shifts in {needed for needed, _, _ in WORK_RANKS[1:]}
        embed.add_field(name="💼 Job", value=f"**{title}** · shift #{self.shifts}"
                        + ("\n🎉 **Promoted!**" if promoted else ""), inline=True)
        embed.add_field(name="💰 Balance", value=fmt(balance), inline=True)
        upcoming = next_rank(self.shifts)
        footer = f"Next shift in {wait_text(WORK_COOLDOWN)}"
        if upcoming:
            footer += f" • {upcoming[0]} more to become {upcoming[1]}"
        embed.set_footer(text=footer)
        return embed

    def mark_answers(self, chosen: int | None):
        for index, item in enumerate(self.children):
            item.disabled = True
            if index == self.task.correct:
                item.style = discord.ButtonStyle.success
            elif index == chosen:
                item.style = discord.ButtonStyle.danger

    async def finish(self, interaction: discord.Interaction, chosen: int):
        if self.done:
            await interaction.response.send_message("This shift is already over.", ephemeral=True)
            return
        self.done = True
        self.stop()
        correct = chosen == self.task.correct
        earned = self.pay(correct)
        balance = credit(self.user_id, earned)
        self.mark_answers(chosen)
        await interaction.response.edit_message(embed=self.result_embed(correct, earned, balance), view=self)

    async def on_timeout(self):
        if self.done:
            return
        self.done = True
        earned = self.pay(False)
        balance = credit(self.user_id, earned)
        self.mark_answers(None)
        if self.message_interaction:
            try:
                await self.message_interaction.edit_original_response(
                    embed=self.result_embed(None, earned, balance), view=self)
            except discord.HTTPException:
                pass


def setup(client):
    """Setup the work command."""

    @client.tree.command(name="work", description="Work a quick casino shift for coins, once an hour")
    async def work(interaction: discord.Interaction):
        started, seconds_left, shifts = start_work_shift(interaction.user.id, WORK_COOLDOWN)
        if not started:
            await interaction.response.send_message(
                f"⏳ You're on a break. Your next shift starts in **{wait_text(seconds_left)}**.", ephemeral=True)
            return

        rng = random.Random()
        task = rng.choice(TASKS)(rng)
        view = WorkView(interaction.user.id, task, shifts, rng)
        title, _ = rank_for(shifts)
        embed = discord.Embed(title=task.job, description=task.prompt, color=discord.Color.blurple())
        embed.set_footer(text=f"{title} · shift #{shifts} • Answer within {WORK_ANSWER_SECONDS} seconds")
        view.message_interaction = interaction
        await interaction.response.send_message(embed=embed, view=view)
