import asyncio
import io

import discord
import pytest
from PIL import Image

import main
from bot.config import AUTOPLAY_BUTTON_SPINS, SLOT_SYMBOLS, STARTING_BALANCE
from bot.games import slots
from bot.games.slots import SlotView
from bot.slots_gif import animation_seconds, render_result_png

from conftest import make_interaction, sent_embed

LEMON, CHERRY, MELON, BELL, STAR, DIAMOND = SLOT_SYMBOLS
LOSS = [[LEMON, CHERRY, BELL], [STAR, MELON, DIAMOND], [CHERRY, BELL, LEMON]]  # columns, no line
SMALL_WIN = [[CHERRY, LEMON, BELL], [CHERRY, STAR, MELON], [CHERRY, DIAMOND, LEMON]]  # one cherry row: 2x
BIG_WIN = [[BELL, LEMON, CHERRY], [BELL, STAR, MELON], [BELL, DIAMOND, LEMON]]  # one bell row: 10x


@pytest.fixture(autouse=True)
def instant(monkeypatch):
    async def no_wait(_):
        pass
    monkeypatch.setattr(slots.asyncio, "sleep", no_wait)


def force_spins(monkeypatch, *spins):
    """Each spin is 3 columns; the next spins land on these, in order."""
    queue = [column for spin in spins for column in spin]
    monkeypatch.setattr(slots.random, "choices", lambda *a, **k: queue.pop(0))


def autoplay(monkeypatch, spins, *outcomes, stop_loss=None, bet=10):
    force_spins(monkeypatch, *outcomes)

    async def go():
        view = SlotView(1, bet)
        interaction = make_interaction(1)
        await view.autoplay(interaction, spins, stop_loss)
        return view, interaction
    return asyncio.run(go())


def test_plays_every_spin_and_sums_up(db, monkeypatch):
    view, interaction = autoplay(monkeypatch, 3, LOSS, SMALL_WIN, LOSS)
    assert db.get_balance(1) == STARTING_BALANCE - 10
    calls = interaction.edit_original_response.call_args_list
    assert [c.kwargs["embed"].title for c in calls[:3]] == [f"🔁 Autoplay — spin {n}/3" for n in (1, 2, 3)]
    assert calls[0].kwargs["attachments"][0].filename == "autoplay.png"
    summary = sent_embed(interaction.edit_original_response)
    assert summary.title == "🔁 Autoplay over: all 3 spins played"
    assert {f.name: f.value for f in summary.fields} == {
        "🎲 Next bet": "10", "📈 Net": "-10", "💰 Balance": "90", "🔢 Spins": "3", "🏆 Best win": "+10"}
    assert summary.color == discord.Color.red()
    assert not view.autoplaying and not any(item.disabled for item in view.children)
    games, wins, losses, *_ = db.get_user_profile(1)["stats"]
    assert (games, wins, losses) == (3, 1, 2)


def test_stops_at_the_stop_loss(db, monkeypatch):
    _, interaction = autoplay(monkeypatch, 10, LOSS, LOSS, LOSS, stop_loss=25)
    assert db.get_balance(1) == STARTING_BALANCE - 30
    assert sent_embed(interaction.edit_original_response).title == "🔁 Autoplay over: stop-loss reached"


def test_pauses_on_a_big_win(db, monkeypatch):
    _, interaction = autoplay(monkeypatch, 10, LOSS, BIG_WIN)
    assert db.get_balance(1) == STARTING_BALANCE - 20 + 100
    assert sent_embed(interaction.edit_original_response).title == "🔁 Autoplay over: big win, +90!"


def test_stops_when_coins_run_out(db, monkeypatch):
    db.set_balance(1, 25)
    _, interaction = autoplay(monkeypatch, 10, LOSS, LOSS)
    assert db.get_balance(1) == 5
    summary = sent_embed(interaction.edit_original_response)
    assert summary.title == "🔁 Autoplay over: not enough coins for the next spin"


def test_without_coins_nothing_is_played(db, monkeypatch):
    db.set_balance(1, 5)
    view, interaction = autoplay(monkeypatch, 10)
    assert db.get_balance(1) == 5
    assert "enough coins" in interaction.edit_original_response.call_args.kwargs["content"]
    assert view.is_finished()


def test_stop_button_works_during_autoplay(db, monkeypatch):
    force_spins(monkeypatch, LOSS, LOSS, LOSS, LOSS)

    async def go():
        view = SlotView(1, 10)
        interaction = make_interaction(1)
        stop = make_interaction(1)
        stop.data = {"custom_id": view.stop_game.custom_id}
        spin = make_interaction(1)
        spin.data = {"custom_id": view.spin_again.custom_id}

        async def press_stop_after_first_spin(**kwargs):
            if kwargs.get("embed") and kwargs["embed"].title.endswith("1/4"):
                assert await view.interaction_check(stop), "Stop is allowed during autoplay"
                assert not await view.interaction_check(spin), "other buttons wait"
                assert not view.stop_game.disabled and view.spin_again.disabled
                await view.stop_game.callback(stop)
        interaction.edit_original_response.side_effect = press_stop_after_first_spin
        await view.autoplay(interaction, 4)
        assert not view.is_finished(), "stopping autoplay keeps the game open"
        return interaction
    interaction = asyncio.run(go())
    assert db.get_balance(1) == STARTING_BALANCE - 10
    assert sent_embed(interaction.edit_original_response).title == "🔁 Autoplay over: stopped"


def test_auto_button_plays_ten(db, monkeypatch):
    force_spins(monkeypatch, *[LOSS] * AUTOPLAY_BUTTON_SPINS)

    async def go():
        view = SlotView(1, 1)
        interaction = make_interaction(1, done=False)
        await view.auto_spin.callback(interaction)
        return interaction
    interaction = asyncio.run(go())
    assert db.get_balance(1) == STARTING_BALANCE - AUTOPLAY_BUTTON_SPINS
    assert sent_embed(interaction.edit_original_response).fields[3].value == str(AUTOPLAY_BUTTON_SPINS)


def test_failed_picture_still_plays(db, monkeypatch):
    def broken(*args):
        raise OSError("no font")
    monkeypatch.setattr(slots, "render_result_png", broken)
    _, interaction = autoplay(monkeypatch, 2, SMALL_WIN, LOSS)
    first = interaction.edit_original_response.call_args_list[0]
    assert first.kwargs["attachments"] == [] and CHERRY in first.kwargs["embed"].description
    assert db.get_balance(1) == STARTING_BALANCE


def test_slots_command_starts_autoplay(db, monkeypatch):
    force_spins(monkeypatch, LOSS, LOSS)

    async def go():
        client = main.BankRollBot()
        slots.setup(client)
        interaction = make_interaction(1, done=False)
        await client.tree.get_command("slots").callback(interaction, 10, 2, None)
        return interaction
    interaction = asyncio.run(go())
    assert interaction.response.send_message.call_args.args[0] == "🔁 Starting autoplay..."
    assert db.get_balance(1) == STARTING_BALANCE - 20


def test_still_picture_is_a_small_png():
    grid = [[BELL] * 3, [LEMON, CHERRY, MELON], [STAR, DIAMOND, LEMON]]
    png = render_result_png(grid, {(0, 0), (0, 1), (0, 2)}, 10, 100)
    image = Image.open(io.BytesIO(png))
    assert image.format == "PNG" and len(png) < 150_000


def test_spin_animation_is_faster():
    assert animation_seconds(False) <= 1.1
