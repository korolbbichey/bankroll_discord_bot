import asyncio
import io
import time

import discord
import pytest
from PIL import Image

import main
from bot import crypto_feed
from bot.crypto_card import BetCard, price_text, render_bet_card, render_market_card
from bot.crypto_feed import PriceFeed
from bot.games import crypto

from conftest import make_interaction


# ---------- the price feed ----------

def test_feed_keeps_the_last_hour():
    feed = PriceFeed()
    feed.add({"BTC": 100.0}, 1000.0)
    feed.add({"BTC": 101.0}, 1005.0)
    feed.add({"BTC": 99.0}, 1004.0)  # older than the last point: ignored
    feed.add({"BTC": 102.0}, 1000.0 + 3601)
    assert [p for _, p in feed.points["BTC"]] == [101.0, 102.0]
    assert feed.latest("BTC") == (4601.0, 102.0)


def test_first_price_after_a_moment():
    feed = PriceFeed()
    for at, price in ((10.0, 1.0), (15.0, 2.0), (20.0, 3.0)):
        feed.add({"ETH": price}, at)
    assert feed.first_after("ETH", 12.0) == (15.0, 2.0)
    assert feed.first_after("ETH", 15.0) == (15.0, 2.0)
    assert feed.first_after("ETH", 21.0) is None
    assert feed.since("ETH", 15.0) == [(15.0, 2.0), (20.0, 3.0)]


def test_freshness():
    feed = PriceFeed()
    assert not feed.is_fresh()
    feed.add({"BTC": 1.0}, 100.0)
    assert feed.is_fresh(now=110.0) and not feed.is_fresh(now=200.0)


def test_waiting_for_the_next_price():
    async def go():
        feed = PriceFeed()
        feed.add({"BTC": 1.0}, time.time() - 1)
        moment = time.time()

        async def later():
            await asyncio.sleep(0.05)
            async with feed.new_prices:
                feed.add({"BTC": 2.0}, time.time())
                feed.new_prices.notify_all()
        asyncio.create_task(later())
        found = await feed.price_after("BTC", moment, timeout=2)
        missing = await feed.price_after("BTC", time.time() + 100, timeout=0.05)
        return found, missing
    found, missing = asyncio.run(go())
    assert found[1] == 2.0 and missing is None


class FakeReply:
    def __init__(self, data):
        self.data = data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    def raise_for_status(self):
        pass

    async def json(self):
        return self.data


class FakeSession:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def get(self, url, params=None):
        self.calls.append((url, params))
        return FakeReply(self.data)


def test_fetch_prices_and_history():
    prices = asyncio.run(crypto_feed.fetch_prices(FakeSession(
        [{"symbol": "BTCUSDT", "price": "61791.91"}, {"symbol": "SUIUSDT", "price": "0.6674"}])))
    assert prices == {"BTC": 61791.91, "SUI": 0.6674}

    now_ms = time.time() * 1000
    candles = [[0, "1", "1", "1", "100.5", "0", now_ms - 60_000], [0, "1", "1", "1", "101.5", "0", now_ms + 30_000]]
    history = asyncio.run(crypto_feed.fetch_history(FakeSession(candles), "BTC"))
    assert [price for _, price in history] == [100.5], "the running candle is left out"

    info = {"symbols": [{"symbol": "BTCUSDT", "status": "TRADING"}, {"symbol": "TONUSDT", "status": "BREAK"}]}
    assert asyncio.run(crypto_feed.fetch_trading(FakeSession(info))) == {"BTC"}


# ---------- the database ----------

def test_open_bets_take_coins_and_have_a_limit(db):
    db.set_balance(1, 1000)
    first = db.open_crypto_bet(1, "BTC", True, 300, 1, max_open=2)
    assert isinstance(first, int) and db.get_balance(1) == 700
    db.open_crypto_bet(1, "ETH", False, 300, 1, max_open=2)
    assert db.open_crypto_bet(1, "SOL", True, 100, 1, max_open=2) == "too_many"
    assert db.get_balance(1) == 400
    db.set_balance(2, 50)
    assert db.open_crypto_bet(2, "BTC", True, 100, 1, max_open=2) == "no_coins"


def test_a_bet_settles_once(db):
    db.set_balance(1, 1000)
    bet_id = db.open_crypto_bet(1, "BTC", True, 100, 1, max_open=3)
    assert db.settle_crypto_bet(bet_id, "won", 190, 101.0) == 1090
    assert db.settle_crypto_bet(bet_id, "won", 190, 101.0) is None
    assert db.get_balance(1) == 1090


def test_open_bets_are_refunded_at_startup(db):
    db.set_balance(1, 1000)
    db.open_crypto_bet(1, "BTC", True, 400, 5, max_open=3)
    assert db.refund_open_crypto_bets() == 1
    assert db.get_balance(1) == 1000
    assert db.refund_open_crypto_bets() == 0


def test_crowd(db):
    db.set_balance(1, 10_000)
    for up in (True, True, False):
        db.open_crypto_bet(1, "BTC", up, 10, 1, max_open=10)
    db.open_crypto_bet(1, "ETH", True, 10, 1, max_open=10)
    assert db.crypto_crowd("BTC") == (2, 1)


# ---------- the game ----------

def test_outcome():
    assert crypto.outcome(True, 100.0, 101.0) == "won"
    assert crypto.outcome(True, 100.0, 99.0) == "lost"
    assert crypto.outcome(False, 100.0, 99.0) == "won"
    assert crypto.outcome(False, 100.0, 100.0) == "push"
    assert crypto.payout_if_won(500) == 950


class FakeFeed:
    """Prices for one bet: the entry and the close, already in the past so the bet ends at once."""

    def __init__(self, entry, close, fresh=True, minutes=1):
        self.fresh = fresh
        start = time.time() - minutes * 60 - 5
        self.entry = (start, entry) if entry is not None else None
        self.close = (start + minutes * 60 + 1, close) if close is not None else None

    def is_fresh(self):
        return self.fresh

    def is_trading(self, coin):
        return coin != "AVAX"  # as if its trading were halted

    async def price_after(self, coin, moment, timeout):
        """The first call asks for the entry price, the second for the close."""
        self.asked = getattr(self, "asked", 0) + 1
        return self.entry if self.asked == 1 else self.close

    def since(self, coin, start):
        return [point for point in (self.entry, self.close) if point]


@pytest.fixture
def quick_draw(monkeypatch):
    """Cards are drawn for real but without the thread pool."""
    async def draw(render, data):
        return discord.File(io.BytesIO(render(data)), filename=crypto.CARD_NAME)
    monkeypatch.setattr(crypto, "draw", draw)


def play(feed, monkeypatch, up=True, bet=500, balance=1000, minutes=1, coin="BTC"):
    monkeypatch.setattr(crypto_feed, "feed", feed)
    interaction = make_interaction(1, done=False)
    import bot.database as database
    database.set_balance(1, balance)
    asyncio.run(crypto.start_crypto_bet(interaction, coin, up, bet, minutes))
    return interaction


def test_paused_coins_take_no_bets(db, monkeypatch):
    interaction = play(FakeFeed(1.6, 1.6), monkeypatch, coin="AVAX")
    assert "paused" in interaction.response.send_message.call_args.args[0]
    assert db.get_balance(1) == 1000


def test_a_right_guess_pays(db, monkeypatch, quick_draw):
    interaction = play(FakeFeed(100.0, 101.0), monkeypatch)
    assert db.get_balance(1) == 1000 - 500 + 950
    assert interaction.edit_original_response.call_args.kwargs["attachments"][0].filename == crypto.CARD_NAME
    assert db.get_game_stats(1)["crypto"][:2] == (1, 1)


def test_a_wrong_guess_loses(db, monkeypatch, quick_draw):
    play(FakeFeed(100.0, 101.0), monkeypatch, up=False)
    assert db.get_balance(1) == 500


def test_an_unchanged_price_returns_the_bet(db, monkeypatch, quick_draw):
    play(FakeFeed(100.0, 100.0), monkeypatch)
    assert db.get_balance(1) == 1000


def test_no_entry_price_refunds(db, monkeypatch, quick_draw):
    interaction = play(FakeFeed(None, None), monkeypatch)
    assert db.get_balance(1) == 1000
    assert "coins are back" in interaction.edit_original_response.call_args.kwargs["content"]


def test_no_closing_price_refunds(db, monkeypatch, quick_draw):
    feed = FakeFeed(100.0, None)
    interaction = play(feed, monkeypatch)
    assert db.get_balance(1) == 1000
    assert "coins are back" in interaction.edit_original_response.call_args.kwargs["content"]


def test_stale_prices_take_nothing(db, monkeypatch):
    interaction = play(FakeFeed(100.0, 101.0, fresh=False), monkeypatch)
    assert db.get_balance(1) == 1000
    assert "aren't available" in interaction.response.send_message.call_args.args[0]


def test_bet_limits(db, monkeypatch):
    interaction = play(FakeFeed(100.0, 101.0), monkeypatch, bet=20_000, balance=50_000)
    assert "maximum crypto bet" in interaction.response.send_message.call_args.args[0]
    assert db.get_balance(1) == 50_000


def test_text_when_the_card_cant_be_drawn(db, monkeypatch):
    async def broken(render, data):
        raise RuntimeError("no fonts")
    monkeypatch.setattr(crypto, "draw", broken)
    interaction = play(FakeFeed(100.0, 101.0), monkeypatch)
    assert "You won 450" in interaction.edit_original_response.call_args.kwargs["embed"].title
    assert db.get_balance(1) == 1450


def test_commands_are_registered(db):
    async def go():
        client = main.BankRollBot()
        crypto.setup(client)
        group = client.tree.get_command("crypto")
        return sorted(command.name for command in group.commands)
    assert asyncio.run(go()) == ["bet", "market"]


def test_market_command(db, monkeypatch, quick_draw):
    feed = PriceFeed()
    now = time.time()
    feed.add({"BTC": 100.0, "ETH": 10.0}, now - 60)
    feed.add({"BTC": 101.0, "ETH": 9.0}, now)
    monkeypatch.setattr(crypto_feed, "feed", feed)

    async def go():
        client = main.BankRollBot()
        crypto.setup(client)
        interaction = make_interaction(1, done=False)
        await client.tree.get_command("crypto").get_command("market").callback(interaction)
        return interaction
    interaction = asyncio.run(go())
    assert interaction.followup.send.call_args.kwargs["file"].filename == crypto.CARD_NAME


# ---------- the cards ----------

def card(status="open", points=None, crowd=None):
    now = time.time()
    points = points if points is not None else [(now - 300 + i * 5, 100 + (i % 7) * 0.3) for i in range(70)]
    return BetCard(coin="BTC", up=True, bet=500, minutes=5, payout_if_won=950, entry=100.5, entry_at=now - 60,
                   ends_at=now + 240, points=points, now=now, status=status,
                   close=None if status == "open" else 101.0, winnings=450, balance=1450, crowd=crowd)


@pytest.mark.parametrize("status", ["open", "won", "lost", "push"])
def test_bet_cards_draw(status):
    png = render_bet_card(card(status, crowd=(6, 4)))
    assert Image.open(io.BytesIO(png)).size == (1000, 540)


def test_bet_card_without_history():
    render_bet_card(card(points=[]))


def test_market_card_draws():
    now = time.time()
    png = render_market_card({"BTC": [(now - 60, 100.0), (now, 101.0)], "SUI": [(now, 0.6674)], "LINK": [],
                              "AVAX": [(now, 6.593)]}, paused={"AVAX"})
    assert Image.open(io.BytesIO(png)).width == 1000


def test_price_text():
    assert price_text(61791.912) == "$61,791.91"
    assert price_text(1.6) == "$1.6000"
    assert price_text(0.0583) == "$0.05830"
    assert price_text(0.00000361) == "$0.00000361"
