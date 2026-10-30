import asyncio
import io
import random

import discord
import pytest
from PIL import Image

from bot.config import SLOT_SYMBOLS, SYMBOL_WEIGHTS, SLOT_PAYOUTS, STARTING_BALANCE, MIN_BET, MAX_BET
from bot.games import slots
from bot.games.slots import calculate_winnings, find_winning_lines, line_cells, SlotView
from bot.slots_gif import animation_seconds, render_spin_gif

from conftest import make_interaction, sent_embed

LEMON, CHERRY, MELON, BELL, STAR, DIAMOND = SLOT_SYMBOLS


@pytest.fixture(autouse=True)
def no_animation_delay(monkeypatch):
    async def instant(_):
        pass
    monkeypatch.setattr(slots.asyncio, "sleep", instant)


def force_columns(monkeypatch, columns):
    """Make the next spin land on the given columns (each a list of 3 symbols, top to bottom)."""
    queue = list(columns)
    monkeypatch.setattr(slots.random, "choices", lambda *a, **k: queue.pop(0))


def test_weights_sum_to_one():
    assert sum(SYMBOL_WEIGHTS.values()) == pytest.approx(1.0)


def test_expected_return_is_below_100_percent():
    """Every line pays, so the expected return is exactly 8 * sum(p^3 * multiplier)."""
    rtp = 8 * sum(SYMBOL_WEIGHTS[combo[0]] ** 3 * mult for combo, mult in SLOT_PAYOUTS.items())
    assert 0.90 < rtp < 1.0


def test_simulated_return_matches_math():
    rng = random.Random(1)
    weights = [SYMBOL_WEIGHTS[s] for s in SLOT_SYMBOLS]
    spins = 50_000
    total = sum(
        calculate_winnings([rng.choices(SLOT_SYMBOLS, weights=weights, k=3) for _ in range(3)], 1)[0]
        for _ in range(spins)
    )
    assert 0.90 < total / spins < 1.0


def test_calculate_winnings_sums_every_line():
    grid = [[CHERRY] * 3, [CHERRY] * 3, [CHERRY] * 3]  # 3 rows + 3 columns + 2 diagonals
    assert calculate_winnings(grid, 10) == (8 * 2 * 10, 8)
    assert calculate_winnings([[LEMON, CHERRY, MELON], [BELL, STAR, DIAMOND], [CHERRY, LEMON, BELL]], 10) == (0, 0)
    assert calculate_winnings([[DIAMOND] * 3, [LEMON, CHERRY, MELON], [BELL, STAR, LEMON]], 2) == (100, 1)


def test_find_winning_lines_names_each_line():
    """The grid from a player report: five cherries, but only the middle row is a full line."""
    grid = [[LEMON, LEMON, BELL], [CHERRY, CHERRY, CHERRY], [CHERRY, CHERRY, MELON]]
    assert find_winning_lines(grid) == [("Row 2", CHERRY * 3, 2)]
    assert calculate_winnings(grid, 50) == (100, 1)

    grid = [[STAR, LEMON, STAR], [CHERRY, STAR, MELON], [STAR, BELL, STAR]]
    assert [name for name, _, _ in find_winning_lines(grid)] == ["Diagonal ↘", "Diagonal ↙"]

    grid = [[BELL, LEMON, CHERRY], [BELL, MELON, STAR], [BELL, DIAMOND, LEMON]]
    assert find_winning_lines(grid) == [("Column 1", BELL * 3, 10)]


def run_spin(monkeypatch, columns, bet=10, user_id=1):
    async def go():
        force_columns(monkeypatch, columns)
        view = SlotView(user_id, bet)
        interaction = make_interaction(user_id)
        await view.spin(interaction)
        return view, interaction
    return asyncio.run(go())


def test_winning_spin_pays_and_shows_green_embed(db, monkeypatch):
    view, interaction = run_spin(monkeypatch, [[DIAMOND, LEMON, BELL], [DIAMOND, CHERRY, STAR], [DIAMOND, MELON, LEMON]])
    assert db.get_balance(1) == STARTING_BALANCE - 10 + 500
    embed = sent_embed(interaction.edit_original_response)
    assert embed.color == discord.Color.green() and "490" in embed.title
    assert [f.value for f in embed.fields] == ["10", "500", "590", f"Row 1 — {DIAMOND * 3} **50x**"]
    assert embed.fields[3].name == "✨ Winning lines"
    assert not view.spinning and not any(item.disabled for item in view.children)


def test_lemon_line_returns_bet(db, monkeypatch):
    _, interaction = run_spin(monkeypatch, [[LEMON, CHERRY, BELL], [LEMON, STAR, MELON], [LEMON, DIAMOND, CHERRY]])
    assert db.get_balance(1) == STARTING_BALANCE
    embed = sent_embed(interaction.edit_original_response)
    assert embed.color == discord.Color.gold() and embed.title == "🔁 Bet returned"
    games, wins, losses, *_ = db.get_user_profile(1)["stats"]
    assert (games, wins, losses) == (1, 0, 0)


def test_losing_spin(db, monkeypatch):
    _, interaction = run_spin(monkeypatch, [[LEMON, CHERRY, BELL], [STAR, MELON, DIAMOND], [CHERRY, BELL, LEMON]])
    assert db.get_balance(1) == STARTING_BALANCE - 10
    embed = sent_embed(interaction.edit_original_response)
    assert embed.color == discord.Color.red()
    assert len(embed.fields) == 3, "no 'Winning lines' field without a win"


def test_spin_without_enough_coins_takes_nothing(db, monkeypatch):
    db.set_balance(1, 5)
    view, interaction = run_spin(monkeypatch, [], bet=10)
    assert db.get_balance(1) == 5
    assert "enough coins" in interaction.edit_original_response.call_args.kwargs["content"]
    assert view.is_finished()


def test_failed_animation_refunds_bet(db, monkeypatch):
    async def go():
        force_columns(monkeypatch, [[LEMON] * 3] * 3)
        view = SlotView(1, 10)
        interaction = make_interaction(1)
        interaction.edit_original_response.side_effect = discord.HTTPException(response=type("R", (), {"status": 500, "reason": "x"})(), message="boom")
        await view.spin(interaction)
    asyncio.run(go())
    assert db.get_balance(1) == STARTING_BALANCE


def test_bet_buttons_clamp_to_limits(monkeypatch):
    async def go():
        force_columns(monkeypatch, [[LEMON, CHERRY, BELL], [STAR, MELON, DIAMOND], [CHERRY, BELL, LEMON]])
        view = SlotView(1, MIN_BET)
        await view.spin(make_interaction(1))
        await view.halve_bet.callback(make_interaction(1))
        assert view.bet == MIN_BET
        view.bet = MAX_BET
        interaction = make_interaction(1)
        await view.double_bet.callback(interaction)
        assert view.bet == MAX_BET
        assert sent_embed(interaction.response.edit_message).fields[0].value == f"{MAX_BET:,}"
    asyncio.run(go())


def test_only_owner_can_press_buttons_and_not_mid_spin():
    async def go():
        view = SlotView(1, 10)
        stranger = make_interaction(2)
        assert not await view.interaction_check(stranger)
        stranger.response.send_message.assert_awaited()
        view.spinning = True
        assert not await view.interaction_check(make_interaction(1))
        view.spinning = False
        assert await view.interaction_check(make_interaction(1))
    asyncio.run(go())


def test_line_cells():
    assert line_cells("Row 2") == [(1, 0), (1, 1), (1, 2)]
    assert line_cells("Column 3") == [(0, 2), (1, 2), (2, 2)]
    assert line_cells("Diagonal ↘") == [(0, 0), (1, 1), (2, 2)]
    assert line_cells("Diagonal ↙") == [(0, 2), (1, 1), (2, 0)]


def test_spin_sends_a_gif_then_the_result(db, monkeypatch):
    view, interaction = run_spin(monkeypatch, [[DIAMOND, LEMON, BELL], [DIAMOND, CHERRY, STAR], [DIAMOND, MELON, LEMON]])
    first, last = interaction.edit_original_response.call_args_list
    file = first.kwargs["attachments"][0]
    assert file.filename == "spin.gif" and file.fp.read(6) == b"GIF89a"
    assert first.kwargs["embed"].title == "🎰 Spinning..."
    assert first.kwargs["embed"].image.url == "attachment://spin.gif"
    assert all(item.disabled for item in view.children) is False, "buttons are back after the spin"
    assert "attachments" not in last.kwargs, "the result keeps the same GIF"
    assert last.kwargs["embed"].image.url == "attachment://spin.gif"


def test_gif_plays_once_and_lands_on_the_grid():
    grid = [[DIAMOND] * 3, [LEMON, CHERRY, MELON], [BELL, STAR, LEMON]]
    gif = Image.open(io.BytesIO(render_spin_gif(grid, {(0, 0), (0, 1), (0, 2)}, 10, 500, seed=1)))
    assert gif.format == "GIF" and gif.is_animated and "loop" not in gif.info
    total = 0
    for number in range(gif.n_frames - 1):
        gif.seek(number)
        total += gif.info["duration"]
    assert total == pytest.approx(animation_seconds(True) * 1000)


def test_gif_shows_the_same_symbols_when_the_reels_stop():
    """The last spinning frame has to match the final grid: no jump between animation and result."""
    grid = [[LEMON, CHERRY, BELL], [STAR, MELON, DIAMOND], [CHERRY, BELL, LEMON]]
    gif = Image.open(io.BytesIO(render_spin_gif(grid, set(), 10, 0, seed=1)))
    window = (60, 24, 360, 324)
    gif.seek(gif.n_frames - 2)  # identical frames get merged, so count from the end
    spinning = gif.convert("RGB").crop(window)
    gif.seek(gif.n_frames - 1)
    assert spinning.tobytes() == gif.convert("RGB").crop(window).tobytes()


@pytest.mark.parametrize("payout, bet", [(0, 10), (10, 10), (10 ** 12, 10 ** 11)])
def test_gif_draws_every_outcome(payout, bet):
    assert render_spin_gif([[LEMON] * 3] * 3, set(), bet, payout, seed=1).startswith(b"GIF89a")
