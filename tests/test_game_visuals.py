import asyncio
import io

import discord
import pytest
from PIL import Image

import main
from bot.blackjack_card import render_table
from bot.coinflip_gif import animation_seconds, render_flip_gif
from bot.config import STARTING_BALANCE
from bot.games import blackjack, coinflip
from bot.games.blackjack import BlackjackView
from bot.slots_gif import GREEN, MUTED

from conftest import make_interaction, sent_embed


def cards(*ranks):
    return [(rank, "♠") for rank in ranks]


# ---------- coin flip GIF ----------

@pytest.mark.parametrize("outcome, guess", [("heads", "heads"), ("tails", "heads"), ("tails", "tails")])
def test_flip_gif_plays_once_with_the_right_timing(outcome, guess):
    gif = Image.open(io.BytesIO(render_flip_gif(outcome, guess, 1_000_000, seed=1)))
    assert gif.format == "GIF" and gif.is_animated and "loop" not in gif.info
    total = 0
    for number in range(gif.n_frames - 1):
        gif.seek(number)
        total += gif.info["duration"]
    assert total == pytest.approx(animation_seconds(outcome == guess) * 1000)


@pytest.fixture
def bot():
    async def build():
        client = main.BankRollBot()
        coinflip.setup(client)
        blackjack.setup(client)
        return client
    return asyncio.run(build())


@pytest.fixture
def instant(monkeypatch):
    async def no_wait(_):
        pass
    monkeypatch.setattr(coinflip.asyncio, "sleep", no_wait)


def play_flip(bot, interaction, monkeypatch, outcome):
    monkeypatch.setattr(coinflip.random, "choice", lambda options: outcome)
    guess = discord.app_commands.Choice(name="Heads", value="heads")

    async def go():
        await bot.tree.get_command("coinflip").callback(interaction, guess, 10)
    asyncio.run(go())


def test_coinflip_sends_a_gif_then_the_result(bot, db, monkeypatch, instant):
    interaction = make_interaction(1, done=False)
    titles = []  # recorded when sent: the same embed object is updated for the result
    interaction.edit_original_response.side_effect = lambda **kwargs: titles.append(kwargs["embed"].title)
    play_flip(bot, interaction, monkeypatch, "heads")
    assert db.get_balance(1) == STARTING_BALANCE + 10
    assert titles == ["🪙 Flipping...", "🎉 You won!"]
    first, last = interaction.edit_original_response.call_args_list
    assert first.kwargs["attachments"][0].filename == "flip.gif"
    assert "attachments" not in last.kwargs
    assert last.kwargs["embed"].title == "🎉 You won!" and last.kwargs["embed"].image.url == "attachment://flip.gif"


def test_coinflip_loss(bot, db, monkeypatch, instant):
    interaction = make_interaction(1, done=False)
    play_flip(bot, interaction, monkeypatch, "tails")
    assert db.get_balance(1) == STARTING_BALANCE - 10
    assert sent_embed(interaction.edit_original_response).color == discord.Color.red()


def test_coinflip_falls_back_to_text(bot, db, monkeypatch, instant):
    def broken(*args):
        raise OSError("no font")
    monkeypatch.setattr(coinflip, "render_flip_gif", broken)
    interaction = make_interaction(1, done=False)
    play_flip(bot, interaction, monkeypatch, "heads")
    assert db.get_balance(1) == STARTING_BALANCE + 10, "the game still counts"
    embed = sent_embed(interaction.edit_original_response)
    assert embed.title == "🎉 You won!" and "Heads" in embed.description and embed.image.url is None


# ---------- blackjack table ----------

def test_table_is_a_png():
    png = render_table(cards("K", "7"), cards("9", "4"), 17, None, "HIT, STAND OR DOUBLE", MUTED, True)
    image = Image.open(io.BytesIO(png))
    assert image.format == "PNG" and image.size == (640, 560)


def test_table_handles_every_suit_and_a_long_hand():
    hand = [("2", "♠"), ("3", "♥"), ("4", "♦"), ("5", "♣"), ("A", "♠"), ("A", "♥"), ("A", "♦"), ("A", "♣"), ("2", "♥"), ("10", "♦"), ("3", "♠")]
    assert render_table(hand, hand, 33, 33, "YOU WON +1,000,000,000", GREEN).startswith(b"\x89PNG")


def test_hidden_dealer_card_is_not_on_the_picture():
    hidden_ace = render_table(cards("K", "7"), [("9", "♦"), ("A", "♠")], 17, None, "x", MUTED, True)
    hidden_two = render_table(cards("K", "7"), [("9", "♦"), ("2", "♠")], 17, None, "x", MUTED, True)
    assert hidden_ace == hidden_two, "the picture can't reveal the face-down card"


def new_game(db, player, dealer, deck=None):
    assert db.try_debit(1, 10)
    view = BlackjackView(1, 10)
    view.player, view.dealer = cards(*player), cards(*dealer)
    if deck:
        view.deck = cards(*deck)
    return view


def test_blackjack_actions_send_a_table(db):
    async def go():
        view = new_game(db, ["5", "6"], ["10", "7"], deck=["2"])
        interaction = make_interaction(1)
        await view.hit.callback(interaction)
        interaction.response.defer.assert_awaited()
        call = interaction.edit_original_response.call_args
        assert call.kwargs["attachments"][0].filename == "table.png"
        assert call.kwargs["embed"].image.url == "attachment://table.png"
        assert [f.name for f in call.kwargs["embed"].fields] == ["💰 Bet"], "hands are on the picture"
        assert view.status[0] == "HIT, STAND OR DOUBLE"

        await view.stand.callback(make_interaction(1))
        assert view.status[0] == "YOU LOST 10"
    asyncio.run(go())


@pytest.mark.parametrize("player, dealer, deck, status", [
    (["10", "9"], ["10", "7"], None, "YOU WON +10"),
    (["10", "7"], ["10", "7"], None, "PUSH"),
])
def test_blackjack_final_status(db, player, dealer, deck, status):
    async def go():
        view = new_game(db, player, dealer, deck)
        await view.stand.callback(make_interaction(1))
        assert view.status[0] == status
    asyncio.run(go())


def test_blackjack_bust_status_and_natural(db):
    async def go():
        view = new_game(db, ["10", "6"], ["10", "7"], deck=["K"])
        await view.hit.callback(make_interaction(1))
        assert view.status[0] == "BUSTED -10"
        view = new_game(db, ["A", "K"], ["9", "7"])
        view.check_naturals()
        assert view.status[0] == "BLACKJACK +15"
    asyncio.run(go())


def test_blackjack_falls_back_to_text(db, monkeypatch):
    def broken(*args):
        raise OSError("no font")
    monkeypatch.setattr(blackjack, "render_table", broken)

    async def go():
        view = new_game(db, ["10", "9"], ["10", "7"])
        interaction = make_interaction(1)
        await view.stand.callback(interaction)
        call = interaction.edit_original_response.call_args
        assert call.kwargs["attachments"] == []
        assert "Your Hand" in [f.name for f in call.kwargs["embed"].fields]
    asyncio.run(go())
    assert db.get_balance(1) == STARTING_BALANCE + 10
