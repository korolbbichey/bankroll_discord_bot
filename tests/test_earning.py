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
    assert rank_for(1) == ("Trainee", 1.0)
    assert rank_for(10)[0] == "Dealer" and rank_for(75)[0] == "Casino Manager"
    assert rank_for(120)[0] == "Casino Director" and rank_for(200)[0] == "Casino Owner"
    assert rank_for(300) == ("Tycoon", 2.7) and rank_for(5000)[0] == "Tycoon"
    assert next_rank(1) == (9, "Dealer", 1.2) and next_rank(78) == (42, "Casino Director", 2.0)
    assert next_rank(300) is None
    multipliers = [multiplier for _, _, multiplier in work.WORK_RANKS]
    assert multipliers == sorted(multipliers) and len(set(multipliers)) == len(multipliers), "every promotion pays more"


def test_rank_multiplies_the_pay_and_shows_the_bonus(db):
    task = work.Task("job", "?", ["a", "b", "c"], 0)

    async def go(shifts):
        view = WorkView(1, task, shifts, random.Random(5))
        press = make_interaction(1, done=False)
        await view.finish(press, 0)
        return sent_embed(press.response.edit_message)
    base = random.Random(5).randint(*WORK_PAY)
    trainee = asyncio.run(go(1))
    assert trainee.title == f"✅ Great job! +{base} coins" and trainee.description is None, "no bonus to show"
    manager = asyncio.run(go(80))
    earned = round(base * 1.7)
    assert manager.title == f"✅ Great job! +{earned} coins"
    assert manager.description == f"💵 {base} pay + **{earned - base}** Casino Manager bonus (×1.7)"
    assert "40 more to become Casino Director (×2 pay)" in manager.footer.text


@pytest.mark.rewards
def test_top_rank_earns_tycoon_once(db):
    task = work.Task("job", "?", ["a", "b", "c"], 0)

    async def go(shifts, pick):
        view = WorkView(1, task, shifts, random.Random(1))
        press = make_interaction(1, done=False)
        await view.finish(press, pick)
        return press.followup.send
    assert asyncio.run(go(299, 0)).await_count == 0 and "tycoon" not in db.get_badges(1)
    told = asyncio.run(go(300, 1))  # even a wrong answer on the shift that reaches the rank
    assert "Tycoon" in told.call_args.args[0] and "tycoon" in db.get_badges(1)
    assert asyncio.run(go(301, 0)).await_count == 0, "only once"


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


# ---------- one-time pay for badges collected before rewards ----------

def old_database_with_badges(tmp_path):
    import sqlite3
    path = tmp_path / "before_rewards.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE currency (user_id INTEGER PRIMARY KEY, balance INTEGER DEFAULT 100, last_claim_date TEXT);
        INSERT INTO currency (user_id, balance) VALUES (1, 100), (2, 20000), (3, 50);
        CREATE TABLE badges (user_id INTEGER NOT NULL, badge TEXT NOT NULL, earned_at TEXT NOT NULL,
                             PRIMARY KEY (user_id, badge));
        INSERT INTO badges VALUES
            (1, 'first_win', '2026-10-30'), (1, 'spins_100', '2026-11-02'),
            (2, 'rich', '2026-10-31'), (2, 'podium', '2026-11-01'), (2, 'first_win', '2026-10-30'),
            (3, 'first_win', '2026-11-06'), (3, 'duelist', '2026-11-06');
    """)
    conn.close()
    return path


def test_old_badges_are_paid_once(db, tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_FILE", str(old_database_with_badges(tmp_path)))
    db.init_db()
    db.init_db()  # only the first start pays
    assert db.get_balance(1) == 100 + BADGE_REWARDS["common"] + BADGE_REWARDS["rare"]
    assert db.get_balance(2) == 20000 + BADGE_REWARDS["epic"] + BADGE_REWARDS["legendary"] + BADGE_REWARDS["common"]
    assert db.get_balance(3) == 50, "badges from the day rewards started were already paid by the game"
    assert db.get_bot_stats()["events"][0][3:] == ("badges", 2050, "3 old badges")


def test_players_are_told_once(db, tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_FILE", str(old_database_with_badges(tmp_path)))
    db.init_db()

    async def go():
        client = main.BankRollBot()
        sends = []
        for user_id in (1, 1, 3):
            interaction = make_interaction(user_id)
            await client.maybe_tell_backpay(interaction)
            sends.append(interaction.followup.send)
        return sends
    first, second, other = asyncio.run(go())
    assert "+200 coins" in first.call_args.args[0] and "2 badges" in first.call_args.args[0]
    assert first.call_args.kwargs["ephemeral"] is True
    assert second.await_count == 0 and other.await_count == 0


# ---------- badge rebalance ----------

def test_rewards_follow_the_odds():
    from bot.config import badge_coins
    assert badge_coins("full_house") == 10_000
    assert [badge_coins(b) for b in ("zero", "bullseye", "duel_5", "duelist")] == [150, 150, 150, 50]
    assert [badge_coins(b) for b in ("max_bet", "week_streak", "streak_3", "jackpot")] == [500, 500, 150, 500]


def raised_rewards_start(db, badges):
    """A start without the badge_topup table yet, with these (user, badge) pairs already earned."""
    import sqlite3
    conn = sqlite3.connect(db.DB_FILE)
    conn.execute("DROP TABLE badge_topup")
    conn.executemany("INSERT INTO badges (user_id, badge, earned_at) VALUES (?, ?, '2026-11-08')", badges)
    conn.commit()
    conn.close()
    db.init_db()


def test_holders_get_the_difference_once(db):
    raised_rewards_start(db, [(1, "max_bet"), (1, "week_streak"), (1, "zero"), (2, "full_house"), (3, "duel_5")])
    assert db.get_balance(1) == STARTING_BALANCE + 350 + 350, "Big Spender and On Fire went up by 350"
    assert db.get_balance(2) == STARTING_BALANCE + 8_500, "Full House went up from 1,500"
    assert db.get_balance(3) == STARTING_BALANCE, "rewards that went down aren't taken back"
    db.init_db()
    assert db.get_balance(1) == STARTING_BALANCE + 700, "only once"


def test_holders_are_told_about_the_difference_once(db):
    raised_rewards_start(db, [(1, "max_bet")])

    async def go():
        client = main.BankRollBot()
        sends = []
        for user_id in (1, 1, 2):
            interaction = make_interaction(user_id)
            await client.maybe_tell_topup(interaction)
            sends.append(interaction.followup.send)
        return sends
    first, second, other = asyncio.run(go())
    assert "+350 coins" in first.call_args.args[0] and first.call_args.kwargs["ephemeral"] is True
    assert second.await_count == 0 and other.await_count == 0


def test_three_day_streak_badge(db):
    progress = progression.record_badges(1, ["streak_3"])
    assert [b.id for b in progress.new_badges] == ["streak_3"]


# ---------- XP given back for the old daily XP limit ----------

def database_from_the_xp_limit_days(db):
    """Players and days as the daily XP limit left them, then a start without the xp_comeback table yet."""
    import sqlite3
    conn = sqlite3.connect(db.DB_FILE)
    conn.executescript("""
        DROP TABLE xp_comeback;
        INSERT INTO players (user_id, xp, first_played) VALUES (1, 4000, '2026-11-01'), (2, 900, '2026-11-01');
        -- player 1 wins 1 game in 4
        INSERT INTO game_stats (user_id, game, games, wins, net) VALUES (1, 'slots', 1000, 250, 0), (2, 'slots', 90, 0, 0);
        INSERT INTO player_days (day, user_id, games, xp) VALUES
            ('2026-11-07', 1, 400, 1500),   -- hit the limit: 400 games = 4,000 XP + 100 wins x 5
            ('2026-11-08', 1, 100, 1100),   -- under the limit: nothing missed
            ('2026-11-09', 1, 200, 1500),   -- hit it again: 2,000 + 50 x 5
            ('2026-11-06', 2, 90, 0);       -- before the limit (no XP recorded yet), never under it
    """)
    conn.commit()
    conn.close()
    db.init_db()


def test_xp_missed_under_the_old_limit_is_given_back_once(db):
    database_from_the_xp_limit_days(db)
    missed = (4000 + 500 - 1500) + (2000 + 250 - 1500)
    assert db.get_player_progress(1)[0] == 4000 + missed
    assert db.get_player_progress(2)[0] == 900, "only days that hit the limit count"
    db.init_db()
    assert db.get_player_progress(1)[0] == 4000 + missed, "only the first start gives it"


@pytest.mark.rewards
def test_xp_given_back_pays_no_coins(db):
    db.set_balance(1, 500)
    database_from_the_xp_limit_days(db)
    assert db.get_balance(1) == 500, "levels from it don't pay level-up rewards"


def test_players_are_told_about_their_xp_once(db):
    database_from_the_xp_limit_days(db)

    async def go():
        client = main.BankRollBot()
        sends = []
        for user_id in (1, 1, 2):
            interaction = make_interaction(user_id)
            await client.maybe_tell_xp_comeback(interaction)
            sends.append(interaction.followup.send)
        return sends
    first, second, other = asyncio.run(go())
    assert "+3,750 XP" in first.call_args.args[0] and first.call_args.kwargs["ephemeral"] is True
    assert second.await_count == 0 and other.await_count == 0
