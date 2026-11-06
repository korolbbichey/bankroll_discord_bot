import asyncio

import discord
import pytest

import main
from bot.config import AUTOPLAY_BUTTON_SPINS, SLOT_SYMBOLS, STARTING_BALANCE
from bot.games import slots
from bot.games.slots import SlotView
from bot.slots_gif import animation_seconds

from conftest import make_interaction, sent_embed

LEMON, CHERRY, MELON, BELL, STAR, DIAMOND = SLOT_SYMBOLS
LOSS = [[LEMON, CHERRY, BELL], [STAR, MELON, DIAMOND], [CHERRY, BELL, LEMON]]  # columns, no line
SMALL_WIN = [[CHERRY, LEMON, BELL], [CHERRY, STAR, MELON], [CHERRY, DIAMOND, LEMON]]  # one cherry row: 2x
BIG_WIN = [[BELL, LEMON, CHERRY], [BELL, STAR, MELON], [BELL, DIAMOND, LEMON]]  # one bell row: 10x


@pytest.fixture(autouse=True)
def waits(monkeypatch):
    """No real waiting; the waits are recorded instead."""
    recorded = []

    async def no_wait(seconds):
        recorded.append(seconds)
    monkeypatch.setattr(slots.asyncio, "sleep", no_wait)
    return recorded


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


def fields(embed):
    return {f.name: f.value for f in embed.fields}


def test_every_spin_is_animated_and_then_shows_its_result(db, monkeypatch, waits):
    view, interaction = autoplay(monkeypatch, 3, LOSS, SMALL_WIN, LOSS)
    calls = interaction.edit_original_response.call_args_list
    spinning, landed = calls[2].kwargs, calls[3].kwargs  # the second spin
    assert spinning["attachments"][0].filename == "spin.gif" and spinning["attachments"][0].fp.read(6) == b"GIF89a"
    assert spinning["embed"].title == "🔁 Autoplay — spin 2/3 🎰"
    assert fields(spinning["embed"])["📈 Net"] == "-10", "the result isn't shown before the reels stop"
    assert "attachments" not in landed, "the result keeps the same GIF"
    assert landed["embed"].title == "🔁 Autoplay — spin 2/3" and fields(landed["embed"])["📈 Net"] == "0"
    assert landed["embed"].image.url == "attachment://spin.gif"
    assert animation_seconds(True) + slots.SLOTS_RESULT_DELAY_MARGIN in waits, "waits for the animation"


def test_plays_every_spin_and_sums_up(db, monkeypatch):
    view, interaction = autoplay(monkeypatch, 3, LOSS, SMALL_WIN, LOSS)
    assert db.get_balance(1) == STARTING_BALANCE - 10
    summary = sent_embed(interaction.edit_original_response)
    assert summary.title == "🔁 Autoplay over: all 3 spins played"
    assert fields(summary) == {
        "🎲 Next bet": "10", "📈 Net": "-10", "💰 Balance": "90", "🔢 Spins": "3", "🏆 Best win": "+10"}
    assert summary.color == discord.Color.red() and summary.image.url == "attachment://spin.gif"
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

        async def press_stop_during_first_spin(**kwargs):
            if kwargs.get("embed") and kwargs["embed"].title == "🔁 Autoplay — spin 1/4 🎰":
                assert await view.interaction_check(stop), "Stop is allowed during autoplay"
                assert not await view.interaction_check(spin), "other buttons wait"
                assert not view.stop_game.disabled and view.spin_again.disabled
                await view.stop_game.callback(stop)
        interaction.edit_original_response.side_effect = press_stop_during_first_spin
        await view.autoplay(interaction, 4)
        assert not view.is_finished(), "stopping autoplay keeps the game open"
        return interaction
    interaction = asyncio.run(go())
    assert db.get_balance(1) == STARTING_BALANCE - 10, "the spin already started is finished"
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
    assert fields(sent_embed(interaction.edit_original_response))["🔢 Spins"] == str(AUTOPLAY_BUTTON_SPINS)


def test_failed_animation_still_plays(db, monkeypatch, waits):
    def broken(*args):
        raise OSError("no font")
    monkeypatch.setattr(slots, "render_spin_gif", broken)
    _, interaction = autoplay(monkeypatch, 2, SMALL_WIN, LOSS)
    first = interaction.edit_original_response.call_args_list[0]
    assert first.kwargs["attachments"] == [] and CHERRY in first.kwargs["embed"].description
    assert db.get_balance(1) == STARTING_BALANCE
    assert all(seconds < 1 for seconds in waits), "no waiting for an animation that isn't there"


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


def test_each_spin_shows_a_log_of_recent_spins(db, monkeypatch):
    _, interaction = autoplay(monkeypatch, 3, LOSS, SMALL_WIN, LOSS)
    third = interaction.edit_original_response.call_args_list[5].kwargs["embed"]
    assert fields(third)["🧾 Last spins"].splitlines() == ["`#3` **-10**", f"`#2` {CHERRY * 3} **+10**", "`#1` **-10**"]
    first_spinning = interaction.edit_original_response.call_args_list[0].kwargs["embed"]
    assert fields(first_spinning)["🧾 Last spins"] == "—"


def test_log_keeps_the_last_five(db, monkeypatch):
    _, interaction = autoplay(monkeypatch, 7, *[LOSS] * 7)
    last = interaction.edit_original_response.call_args_list[13].kwargs["embed"]
    log = fields(last)["🧾 Last spins"].splitlines()
    assert len(log) == 5 and log[0].startswith("`#7`") and log[-1].startswith("`#3`")


def test_several_autoplays_can_run_at_once(db, monkeypatch):
    force_spins(monkeypatch, *[LOSS] * 4)

    async def go():
        first, second = SlotView(1, 10), SlotView(1, 10)
        a, b = make_interaction(1), make_interaction(1)
        await asyncio.gather(first.autoplay(a, 2), second.autoplay(b, 2))
        return a, b
    a, b = asyncio.run(go())
    assert db.get_balance(1) == STARTING_BALANCE - 40, "both autoplays played"
    for interaction in (a, b):
        assert sent_embed(interaction.edit_original_response).title == "🔁 Autoplay over: all 2 spins played"


def test_autoplays_per_player_are_limited(db, monkeypatch):
    limit = slots.AUTOPLAY_MAX_PER_PLAYER

    async def go():
        finish = asyncio.Event()
        running = []

        async def long_autoplay(view, interaction, spins, stop_loss=None):
            running.append(view)
            await finish.wait()
        monkeypatch.setattr(SlotView, "autoplay", long_autoplay)
        client = main.BankRollBot()
        slots.setup(client)
        command = client.tree.get_command("slots").callback

        runs = [asyncio.create_task(command(make_interaction(1, done=False), 10, 2, None)) for _ in range(limit)]
        while len(running) < limit:
            await asyncio.wait(runs, timeout=0.01)
        rejected, button = make_interaction(1, done=False), make_interaction(1, done=False)
        await command(rejected, 10, 2, None)
        await SlotView(1, 10).auto_spin.callback(button)
        other_player = make_interaction(2, done=False)
        runs.append(asyncio.create_task(command(other_player, 10, 2, None)))
        while len(running) < limit + 1:
            await asyncio.wait(runs, timeout=0.01)
        finish.set()
        await asyncio.gather(*runs)
        assert not slots.running_autoplays, "finished autoplays are released"
        return rejected, button
    for interaction in asyncio.run(go()):
        call = interaction.response.send_message.call_args
        assert call.args[0] == slots.TOO_MANY_AUTOPLAYS and call.kwargs["ephemeral"]


def test_autoplay_slot_is_released_after_an_error(db, monkeypatch):
    async def broken(*args, **kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr(SlotView, "autoplay", broken)

    async def go():
        with pytest.raises(RuntimeError):
            await SlotView(1, 10).auto_spin.callback(make_interaction(1, done=False))
    asyncio.run(go())
    assert not slots.running_autoplays


def test_merged_notice_claims_only_its_own_level_ups():
    from bot.progression import Progress
    assert slots.merge_progress([Progress(13, 13), Progress(14, 14)]).leveled_up is False, \
        "a level reached by another game window isn't announced here"
    merged = slots.merge_progress([Progress(12, 12), Progress(12, 13, coins=325), Progress(14, 14)])
    assert (merged.level_before, merged.level_after, merged.coins) == (12, 13, 325)


def test_spin_animation_is_fast():
    assert animation_seconds(False) <= 1.1
