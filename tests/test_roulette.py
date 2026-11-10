import asyncio
import io
from fractions import Fraction

import discord
import pytest
from PIL import Image

import main
from bot import progression
from bot.coinflip_gif import _coin_face
from bot.config import STARTING_BALANCE
from bot.games import roulette
from bot.games.roulette import OUTSIDE_BETS, number_bet, parse_roulette_bet, payout_for
from bot.roulette_gif import RED_NUMBERS, WHEEL_ORDER, animation_seconds, color_of, render_spin_gif
from bot.utils import InvalidBet

from conftest import make_interaction, sent_embed


# ---------- rules ----------

def test_wheel_is_a_real_european_wheel():
    assert sorted(WHEEL_ORDER) == list(range(37))
    assert len(RED_NUMBERS) == 18
    colors = [color_of(n) for n in WHEEL_ORDER[1:]]
    assert all(a != b for a, b in zip(colors, colors[1:])), "red and black alternate around the wheel"


@pytest.mark.parametrize("text, key", [
    ("red", "red"), (" Black ", "black"), ("R", "red"), ("odd", "odd"), ("1-18", "low"), ("19–36", "high"),
    ("1st 12", "dozen1"), ("2nd12", "dozen2"), ("third 12", "dozen3"), ("0", "0"), ("36", "36"), ("07", "7"),
])
def test_bets_are_understood(text, key):
    assert parse_roulette_bet(text).key == key


@pytest.mark.parametrize("text", ["37", "-1", "green", "", "4th 12", "1.5"])
def test_unknown_bets_are_rejected(text):
    with pytest.raises(InvalidBet):
        parse_roulette_bet(text)


@pytest.mark.parametrize("bet", OUTSIDE_BETS + [number_bet(n) for n in (0, 17, 36)], ids=lambda b: b.key)
def test_every_bet_returns_36_of_37(bet):
    """Real roulette payouts: only the zero gives the house its edge, about 2.7%."""
    expected = Fraction(sum(payout_for(bet, 1, n) for n in range(37)), 37)
    assert expected == Fraction(36, 37)


def test_zero_loses_outside_bets():
    assert all(payout_for(bet, 10, 0) == 0 for bet in OUTSIDE_BETS)


def test_suggestions():
    transformer = roulette.RouletteBetTransformer()
    interaction = make_interaction(1)

    def suggest(text):
        return [c.value for c in asyncio.run(transformer.autocomplete(interaction, text))]
    assert suggest("")[:2] == ["red", "black"] and "0" in suggest("")
    assert suggest("12") == ["12"] and suggest("40") == []
    assert suggest("doz") == ["dozen1", "dozen2", "dozen3"]
    assert suggest("2nd") == ["dozen2"]


# ---------- GIF ----------

@pytest.mark.parametrize("number, payout", [(5, 200), (0, 0)])
def test_spin_gif_plays_once_with_the_right_timing(number, payout):
    gif = Image.open(io.BytesIO(render_spin_gif(number, "RED", 100, payout, seed=1)))
    assert gif.format == "GIF" and gif.is_animated and "loop" not in gif.info
    total = 0
    for frame in range(gif.n_frames - 1):
        gif.seek(frame)
        total += gif.info["duration"]
    assert total == pytest.approx(animation_seconds(payout > 0) * 1000)


def test_coin_sides_have_different_pictures():
    heads, tails = _coin_face("heads"), _coin_face("tails")
    assert heads.size == tails.size and heads.tobytes() != tails.tobytes()


# ---------- command ----------

@pytest.fixture
def bot():
    async def build():
        client = main.BankRollBot()
        roulette.setup(client)
        return client
    return asyncio.run(build())


@pytest.fixture(autouse=True)
def instant(monkeypatch):
    async def no_wait(_):
        pass
    monkeypatch.setattr(roulette.asyncio, "sleep", no_wait)


def spin(bot, monkeypatch, on, bet, number, user_id=1):
    monkeypatch.setattr(roulette.random, "randrange", lambda n: number)
    interaction = make_interaction(user_id, done=False)

    async def go():
        await bot.tree.get_command("roulette").callback(interaction, parse_roulette_bet(on), bet)
    asyncio.run(go())
    return interaction


def test_win_on_red(bot, db, monkeypatch):
    interaction = spin(bot, monkeypatch, "red", 10, 5)
    assert db.get_balance(1) == STARTING_BALANCE + 10
    first = interaction.edit_original_response.call_args_list[0]
    assert first.kwargs["attachments"][0].filename == "roulette.gif"
    embed = sent_embed(interaction.edit_original_response)
    assert embed.title == "🎉 You won!" and "5 🔴 Red" in embed.description
    still = interaction.edit_original_response.call_args.kwargs["attachments"][0]
    assert still.filename == "roulette.png" and embed.image.url == "attachment://roulette.png", "no replay"
    assert db.get_game_stats(1)["roulette"] == (1, 1, 10)


def test_single_number_pays_36x_and_earns_bullseye(bot, db, monkeypatch):
    spin(bot, monkeypatch, "17", 2, 17)
    assert db.get_balance(1) == STARTING_BALANCE + 70
    assert "bullseye" in db.get_badges(1)
    assert "zero" not in db.get_badges(1)
    assert "jackpot" not in db.get_badges(1), "36x on a number is 1 in 37: Jackpot is for slots"


def test_zero_win_earns_green_zero(bot, db, monkeypatch):
    spin(bot, monkeypatch, "0", 1, 0)
    assert {"bullseye", "zero"} <= db.get_badges(1)


def test_loss_on_zero(bot, db, monkeypatch):
    interaction = spin(bot, monkeypatch, "black", 10, 0)
    assert db.get_balance(1) == STARTING_BALANCE - 10
    embed = sent_embed(interaction.edit_original_response)
    assert embed.color == discord.Color.red() and "0 🟢 Green" in embed.description


def test_bet_must_be_affordable(bot, db, monkeypatch):
    interaction = spin(bot, monkeypatch, "red", 500, 5)
    assert interaction.response.send_message.call_args.kwargs["ephemeral"] is True
    assert db.get_balance(1) == STARTING_BALANCE


def test_failed_animation_still_pays(bot, db, monkeypatch):
    def broken(*args):
        raise OSError("no font")
    monkeypatch.setattr(roulette, "render_spin_gif", broken)
    interaction = spin(bot, monkeypatch, "even", 10, 2)
    assert db.get_balance(1) == STARTING_BALANCE + 10
    assert sent_embed(interaction.edit_original_response).image.url is None


# ---------- new badges ----------

def test_duel_badges(db):
    for number in range(5):
        progress = progression.record_game(1, "duel", 10, 20)
        if number == 0:
            assert [b.id for b in progress.new_badges] == ["first_win", "duelist"]
    assert {"duelist", "duel_5"} <= db.get_badges(1)


def test_grand_tour_needs_every_game(db):
    for game in ("slots", "coinflip", "blackjack", "roulette"):
        progression.record_game(1, game, 10, 0)
    assert "grand_tour" not in db.get_badges(1)
    progression.record_game(1, "duel", 10, 0)
    assert "grand_tour" in db.get_badges(1)


def test_veteran_after_500_games(db, monkeypatch):
    monkeypatch.setattr(progression, "VETERAN_GAMES", 3)
    progression.record_game(1, "slots", 10, 0)
    progression.record_game(1, "roulette", 10, 0)
    assert "veteran" not in db.get_badges(1)
    progression.record_game(1, "coinflip", 10, 0)
    assert "veteran" in db.get_badges(1)


def test_jackpot_needs_25x(db):
    progression.record_game(1, "slots", 10, 240)
    assert "jackpot" not in db.get_badges(1)
    progression.record_game(1, "slots", 10, 250)
    assert "jackpot" in db.get_badges(1)


@pytest.mark.parametrize("streak, expected", [(2, set()), (3, {"streak_3"}), (7, {"streak_3", "week_streak"}),
                                              (30, {"streak_3", "week_streak", "month_streak"})])
def test_streak_badges_from_daily_reward(db, monkeypatch, streak, expected):
    from dataclasses import replace
    economy = main.economy
    real_claim = db.claim_daily_reward
    monkeypatch.setattr(economy, "claim_daily_reward", lambda user_id: replace(real_claim(user_id), streak=streak))

    async def go():
        client = main.BankRollBot()
        economy.setup(client)
        await client.tree.get_command("daily_reward").callback(make_interaction(1, done=False))
    asyncio.run(go())
    assert expected <= db.get_badges(1)
    assert ("month_streak" in db.get_badges(1)) == (streak >= 30)
    assert ("streak_3" in db.get_badges(1)) == (streak >= 3)
