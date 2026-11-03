"""Quick-play buttons, the bailout, duels and owner statistics."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import discord
import pytest

import main
from bot import progression
from bot.commands.economy import QuickPlayView
from bot.config import BAILOUT_AMOUNT, COIN_EVENT_MIN, QUICK_PLAY_BET, STARTING_BALANCE
from bot.games import duel, slots
from bot.games.duel import DuelView

from conftest import make_interaction, make_user, sent_embed

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def bot():
    async def build():
        client = main.BankRollBot()
        for module in (main.economy, main.slots, main.blackjack, main.coinflip, main.duel):
            module.setup(client)
        return client
    return asyncio.run(build())


@pytest.fixture(autouse=True)
def instant(monkeypatch):
    async def no_wait(_):
        pass
    monkeypatch.setattr(asyncio, "sleep", no_wait)


def command(bot, name):
    return bot.tree.get_command(name)


# ---------- bailout ----------

def test_bailout_only_with_an_empty_wallet_and_once_a_day(db):
    assert db.claim_bailout(1, now=NOW)[0] == "has_coins", "a new player still has starting coins"
    assert db.get_balance(1) == STARTING_BALANCE

    db.set_balance(1, 0)
    assert db.claim_bailout(1, now=NOW) == ("ok", BAILOUT_AMOUNT)
    db.set_balance(1, 0)
    assert db.claim_bailout(1, now=NOW) == ("already_claimed", 0)
    assert db.claim_bailout(1, now=NOW + timedelta(days=1)) == ("ok", BAILOUT_AMOUNT)


def test_bailout_does_not_touch_the_daily_reward(db):
    db.claim_daily_reward(1, now=NOW)
    db.set_balance(1, 0)
    db.claim_bailout(1, now=NOW)
    assert not db.claim_daily_reward(1, now=NOW).claimed


def test_bailout_command(bot, db):
    db.set_balance(1, 0)

    async def run():
        interaction = make_interaction(1, done=False)
        await command(bot, "bailout").callback(interaction)
        return interaction.response.send_message.call_args
    first = asyncio.run(run())
    assert "25" in first.args[0] and first.kwargs["ephemeral"] is True
    assert isinstance(first.kwargs["view"], QuickPlayView)
    assert "already got" in asyncio.run(run()).args[0] or "only for empty" in asyncio.run(run()).args[0]


def test_empty_wallet_error_suggests_help():
    from bot.utils import validate_bet
    assert "/bailout" in validate_bet(10, 0)[1]
    assert "/bailout" not in validate_bet(500, 100)[1]


# ---------- quick play ----------

def test_daily_reward_offers_games(bot, db):
    async def go():
        interaction = make_interaction(1, done=False)
        await command(bot, "daily_reward").callback(interaction)
        return interaction.response.send_message.call_args.kwargs["view"]
    view = asyncio.run(go())
    assert isinstance(view, QuickPlayView) and len(view.children) == 3


def test_quick_bet_never_exceeds_the_balance(db):
    db.set_balance(1, 4)
    assert QuickPlayView.quick_bet(1) == 4
    db.set_balance(1, 1000)
    assert QuickPlayView.quick_bet(1) == QUICK_PLAY_BET


def test_quick_play_buttons_start_public_games(db):
    async def go():
        view = QuickPlayView()
        spin = make_interaction(1, done=False)
        await view.spin.callback(spin)
        assert "ephemeral" not in spin.response.send_message.call_args.kwargs
        for button in (view.flip, view.blackjack):
            interaction = make_interaction(1, done=False)
            await button.callback(interaction)
            interaction.response.defer.assert_awaited_with(thinking=True)
    asyncio.run(go())
    assert db.get_game_stats(1).keys() >= {"slots", "coinflip"}


# ---------- duels ----------

def new_duel(db, bet=10):
    duel_id = db.open_duel(1, 2, bet)
    assert duel_id is not None
    view = DuelView(duel_id, make_user(1, global_name="Ann"), make_user(2, global_name="Bob"), bet)
    view.last_interaction = make_interaction(1)
    return view


def force_coin(monkeypatch, outcome):
    monkeypatch.setattr(duel.random, "choice", lambda options: outcome)


def test_duel_command_takes_the_bet(bot, db):
    async def go():
        interaction = make_interaction(1, done=False)
        await command(bot, "duel").callback(interaction, make_user(2), 30)
        assert isinstance(interaction.response.send_message.call_args.kwargs["view"], DuelView)
        assert interaction.response.send_message.call_args.args[0] == make_user(2).mention
    asyncio.run(go())
    assert db.get_balance(1) == STARTING_BALANCE - 30
    assert db.get_balance(2) == STARTING_BALANCE, "the opponent pays only when accepting"


@pytest.mark.parametrize("target, bet, guild, message", [
    (make_user(1), 10, 100, "yourself"),
    (make_user(9, bot=True), 10, 100, "bot"),
    (make_user(2), 5000, 100, "enough coins"),
    (make_user(2), 10, None, "server"),
])
def test_invalid_duels_cost_nothing(bot, db, target, bet, guild, message):
    async def go():
        interaction = make_interaction(1, done=False, guild_id=guild)
        await command(bot, "duel").callback(interaction, target, bet)
        return interaction.response.send_message.call_args
    call = asyncio.run(go())
    assert message in call.args[0] and call.kwargs["ephemeral"] is True
    assert db.get_balance(1) == STARTING_BALANCE


@pytest.mark.parametrize("outcome, winner, loser", [("heads", 1, 2), ("tails", 2, 1)])
def test_accepting_settles_the_duel(db, monkeypatch, outcome, winner, loser):
    force_coin(monkeypatch, outcome)

    async def go():
        view = new_duel(db)
        interaction = make_interaction(2, done=False)
        await view.accept.callback(interaction)
        assert view.finished and all(item.disabled for item in view.children)
        first = interaction.edit_original_response.call_args_list[0]
        assert first.kwargs["attachments"][0].filename == "duel.gif"
        return sent_embed(interaction.edit_original_response)
    embed = asyncio.run(go())
    assert db.get_balance(winner) == STARTING_BALANCE + 10
    assert db.get_balance(loser) == STARTING_BALANCE - 10
    assert "wins the duel" in embed.title
    assert db.get_game_stats(winner)["duel"] == (1, 1, 10)
    assert db.get_game_stats(loser)["duel"] == (1, 0, -10)


def test_only_the_opponent_can_accept(db):
    async def go():
        view = new_duel(db)
        for user_id in (1, 3):
            interaction = make_interaction(user_id, done=False)
            await view.accept.callback(interaction)
            assert interaction.response.send_message.call_args.kwargs["ephemeral"] is True
        assert not view.finished
    asyncio.run(go())
    assert db.get_balance(3) == STARTING_BALANCE


def test_accepting_without_coins_keeps_the_duel_open(db):
    db.set_balance(2, 5)

    async def go():
        view = new_duel(db)
        interaction = make_interaction(2, done=False)
        await view.accept.callback(interaction)
        assert not view.finished and "You need" in interaction.response.send_message.call_args.args[0]
    asyncio.run(go())
    assert db.get_balance(2) == 5


@pytest.mark.parametrize("user_id, word", [(2, "declined"), (1, "cancelled")])
def test_declining_refunds_the_challenger(db, user_id, word):
    async def go():
        view = new_duel(db)
        interaction = make_interaction(user_id, done=False)
        await view.decline.callback(interaction)
        assert word in sent_embed(interaction.response.edit_message).title
        stranger = make_interaction(user_id, done=False)
        await view.decline.callback(stranger)  # a second click can't refund twice
        assert "already over" in stranger.response.send_message.call_args.args[0]
    asyncio.run(go())
    assert db.get_balance(1) == STARTING_BALANCE


def test_strangers_cannot_decline(db):
    async def go():
        view = new_duel(db)
        await view.decline.callback(make_interaction(3, done=False))
        assert not view.finished
    asyncio.run(go())


def test_expired_duel_refunds_once(db):
    async def go():
        view = new_duel(db)
        await view.on_timeout()
        await view.on_timeout()
        assert "expired" in sent_embed(view.last_interaction.edit_original_response).title
        late = make_interaction(2, done=False)
        await view.accept.callback(late)
        assert "already over" in late.response.send_message.call_args.args[0]
    asyncio.run(go())
    assert db.get_balance(1) == STARTING_BALANCE
    assert db.get_balance(2) == STARTING_BALANCE


def test_failed_duel_animation_still_pays(db, monkeypatch):
    force_coin(monkeypatch, "heads")

    def broken(*args):
        raise OSError("no font")
    monkeypatch.setattr(duel, "render_flip_gif", broken)

    async def go():
        view = new_duel(db)
        interaction = make_interaction(2, done=False)
        await view.accept.callback(interaction)
        return sent_embed(interaction.edit_original_response)
    assert asyncio.run(go()).image.url is None
    assert db.get_balance(1) == STARTING_BALANCE + 10


def test_duels_open_at_a_restart_are_refunded(db):
    new_duel(db, bet=30)
    new_duel(db, bet=20)
    assert db.get_balance(1) == STARTING_BALANCE - 50
    assert db.refund_pending_duels() == 2
    assert db.refund_pending_duels() == 0
    assert db.get_balance(1) == STARTING_BALANCE


def test_finished_duels_are_not_refunded_at_a_restart(db, monkeypatch):
    force_coin(monkeypatch, "tails")

    async def go():
        accepted, declined = new_duel(db), new_duel(db)
        await accepted.accept.callback(make_interaction(2, done=False))
        await declined.decline.callback(make_interaction(2, done=False))
    asyncio.run(go())
    assert db.refund_pending_duels() == 0
    assert (db.get_balance(1), db.get_balance(2)) == (STARTING_BALANCE - 10, STARTING_BALANCE + 10)


def test_a_refunded_duel_cannot_be_accepted(db):
    async def go():
        view = new_duel(db)
        db.refund_pending_duels()
        interaction = make_interaction(2, done=False)
        await view.accept.callback(interaction)
        assert "already over" in interaction.response.send_message.call_args.args[0]
    asyncio.run(go())
    assert (db.get_balance(1), db.get_balance(2)) == (STARTING_BALANCE, STARTING_BALANCE)


def test_duel_only_player_has_a_profile(bot, db):
    db.set_balance(1, 50)
    progression.record_game(1, "duel", 10, 20)

    async def go():
        interaction = make_interaction(1, done=False)
        await command(bot, "profile").callback(interaction, None)
        return interaction.followup.send.call_args.kwargs["file"]
    assert asyncio.run(go()).filename == "profile.png"


# ---------- statistics ----------

def test_daily_activity_and_retention(db, monkeypatch):
    def play(user_id, when):
        db.record_game_result(user_id, "slots", False, -10, 10, when.strftime("%Y-%m-%d"))
    yesterday, two_days_ago = NOW - timedelta(days=1), NOW - timedelta(days=2)
    play(1, two_days_ago)
    play(1, yesterday)  # came back
    play(2, two_days_ago)  # never came back
    play(3, NOW)
    play(3, NOW)  # new today: too early to count as returned or not

    stats = db.get_bot_stats(now=NOW)
    today, previous = stats["days"][0], stats["days"][1]
    assert (today["new"], today["active"], today["games"]) == (1, 1, 2)
    assert (previous["new"], previous["active"], previous["games"]) == (0, 1, 1)
    assert (stats["cohort"], stats["returned"]) == (2, 1)
    assert stats["games"] == [("slots", 5, 3, -50)]


def old_database_with_veterans(tmp_path):
    """A database from before the veteran flag: players 1 and 2 played before game_stats existed, 3 and 4 after."""
    import sqlite3
    path = tmp_path / "before_veterans.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE stats (user_id INTEGER PRIMARY KEY, games_played INTEGER DEFAULT 0, wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0, total_earned INTEGER DEFAULT 0, most_common_symbol TEXT DEFAULT '',
            largest_win INTEGER DEFAULT 0);
        CREATE TABLE blackjack_stats (user_id INTEGER PRIMARY KEY, blackjack_wins INTEGER DEFAULT 0,
            blackjack_losses INTEGER DEFAULT 0, blackjack_total_earned INTEGER DEFAULT 0,
            blackjack_largest_win INTEGER DEFAULT 0);
        CREATE TABLE players (user_id INTEGER PRIMARY KEY, xp INTEGER DEFAULT 0, first_played TEXT);
        CREATE TABLE game_stats (user_id INTEGER NOT NULL, game TEXT NOT NULL, games INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0, net INTEGER DEFAULT 0, PRIMARY KEY (user_id, game));
        -- 1: 20 slots games before, 2 after; 2: an old blackjack loss, came back for one win
        INSERT INTO stats VALUES (1, 22, 5, 17, 0, '', 0);
        INSERT INTO blackjack_stats VALUES (2, 1, 1, 10, 10);
        -- 3: new, everything recorded in both; 4: new, a blackjack push that the old stats don't count
        INSERT INTO stats VALUES (3, 4, 1, 3, 0, '', 0);
        INSERT INTO blackjack_stats VALUES (4, 1, 0, 10, 10);
        INSERT INTO players VALUES (1, 0, '2026-11-08'), (2, 0, '2026-11-08'), (3, 0, '2026-11-08'),
                                   (4, 0, '2026-11-08'), (5, 0, NULL);
        INSERT INTO game_stats VALUES (1, 'slots', 2, 0, -20), (2, 'blackjack', 1, 1, 10), (3, 'slots', 3, 1, 0),
                                      (3, 'coinflip', 1, 0, -10), (4, 'blackjack', 2, 1, 10);
    """)
    conn.close()
    return path


def test_old_players_are_marked_as_veterans(db, tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_FILE", str(old_database_with_veterans(tmp_path)))
    db.init_db()
    db.init_db()
    with db.get_connection() as conn:
        veterans = {row[0] for row in conn.execute("SELECT user_id FROM players WHERE veteran")}
    assert veterans == {1, 2, 5}

    for user_id in (1, 3):
        db.record_game_result(user_id, "slots", False, -10, 10, "2026-11-10")
    stats = db.get_bot_stats(now=NOW)
    assert stats["days"][2]["new"] == 2, "only 3 and 4 were new on 11-08"
    assert (stats["cohort"], stats["returned"], stats["veterans_back"]) == (2, 1, 1)
    assert db.get_player_progress(1)[1] is None, "a veteran's first game is unknown"
    assert db.get_player_progress(3)[1] == "2026-11-08"


def test_never_played_counts_accounts_without_games(db):
    db.claim_daily_reward(1)
    db.claim_daily_reward(2)
    progression.record_game(2, "slots", 10, 0)
    stats = db.get_bot_stats()
    assert (stats["accounts"], stats["never_played"]) == (2, 1)


def test_only_big_coin_movements_are_logged(db):
    db.save_username(1, "x")
    progression.record_game(1, "slots", 10, COIN_EVENT_MIN + 10)  # big win
    progression.record_game(1, "slots", 10, 30)  # small win
    db.record_coin_event(2, "pay", COIN_EVENT_MIN - 1)
    db.record_coin_event(2, "pay", COIN_EVENT_MIN, "from 1")
    events = db.get_bot_stats()["events"]
    assert [(e[1], e[3], e[4]) for e in events] == [(1, "slots", COIN_EVENT_MIN), (2, "pay", COIN_EVENT_MIN)]


def test_big_pay_is_logged(bot, db):
    db.set_balance(1, 5000)

    async def go():
        await command(bot, "pay").callback(make_interaction(1), make_user(2), 2000)
    asyncio.run(go())
    assert db.get_bot_stats()["events"][0][3:] == ("pay", 2000, "from 1")


def test_admin_stats_command(db, monkeypatch):
    monkeypatch.setattr(main.admin, "ADMIN_GUILD_ID", 123)
    progression.record_game(1, "slots", 10, COIN_EVENT_MIN + 10)

    async def go():
        client = main.BankRollBot()
        main.admin.setup(client)
        group = client.tree.get_command("admin", guild=discord.Object(123))
        interaction = make_interaction(42, done=False)
        await group.get_command("stats").callback(interaction)
        return sent_embed(interaction.response.send_message), interaction.response.send_message.call_args.kwargs
    embed, kwargs = asyncio.run(go())
    assert kwargs["ephemeral"] is True
    assert [f.name for f in embed.fields] == ["👥 Players", "📅 Last 7 days (UTC)", "🎮 Games, all time", "💰 Biggest coin movements"]
    assert "slots" in embed.fields[2].value and "+1,000" in embed.fields[3].value


def test_new_tables_are_added_to_an_old_database(db, tmp_path, monkeypatch):
    import sqlite3
    old = tmp_path / "old.db"
    conn = sqlite3.connect(old)
    conn.execute("CREATE TABLE currency (user_id INTEGER PRIMARY KEY, balance INTEGER DEFAULT 100, last_claim_date TEXT)")
    conn.execute("INSERT INTO currency VALUES (1, 0, NULL)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(db, "DB_FILE", str(old))
    db.init_db()
    assert db.claim_bailout(1, now=NOW)[0] == "ok"
    assert db.get_bot_stats(now=NOW)["accounts"] == 1


def test_slots_quick_start_checks_the_bet(db):
    db.set_balance(1, 0)

    async def go():
        interaction = make_interaction(1, done=False)
        await slots.start_slots(interaction, 1)
        return interaction.response.send_message.call_args
    call = asyncio.run(go())
    assert "/bailout" in call.args[0] and call.kwargs["ephemeral"] is True
