import asyncio
import sqlite3

import pytest

from bot import progression
from bot.config import MAX_BET, XP_PER_GAME, XP_PER_WIN
from bot.progression import (
    BADGES, level_for_xp, level_progress, progress_bar, title_for_level, xp_for_level, record_game, record_badges,
)

from conftest import make_interaction


def badge_ids(progress):
    return [badge.id for badge in progress.new_badges]


# ---------- levels and titles ----------

def test_level_thresholds():
    assert [xp_for_level(n) for n in range(1, 6)] == [0, 100, 300, 600, 1000]
    assert level_for_xp(0) == 1
    assert level_for_xp(99) == 1
    assert level_for_xp(100) == 2
    assert level_for_xp(1000) == 5
    assert level_progress(350) == (3, 50, 300)


def test_progress_bar():
    assert progress_bar(0, 100) == "▱" * 10
    assert progress_bar(50, 100) == "▰" * 5 + "▱" * 5
    assert progress_bar(100, 100) == "▰" * 10


@pytest.mark.parametrize("level, title", [(1, "Rookie"), (2, "Rookie"), (3, "Gambler"), (6, "High Roller"),
                                          (10, "Card Shark"), (15, "Casino King"), (25, "Legend"), (99, "Legend")])
def test_titles(level, title):
    assert title_for_level(level).name == title


def test_badge_ids_are_unique():
    assert len({badge.id for badge in BADGES}) == len(BADGES)


# ---------- XP ----------

def test_xp_per_game_and_level_up(db):
    progress = record_game(1, "coinflip", 10, 0)
    assert db.get_player_progress(1)[0] == XP_PER_GAME and not progress.leveled_up
    for _ in range(6):
        progress = record_game(1, "coinflip", 10, 20)
    assert db.get_player_progress(1)[0] == XP_PER_GAME * 7 + XP_PER_WIN * 6  # 100 XP
    assert progress.leveled_up and progress.level_after == 2
    assert "Level up" in progress.notice()


def test_new_title_is_announced(db):
    for _ in range(19):  # 285 XP, level 2
        record_game(1, "slots", 10, 30)
    progress = record_game(1, "slots", 10, 30)  # 300 XP -> level 3 = Gambler
    assert progress.level_after == 3
    assert "New title: 🎲 **Gambler**" in progress.notice()


def test_game_stats_and_first_played(db):
    record_game(1, "slots", 10, 30)
    record_game(1, "slots", 10, 0)
    assert db.get_game_stats(1) == {"slots": (2, 1, 10)}
    assert db.get_player_progress(1)[1] is not None


# ---------- badges ----------

def test_first_win_only_once(db):
    assert badge_ids(record_game(1, "coinflip", 10, 0)) == []
    assert badge_ids(record_game(1, "coinflip", 10, 20)) == ["first_win"]
    assert "first_win" not in badge_ids(record_game(1, "coinflip", 10, 20))


def test_bet_returned_is_not_a_win(db):
    assert badge_ids(record_game(1, "slots", 10, 10)) == []


def test_explorer(db):
    record_game(1, "slots", 10, 0)
    record_game(1, "coinflip", 10, 0)
    assert badge_ids(record_game(1, "blackjack", 10, 0)) == ["explorer"]


def test_slot_badges(db):
    progress = record_game(1, "slots", 10, 80, winning_combos=["🍒🍒🍒", "💎💎💎", "🍋🍋🍋"])
    assert {"multi_line", "diamond_line", "first_win"} <= set(badge_ids(progress))


def test_spin_master(db):
    for _ in range(99):
        record_game(1, "slots", 1, 0)
    assert "spins_100" in badge_ids(record_game(1, "slots", 1, 0))


def test_blackjack_badges(db):
    assert "natural" in badge_ids(record_game(1, "blackjack", 10, 25, natural=True))
    assert "double_win" not in badge_ids(record_game(1, "blackjack", 20, 0, doubled=True))
    assert "double_win" in badge_ids(record_game(1, "blackjack", 20, 40, doubled=True))


def test_coin_collector(db):
    for _ in range(9):
        record_game(1, "coinflip", 1, 2)
    assert "coin_10" in badge_ids(record_game(1, "coinflip", 1, 2))


def test_big_spender(db):
    assert "max_bet" in badge_ids(record_game(1, "coinflip", MAX_BET, 0))


def test_wealth_badges(db):
    db.set_balance(1, 10_000)
    assert "rich" in badge_ids(record_game(1, "coinflip", 1, 0))

    assert "podium" not in badge_ids(record_game(2, "coinflip", 1, 0)), "needs some competition first"
    for user_id in range(100, 110):
        db.set_balance(user_id, 50)
    assert "podium" in badge_ids(record_game(1, "coinflip", 1, 0))


def test_badges_outside_games(db):
    assert badge_ids(record_badges(1, ["generous"])) == ["generous"]
    assert badge_ids(record_badges(1, ["generous"])) == []
    db.set_balance(1, 20_000)
    assert badge_ids(record_badges(1, [], check_wealth=True)) == ["rich"]
    assert record_badges(1, []).notice() is None


def test_badge_notice_text(db):
    notice = record_game(1, "coinflip", 10, 20).notice()
    assert notice == "🏅 **New badge:** 🍀 First Win — Win any game"


def test_progression_errors_never_break_games(db, monkeypatch):
    monkeypatch.setattr(progression, "record_game_result", lambda *a, **k: 1 / 0)
    assert progression.track_game(1, "slots", 10, 0) is None


# ---------- migration ----------

def test_existing_players_get_xp_from_old_stats(db, tmp_path, monkeypatch):
    old = tmp_path / "old.db"
    conn = sqlite3.connect(old)
    conn.execute("CREATE TABLE currency (user_id INTEGER PRIMARY KEY, balance INTEGER DEFAULT 100, last_claim_date TEXT)")
    conn.execute("CREATE TABLE stats (user_id INTEGER PRIMARY KEY, games_played INTEGER, wins INTEGER, losses INTEGER,"
                 " total_earned INTEGER, most_common_symbol TEXT, largest_win INTEGER)")
    conn.execute("INSERT INTO stats VALUES (1, 48, 11, 31, 750, '', 400)")
    conn.execute("CREATE TABLE blackjack_stats (user_id INTEGER PRIMARY KEY, blackjack_wins INTEGER,"
                 " blackjack_losses INTEGER, blackjack_total_earned INTEGER, blackjack_largest_win INTEGER)")
    conn.execute("INSERT INTO blackjack_stats VALUES (1, 1, 0, 2, 2), (2, 2, 3, 20, 10)")
    conn.commit()
    conn.close()

    monkeypatch.setattr(db, "DB_FILE", str(old))
    db.init_db()
    db.init_db()  # the backfill runs only once
    assert db.get_player_progress(1) == ((48 + 1) * XP_PER_GAME + (11 + 1) * XP_PER_WIN, None)
    assert db.get_player_progress(2) == (5 * XP_PER_GAME + 2 * XP_PER_WIN, None)
    assert db.get_badges(1) == {"first_win"} and db.get_badges(2) == {"first_win"}
    assert db.get_badges(3) == set()


# ---------- notices in games ----------

def test_slots_sends_badge_notice(db, monkeypatch):
    from bot.games import slots

    async def instant(_):
        pass
    monkeypatch.setattr(slots.asyncio, "sleep", instant)
    columns = [["💎", "🍋", "🔔"], ["💎", "🍒", "⭐"], ["💎", "🍉", "🍋"]]
    monkeypatch.setattr(slots.random, "choices", lambda *a, **k: columns.pop(0))

    async def go():
        view = slots.SlotView(1, 10)
        interaction = make_interaction(1)
        await view.spin(interaction)
        return interaction.followup.send
    notice = asyncio.run(go())
    message = notice.call_args.args[0]
    assert "🍀 First Win" in message and "💎 Diamond Hands" in message
    assert notice.call_args.kwargs["ephemeral"] is True


def test_blackjack_natural_sends_badge_notice(db):
    from bot.games.blackjack import BlackjackView

    async def go():
        assert db.try_debit(1, 10)
        view = BlackjackView(1, 10)
        view.player, view.dealer = [("A", "♠"), ("K", "♠")], [("9", "♥"), ("7", "♥")]
        view.check_naturals()
        await progression.send_notice(make_interaction(1), view.progress)
        return view.progress
    assert "natural" in badge_ids(asyncio.run(go()))
