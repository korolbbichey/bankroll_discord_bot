import sqlite3
from datetime import datetime, timedelta, timezone

from bot.config import STARTING_BALANCE, DAILY_REWARD, DAILY_STREAK_REWARDS


def test_new_user_has_starting_balance(db):
    assert db.get_balance(1) == STARTING_BALANCE


def test_checking_a_balance_does_not_create_an_account(db):
    db.get_balance(1)
    assert db.get_rank(1) is None
    assert db.get_player_count() == 0
    db.claim_daily_reward(1)
    assert db.get_player_count() == 1


def test_debit_and_credit(db):
    assert db.try_debit(1, 30)
    assert db.get_balance(1) == STARTING_BALANCE - 30
    assert not db.try_debit(1, 10**6), "can't spend more than the balance"
    assert db.get_balance(1) == STARTING_BALANCE - 30
    assert db.credit(1, 5) == STARTING_BALANCE - 25


def test_transfer(db):
    assert db.transfer(1, 2, 40)
    assert db.get_balance(1) == STARTING_BALANCE - 40
    assert db.get_balance(2) == STARTING_BALANCE + 40
    assert not db.transfer(1, 2, 10**6)
    assert db.get_balance(1) == STARTING_BALANCE - 40


DAY_1 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


def day(n: int, hour: int = 12) -> datetime:
    """Noon (by default) on the n-th day of the test calendar, starting at 1."""
    return DAY_1 + timedelta(days=n - 1, hours=hour - 12)


def test_daily_reward_once_per_day(db):
    claim = db.claim_daily_reward(1, now=day(1))
    assert claim.claimed and claim.is_new
    assert claim.balance == STARTING_BALANCE + DAILY_REWARD
    assert (claim.streak, claim.reward, claim.next_reward) == (1, DAILY_REWARD, DAILY_STREAK_REWARDS[1])
    assert claim.seconds_left == 12 * 3600

    again = db.claim_daily_reward(1, now=day(1, hour=23))
    assert not again.claimed and again.reward == 0
    assert again.balance == claim.balance and again.streak == 1


def test_daily_streak_grows_and_caps(db):
    rewards = [db.claim_daily_reward(1, now=day(n)).reward for n in range(1, 11)]
    assert rewards == DAILY_STREAK_REWARDS + [DAILY_STREAK_REWARDS[-1]] * 3
    assert db.claim_daily_reward(1, now=day(11)).streak == 11


def test_missing_a_day_resets_the_streak(db):
    db.claim_daily_reward(1, now=day(1))
    db.claim_daily_reward(1, now=day(2))
    assert db.get_daily_streak(1, now=day(3)) == 2, "still active the day after a claim"
    assert db.get_daily_streak(1, now=day(4)) == 0, "lost after a missed day"
    claim = db.claim_daily_reward(1, now=day(4))
    assert (claim.streak, claim.reward) == (1, DAILY_REWARD)


def test_streak_counts_utc_calendar_days(db):
    db.claim_daily_reward(1, now=day(1, hour=23))
    claim = db.claim_daily_reward(1, now=day(2, hour=0))  # one hour later, but a new UTC day
    assert claim.claimed and claim.streak == 2


def test_playing_does_not_reset_daily_reward(db):
    """Regression: REPLACE INTO used to wipe last_claim_date, allowing unlimited daily rewards."""
    db.claim_daily_reward(1, now=day(1))
    db.try_debit(1, 10)
    db.credit(1, 20)
    db.set_balance(1, 500)
    assert not db.claim_daily_reward(1, now=day(1)).claimed


def test_update_stats_counts_push_as_neither(db):
    db.update_stats(1, payout=0, bet=10)    # loss
    db.update_stats(1, payout=10, bet=10)   # bet returned
    db.update_stats(1, payout=30, bet=10)   # win, +20
    games, wins, losses, total_earned, largest_win = db.get_user_profile(1)["stats"]
    assert (games, wins, losses, total_earned, largest_win) == (3, 1, 1, 20, 20)


def test_most_common_symbol(db):
    db.update_stats(1, 0, 10, [["🍒", "🍒", "🍋"], ["🍒", "🍉", "🍋"], ["🔔", "⭐", "💎"]])
    assert db.get_user_profile(1)["most_common_symbol"] == "🍒"


def test_blackjack_stats(db):
    db.update_blackjack_stats(1, 15, is_win=True)
    db.update_blackjack_stats(1, 0, is_win=False, is_push=True)
    db.update_blackjack_stats(1, -10, is_win=False)
    assert db.get_user_profile(1)["blackjack"] == (1, 1, 15, 15)


def test_rank_and_player_count(db):
    db.set_balance(1, 50)
    db.set_balance(2, 500)
    db.set_balance(3, 200)
    assert [db.get_rank(u) for u in (2, 3, 1)] == [1, 2, 3]
    assert db.get_rank(999) is None
    assert db.get_player_count() == 3


def test_rank_matches_leaderboard_order_and_never_exceeds_total(db):
    """Regression: the footer showed 'Your position: #19' next to 'Total players: 15'."""
    for user_id, balance in [(5, 150), (3, 150), (9, 663), (4, 150), (7, 100)]:
        db.set_balance(user_id, balance)
    order = [row[0] for row in db.get_leaderboard(10)]
    assert order == [9, 3, 4, 5, 7], "ties are ordered by user id, consistently between calls"
    assert [db.get_rank(user_id) for user_id in order] == [1, 2, 3, 4, 5]
    assert max(db.get_rank(u) for u in order) <= db.get_player_count()


def test_leaderboard_includes_saved_usernames(db):
    db.set_balance(1, 300)
    db.set_balance(2, 100)
    assert db.save_username(1, "Alice")
    assert db.get_leaderboard(10) == [(1, 300, "Alice"), (2, 100, None)]


def test_save_username_needs_account_and_only_writes_changes(db):
    assert not db.save_username(42, "Ghost"), "no account -> nothing stored"
    db.credit(42, 0)
    assert db.save_username(42, "Ghost")
    assert db.save_username(42, "Ghost")
    db.save_username(42, "Renamed")
    assert db.get_leaderboard(1)[0][2] == "Renamed"


def test_announcement_shown_once_per_target_and_id(db):
    assert db.mark_announcement_shown(100, "update-1")
    assert not db.mark_announcement_shown(100, "update-1")
    assert db.mark_announcement_shown(200, "update-1")
    assert db.mark_announcement_shown(100, "update-2"), "a new announcement shows again"


def test_init_db_migrates_old_schema(db, tmp_path, monkeypatch):
    """An old database (no username column, clown symbol counts) is upgraded in place."""
    old = tmp_path / "old.db"
    conn = sqlite3.connect(old)
    conn.execute("CREATE TABLE currency (user_id INTEGER PRIMARY KEY, balance INTEGER DEFAULT 100, last_claim_date TEXT)")
    conn.execute("INSERT INTO currency VALUES (1, 777, NULL)")
    conn.execute("CREATE TABLE symbol_counts (user_id INTEGER, symbol TEXT, count INTEGER, PRIMARY KEY (user_id, symbol))")
    conn.execute("INSERT INTO symbol_counts VALUES (1, '🤡', 50), (1, '🍒', 3)")
    conn.commit()
    conn.close()

    monkeypatch.setattr(db, "DB_FILE", str(old))
    db.init_db()
    db.init_db()  # running twice is safe
    assert db.get_balance(1) == 777
    assert db.save_username(1, "Old player")
    assert db.claim_daily_reward(1).streak == 1, "daily_streak column was added"
    assert db.get_user_profile(1)["most_common_symbol"] == "🍒"
