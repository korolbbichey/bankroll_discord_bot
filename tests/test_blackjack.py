import asyncio
import random

from bot.config import STARTING_BALANCE
from bot.games.blackjack import BlackjackView, hand_value, is_natural

from conftest import make_interaction


def cards(*ranks):
    return [(rank, "♠") for rank in ranks]


def test_hand_value_counts_aces_as_1_or_11():
    assert hand_value(cards("A", "K")) == 21
    assert hand_value(cards("A", "A")) == 12
    assert hand_value(cards("A", "A", "9")) == 21
    assert hand_value(cards("K", "Q", "A")) == 21
    assert hand_value(cards("K", "Q", "5")) == 25


def test_is_natural():
    assert is_natural(cards("A", "10"))
    assert not is_natural(cards("7", "7", "7"))


def new_game(db, user_id, bet, player, dealer, deck=None):
    """Start a game like /blackjack does: the bet is taken first."""
    assert db.try_debit(user_id, bet)
    view = BlackjackView(user_id, bet)
    view.player, view.dealer = cards(*player), cards(*dealer)
    if deck is not None:
        view.deck = cards(*deck)
    return view


def test_player_natural_pays_3_to_2(db):
    async def go():
        view = new_game(db, 1, 10, ["A", "K"], ["9", "7"])
        assert view.check_naturals() is not None
        assert view.settled
    asyncio.run(go())
    assert db.get_balance(1) == STARTING_BALANCE + 15


def test_dealer_natural_wins_immediately(db):
    async def go():
        view = new_game(db, 1, 10, ["10", "9"], ["A", "K"])
        assert view.check_naturals() is not None
    asyncio.run(go())
    assert db.get_balance(1) == STARTING_BALANCE - 10


def test_stand_win_and_push(db):
    async def go():
        view = new_game(db, 1, 10, ["10", "9"], ["10", "7"])
        await view.stand.callback(make_interaction(1))
        view = new_game(db, 2, 10, ["10", "7"], ["10", "7"])
        await view.stand.callback(make_interaction(2))
    asyncio.run(go())
    assert db.get_balance(1) == STARTING_BALANCE + 10
    assert db.get_balance(2) == STARTING_BALANCE
    assert db.get_user_profile(2)["blackjack"] == (0, 0, 0, 0), "a push is neither a win nor a loss"


def test_bust_loses_bet(db):
    async def go():
        view = new_game(db, 1, 10, ["10", "6"], ["10", "7"], deck=["K"])
        await view.hit.callback(make_interaction(1))
        assert view.settled
    asyncio.run(go())
    assert db.get_balance(1) == STARTING_BALANCE - 10


def test_double_down_doubles_the_stake(db):
    async def go():
        view = new_game(db, 1, 10, ["5", "6"], ["10", "7"], deck=["9"])
        await view.double.callback(make_interaction(1))
        assert view.bet == 20 and view.settled
    asyncio.run(go())
    assert db.get_balance(1) == STARTING_BALANCE + 20


def test_double_down_needs_coins(db):
    db.set_balance(1, 10)
    async def go():
        view = new_game(db, 1, 10, ["5", "6"], ["10", "7"], deck=["9"])
        interaction = make_interaction(1)
        await view.double.callback(interaction)
        assert view.bet == 10 and not view.settled
        interaction.response.send_message.assert_awaited()
    asyncio.run(go())


def test_timeout_stands_automatically(db):
    async def go():
        view = new_game(db, 1, 10, ["10", "9"], ["10", "7"])
        view.last_interaction = make_interaction(1)
        await view.on_timeout()
        assert view.settled
    asyncio.run(go())
    assert db.get_balance(1) == STARTING_BALANCE + 10


def test_money_is_conserved_over_random_games(db):
    """Whatever the player does, the balance changes by a legal blackjack amount."""
    async def go():
        rng = random.Random(7)
        for user_id in range(1000, 1300):
            start = db.get_balance(user_id)
            assert db.try_debit(user_id, 10)
            view = BlackjackView(user_id, 10)
            view.check_naturals()
            action = rng.choice(["hit", "stand", "double"])
            while not view.settled:
                await getattr(view, action).callback(make_interaction(user_id))
                action = rng.choice(["hit", "stand"])
            assert db.get_balance(user_id) - start in (-20, -10, 0, 10, 15, 20)
    asyncio.run(go())
