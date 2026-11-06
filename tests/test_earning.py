import asyncio
import random
from datetime import datetime, timedelta, timezone

import discord
import pytest

import main
from bot import progression
from bot.commands import work
from bot.commands.work import TASKS, WorkView, next_rank, rank_for
from bot.config import (
    BADGE_RARITY, BADGE_REWARDS, LEVEL_UP_REWARD, STARTING_BALANCE, WORK_COOLDOWN, WORK_PAY, WORK_PAY_WRONG,
)
from bot.games import coinflip
from bot.progression import BADGES
from bot.utils import ConfirmBetView

from conftest import make_interaction, sent_embed

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


# ---------- rewards for badges and levels ----------

def test_every_badge_has_a_reward():
    assert {badge.id for badge in BADGES} == set(BADGE_RARITY)
    assert set(BADGE_RARITY.values()) == set(BADGE_REWARDS)


@pytest.mark.rewards
def test_reward_math():
    assert progression.reward_for(1, 1, []) == 0
    assert progression.reward_for(1, 3, []) == (2 + 3) * LEVEL_UP_REWARD
    assert progression.reward_for(1, 1, ["first_win", "jackpot"]) == BADGE_REWARDS["common"] + BADGE_REWARDS["epic"]


@pytest.mark.rewards
def test_first_win_pays_its_reward_once(db):
    db.set_balance(1, 100)
    progress = progression.record_game(1, "coinflip", 10, 20)
    assert progress.coins == BADGE_REWARDS["common"]
    assert db.get_balance(1) == 100 + BADGE_REWARDS["common"]
    assert "+50 coins" in progress.notice()
    assert progression.record_game(1, "coinflip", 10, 20).coins == 0, "a badge pays only once"


@pytest.mark.rewards
def test_level_up_pays(db):
    db.set_balance(1, 0)
    for _ in range(7):  # 7 losses = 70 XP, still level 1
        progression.record_game(1, "slots", 10, 0)
    progress = progression.record_game(1, "slots", 10, 0)  # 80 XP
    assert not progress.leveled_up and db.get_balance(1) == 0
    progression.record_game(1, "slots", 10, 0)
    progress = progression.record_game(1, "slots", 10, 0)  # 100 XP: level 2
    assert progress.leveled_up and progress.coins == 2 * LEVEL_UP_REWARD
    assert db.get_balance(1) == 2 * LEVEL_UP_REWARD


# ---------- /work ----------

def test_work_cooldown(db):
    assert db.start_work_shift(1, WORK_COOLDOWN, now=NOW) == (True, WORK_COOLDOWN, 1)
    started, left, shifts = db.start_work_shift(1, WORK_COOLDOWN, now=NOW + timedelta(minutes=20))
    assert not started and left == 40 * 60 and shifts == 1
    assert db.start_work_shift(1, WORK_COOLDOWN, now=NOW + timedelta(hours=1))[0]
    assert db.start_work_shift(1, WORK_COOLDOWN, now=NOW + timedelta(hours=2))[2] == 3


@pytest.mark.parametrize("make", TASKS, ids=lambda f: f.__name__)
def test_every_task_has_one_right_answer(make):
    for seed in range(200):
        task = make(random.Random(seed))
        assert 3 <= len(task.answers) <= 5
        assert len(set(task.answers)) == len(task.answers), "answers are all different"
        assert 0 <= task.correct < len(task.answers)
        assert all(len(answer) <= 80 for answer in task.answers), "fits on a button"


def test_tasks_are_right():
    rng = random.Random(3)
    task = work.cashier(rng)
    chips = task.prompt.split(": ")[1].split("\n")[0]
    assert int(task.answers[task.correct]) == chips.count("🔴") * 5 + chips.count("🪙")


def test_ranks():
    assert rank_for(1) == ("Trainee", 0)
    assert rank_for(10)[0] == "Dealer" and rank_for(500)[0] == "Casino Manager"
    assert next_rank(1) == (9, "Dealer") and next_rank(75) is None


def run_work(monkeypatch, pick):
    """Start a shift with a known task and press answer `pick` ('right', 'wrong' or None for a timeout)."""
    task = work.Task("🃏 Dealer shift", "?", ["16", "17", "18"], 1)
    monkeypatch.setattr(work.random.Random, "choice", lambda self, seq: (lambda rng: task) if seq is TASKS else seq[0])

    async def go():
        client = main.BankRollBot()
        work.setup(client)
        interaction = make_interaction(1, done=False)
        await client.tree.get_command("work").callback(interaction)
        view = interaction.response.send_message.call_args.kwargs["view"]
        if pick is None:
            await view.on_timeout()
            return view, sent_embed(interaction.edit_original_response)
        press = make_interaction(1, done=False)
        await view.children[1 if pick == "right" else 0].callback(press)
        return view, sent_embed(press.response.edit_message)
    return asyncio.run(go())


def test_right_answer_pays_full(db, monkeypatch):
    view, embed = run_work(monkeypatch, "right")
    earned = db.get_balance(1) - STARTING_BALANCE
    assert WORK_PAY[0] <= earned <= WORK_PAY[1]
    assert embed.title.startswith("✅") and "shift #1" in embed.fields[0].value
    assert view.children[1].style == discord.ButtonStyle.success


def test_wrong_answer_pays_a_little(db, monkeypatch):
    view, embed = run_work(monkeypatch, "wrong")
    assert db.get_balance(1) == STARTING_BALANCE + WORK_PAY_WRONG
    assert "The answer was **17**" in embed.description
    assert view.children[0].style == discord.ButtonStyle.danger


def test_timeout_pays_a_little(db, monkeypatch):
    _, embed = run_work(monkeypatch, None)
    assert db.get_balance(1) == STARTING_BALANCE + WORK_PAY_WRONG
    assert embed.title.startswith("⌛")


def test_work_is_once_an_hour(db, monkeypatch):
    run_work(monkeypatch, "right")
    balance = db.get_balance(1)

    async def go():
        client = main.BankRollBot()
        work.setup(client)
        interaction = make_interaction(1, done=False)
        await client.tree.get_command("work").callback(interaction)
        return interaction.response.send_message.call_args
    call = asyncio.run(go())
    assert "next shift" in call.args[0] and call.kwargs["ephemeral"] is True
    assert db.get_balance(1) == balance


def test_answering_twice_pays_once(db):
    async def go():
        task = work.Task("job", "?", ["a", "b", "c"], 0)
        view = WorkView(1, task, 1, random.Random(1))
        await view.finish(make_interaction(1, done=False), 0)
        second = make_interaction(1, done=False)
        await view.finish(second, 0)
        assert "already over" in second.response.send_message.call_args.args[0]
    asyncio.run(go())
    assert db.get_balance(1) <= STARTING_BALANCE + WORK_PAY[1]


# ---------- confirmation for big bets ----------

@pytest.fixture
def flip_bot(monkeypatch):
    async def no_wait(_):
        pass
    monkeypatch.setattr(coinflip.asyncio, "sleep", no_wait)
    monkeypatch.setattr(coinflip.random, "choice", lambda options: "tails")

    async def build():
        client = main.BankRollBot()
        coinflip.setup(client)
        return client
    return asyncio.run(build())


def flip(bot, bet):
    guess = discord.app_commands.Choice(name="Heads", value="heads")

    async def go():
        interaction = make_interaction(1, done=False)
        await bot.tree.get_command("coinflip").callback(interaction, guess, bet)
        return interaction
    return asyncio.run(go())


def test_small_bets_go_straight_through(db, flip_bot):
    flip(flip_bot, 50)
    assert db.get_balance(1) == STARTING_BALANCE - 50


def test_big_bet_asks_first_and_takes_nothing(db, flip_bot):
    interaction = flip(flip_bot, STARTING_BALANCE)
    call = interaction.response.send_message.call_args
    assert "**all** of your coins" in call.args[0] and call.kwargs["ephemeral"] is True
    assert isinstance(call.kwargs["view"], ConfirmBetView)
    assert db.get_balance(1) == STARTING_BALANCE


@pytest.mark.parametrize("button, asks_again", [("confirm", True), ("confirm_always", False)])
def test_confirming_plays_the_bet(db, flip_bot, button, asks_again):
    view = flip(flip_bot, 80).response.send_message.call_args.kwargs["view"]

    async def press():
        interaction = make_interaction(1, done=False)
        assert await view.interaction_check(interaction)
        await getattr(view, button).callback(interaction)
        assert not await view.interaction_check(make_interaction(1, done=False)), "only one answer"
    asyncio.run(press())
    assert db.get_balance(1) == STARTING_BALANCE - 80
    db.set_balance(1, 100)
    call = flip(flip_bot, 80).response.send_message.call_args  # None when the game started right away
    assert (call is not None and isinstance(call.kwargs.get("view"), ConfirmBetView)) == asks_again


def test_cancel(db, flip_bot):
    view = flip(flip_bot, 80).response.send_message.call_args.kwargs["view"]

    async def press():
        interaction = make_interaction(1, done=False)
        await view.cancel.callback(interaction)
        return interaction
    interaction = asyncio.run(press())
    assert "cancelled" in interaction.response.edit_message.call_args.kwargs["content"]
    assert db.get_balance(1) == STARTING_BALANCE


def test_low_balances_are_not_asked(db, flip_bot):
    db.set_balance(1, 40)
    flip(flip_bot, 40)
    assert db.get_balance(1) == 0
