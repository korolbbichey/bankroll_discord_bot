"""
Database operations for the BankRoll Discord Bot.

All balance changes are done with single atomic UPDATE statements so that
concurrent games can never read a stale balance and overwrite each other.
"""

import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .config import (
    DB_FILE, STARTING_BALANCE, DAILY_STREAK_REWARDS, XP_PER_GAME, XP_PER_WIN, BAILOUT_AMOUNT, COIN_EVENT_MIN,
    BADGE_RARITY, BADGE_REWARDS_SINCE, OLD_BADGE_COINS, badge_coins,
)


@contextmanager
def get_connection():
    """Context manager for database connections."""
    conn = sqlite3.connect(DB_FILE, timeout=10)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Initialize all database tables."""
    db_dir = os.path.dirname(DB_FILE)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")

        cursor.execute('''CREATE TABLE IF NOT EXISTS currency (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 100,
            last_claim_date TEXT
        )''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS stats (
            user_id INTEGER PRIMARY KEY,
            games_played INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            total_earned INTEGER DEFAULT 0,
            most_common_symbol TEXT DEFAULT '',
            largest_win INTEGER DEFAULT 0
        )''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS blackjack_stats (
            user_id INTEGER PRIMARY KEY,
            blackjack_wins INTEGER DEFAULT 0,
            blackjack_losses INTEGER DEFAULT 0,
            blackjack_total_earned INTEGER DEFAULT 0,
            blackjack_largest_win INTEGER DEFAULT 0
        )''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS symbol_counts (
            user_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            count INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, symbol)
        )''')
        # target_id is a server ID (or a user ID for commands used outside a server)
        cursor.execute('''CREATE TABLE IF NOT EXISTS announcements_shown (
            target_id INTEGER PRIMARY KEY,
            announcement_id TEXT NOT NULL
        )''')
        # The newest changelog entry each player was told about (bot/changelog.py)
        cursor.execute('''CREATE TABLE IF NOT EXISTS changelog_seen (
            user_id INTEGER PRIMARY KEY,
            entry_id TEXT NOT NULL
        )''')

        # Display names are cached for the leaderboard, so it doesn't need Discord API calls.
        currency_columns = [row[1] for row in cursor.execute("PRAGMA table_info(currency)")]
        if "username" not in currency_columns:
            cursor.execute("ALTER TABLE currency ADD COLUMN username TEXT")
        if "daily_streak" not in currency_columns:
            cursor.execute("ALTER TABLE currency ADD COLUMN daily_streak INTEGER DEFAULT 0")
        # Only the hash that identifies the avatar on Discord's CDN, never the picture. NULL = not known yet.
        if "avatar_hash" not in currency_columns:
            cursor.execute("ALTER TABLE currency ADD COLUMN avatar_hash TEXT")
        if "last_bailout" not in currency_columns:
            cursor.execute("ALTER TABLE currency ADD COLUMN last_bailout TEXT")
        # /work: when the last shift started (ISO time, UTC) and how many shifts the player has done
        if "last_work" not in currency_columns:
            cursor.execute("ALTER TABLE currency ADD COLUMN last_work TEXT")
        if "work_shifts" not in currency_columns:
            cursor.execute("ALTER TABLE currency ADD COLUMN work_shifts INTEGER DEFAULT 0")
        # 0 = the player turned off the confirmation for bets over half their balance
        if "confirm_big_bets" not in currency_columns:
            cursor.execute("ALTER TABLE currency ADD COLUMN confirm_big_bets INTEGER DEFAULT 1")

        # ---- Statistics for the bot owner ----
        cursor.execute('''CREATE TABLE IF NOT EXISTS player_days (
            day TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            games INTEGER DEFAULT 0,
            PRIMARY KEY (day, user_id)
        )''')
        day_columns = [row[1] for row in cursor.execute("PRAGMA table_info(player_days)")]
        if "xp" not in day_columns:  # XP earned from games that day
            cursor.execute("ALTER TABLE player_days ADD COLUMN xp INTEGER DEFAULT 0")
        if "level_coins" not in day_columns:  # level-up rewards paid that day, for the daily limit
            cursor.execute("ALTER TABLE player_days ADD COLUMN level_coins INTEGER DEFAULT 0")
        cursor.execute('''CREATE TABLE IF NOT EXISTS coin_events (
            at TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            kind TEXT NOT NULL,
            amount INTEGER NOT NULL,
            detail TEXT
        )''')
        # Ideas and bug reports sent with /feedback, kept even if the DM to the owner fails
        cursor.execute('''CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            at TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            user_name TEXT,
            kind TEXT NOT NULL,
            place TEXT,
            message TEXT NOT NULL
        )''')
        # Challengers' bets held while a duel waits for an answer, so they can be refunded after a restart.
        cursor.execute('''CREATE TABLE IF NOT EXISTS pending_duels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            challenger_id INTEGER NOT NULL,
            opponent_id INTEGER NOT NULL,
            bet INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )''')

        # The clown symbol was removed from the slots.
        cursor.execute("DELETE FROM symbol_counts WHERE symbol = ?", ("\U0001f921",))

        # ---- Progression: XP, per-game stats and badges ----
        cursor.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'players'")
        players_is_new = cursor.fetchone() is None
        # veteran = played before per-game stats existed: first_played is unknown, so they never count as new players
        cursor.execute('''CREATE TABLE IF NOT EXISTS players (
            user_id INTEGER PRIMARY KEY,
            xp INTEGER DEFAULT 0,
            first_played TEXT,
            veteran INTEGER DEFAULT 0
        )''')
        # game is 'slots', 'coinflip' or 'blackjack'; net is total payout minus total bets
        cursor.execute('''CREATE TABLE IF NOT EXISTS game_stats (
            user_id INTEGER NOT NULL,
            game TEXT NOT NULL,
            games INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            net INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, game)
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS badges (
            user_id INTEGER NOT NULL,
            badge TEXT NOT NULL,
            earned_at TEXT NOT NULL,
            PRIMARY KEY (user_id, badge)
        )''')
        player_columns = [row[1] for row in cursor.execute("PRAGMA table_info(players)")]
        if "veteran" not in player_columns:
            cursor.execute("ALTER TABLE players ADD COLUMN veteran INTEGER DEFAULT 0")
            # Veterans either haven't played since (first_played is still empty), or their old stats hold more
            # games than game_stats, which only counts games since it was added. Blackjack pushes are missing
            # from the old stats, so blackjack is compared by wins and losses separately.
            cursor.execute("""
                UPDATE players SET veteran = 1
                WHERE first_played IS NULL
                   OR COALESCE((SELECT games_played FROM stats s WHERE s.user_id = players.user_id), 0)
                      > COALESCE((SELECT SUM(games) FROM game_stats g
                                  WHERE g.user_id = players.user_id AND g.game IN ('slots', 'coinflip')), 0)
                   OR EXISTS (
                      SELECT 1 FROM blackjack_stats b
                      LEFT JOIN game_stats g ON g.user_id = b.user_id AND g.game = 'blackjack'
                      WHERE b.user_id = players.user_id
                        AND (b.blackjack_wins > COALESCE(g.wins, 0)
                             OR b.blackjack_losses > COALESCE(g.games - g.wins, 0))
                   )
            """)
        if players_is_new:
            # Existing players keep their progress: XP is rebuilt from the stats recorded so far.
            cursor.execute("""
                INSERT INTO players (user_id, xp, veteran)
                SELECT user_id, SUM(games) * ? + SUM(wins) * ?, 1 FROM (
                    SELECT user_id, games_played AS games, wins FROM stats
                    UNION ALL
                    SELECT user_id, blackjack_wins + blackjack_losses, blackjack_wins FROM blackjack_stats
                ) GROUP BY user_id
            """, (XP_PER_GAME, XP_PER_WIN))
            # The only badge the old stats can prove: anyone with a recorded win already has "First Win".
            cursor.execute("""
                INSERT OR IGNORE INTO badges (user_id, badge, earned_at)
                SELECT user_id, 'first_win', date('now') FROM stats WHERE wins > 0
                UNION
                SELECT user_id, 'first_win', date('now') FROM blackjack_stats WHERE blackjack_wins > 0
            """)

        # Badges started paying coins on BADGE_REWARDS_SINCE. Players are paid once for the badges they
        # collected before that; `notified` turns 1 when they've been told about it.
        cursor.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'badge_backpay'")
        backpay_is_new = cursor.fetchone() is None
        cursor.execute('''CREATE TABLE IF NOT EXISTS badge_backpay (
            user_id INTEGER PRIMARY KEY,
            coins INTEGER NOT NULL,
            badges INTEGER NOT NULL,
            notified INTEGER DEFAULT 0
        )''')
        if backpay_is_new:
            owed: dict[int, list[int]] = {}
            for user_id, badge in cursor.execute("SELECT user_id, badge FROM badges WHERE earned_at < ?",
                                                 (BADGE_REWARDS_SINCE,)).fetchall():
                if badge in BADGE_RARITY:
                    owed.setdefault(user_id, []).append(badge_coins(badge))
            at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
            for user_id, rewards in owed.items():
                coins = sum(rewards)
                _ensure_account(cursor, user_id)
                cursor.execute("UPDATE currency SET balance = balance + ? WHERE user_id = ?", (coins, user_id))
                cursor.execute("INSERT INTO badge_backpay (user_id, coins, badges) VALUES (?, ?, ?)",
                               (user_id, coins, len(rewards)))
                if coins >= COIN_EVENT_MIN:
                    cursor.execute("INSERT INTO coin_events (at, user_id, kind, amount, detail) VALUES (?, ?, ?, ?, ?)",
                                   (at, user_id, "badges", coins, f"{len(rewards)} old badges"))

        # XP from games was capped at OLD_DAILY_XP_LIMIT a day for a few days. Players get back, once, the XP they
        # missed on the days they hit it; XP only, level-ups from it pay no coins. `notified` as above.
        cursor.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'xp_comeback'")
        comeback_is_new = cursor.fetchone() is None
        cursor.execute('''CREATE TABLE IF NOT EXISTS xp_comeback (
            user_id INTEGER PRIMARY KEY,
            xp INTEGER NOT NULL,
            notified INTEGER DEFAULT 0
        )''')
        if comeback_is_new:
            for user_id, xp in _missed_xp(cursor).items():
                cursor.execute("UPDATE players SET xp = xp + ? WHERE user_id = ?", (xp, user_id))
                cursor.execute("INSERT INTO xp_comeback (user_id, xp) VALUES (?, ?)", (user_id, xp))

        # Some badges pay more since the rebalance (OLD_BADGE_COINS). Players who already had them get the
        # difference once; rewards that went down aren't taken back. `notified` as above.
        cursor.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'badge_topup'")
        topup_is_new = cursor.fetchone() is None
        cursor.execute('''CREATE TABLE IF NOT EXISTS badge_topup (
            user_id INTEGER PRIMARY KEY,
            coins INTEGER NOT NULL,
            notified INTEGER DEFAULT 0
        )''')
        if topup_is_new:
            owed: dict[int, int] = {}
            for user_id, badge in cursor.execute(
                    f"SELECT user_id, badge FROM badges WHERE badge IN ({','.join('?' * len(OLD_BADGE_COINS))})",
                    list(OLD_BADGE_COINS)).fetchall():
                owed[user_id] = owed.get(user_id, 0) + max(0, badge_coins(badge) - OLD_BADGE_COINS[badge])
            at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
            for user_id, coins in owed.items():
                if not coins:
                    continue
                _ensure_account(cursor, user_id)
                cursor.execute("UPDATE currency SET balance = balance + ? WHERE user_id = ?", (coins, user_id))
                cursor.execute("INSERT INTO badge_topup (user_id, coins) VALUES (?, ?)", (user_id, coins))
                if coins >= COIN_EVENT_MIN:
                    cursor.execute("INSERT INTO coin_events (at, user_id, kind, amount, detail) VALUES (?, ?, ?, ?, ?)",
                                   (at, user_id, "badges", coins, "badge rewards raised"))


OLD_DAILY_XP_LIMIT = 1500


def _missed_xp(cursor) -> dict[int, int]:
    """
    XP each player missed while games' XP was capped: on every day they reached the cap, every game would have
    given 10 XP, plus 5 for a win. Wins per day weren't recorded, so they're estimated from the player's win rate.
    """
    win_rates = {user_id: wins / games for user_id, games, wins in cursor.execute(
        "SELECT user_id, SUM(games), SUM(wins) FROM game_stats GROUP BY user_id HAVING SUM(games) > 0").fetchall()}
    missed: dict[int, int] = {}
    for user_id, games, xp in cursor.execute(
            "SELECT user_id, games, xp FROM player_days WHERE xp >= ?", (OLD_DAILY_XP_LIMIT,)).fetchall():
        earned = games * XP_PER_GAME + round(games * win_rates.get(user_id, 0)) * XP_PER_WIN
        if earned > xp:
            missed[user_id] = missed.get(user_id, 0) + earned - xp
    return missed


def _ensure_account(cursor, user_id):
    cursor.execute("INSERT OR IGNORE INTO currency (user_id, balance) VALUES (?, ?)",
                   (user_id, STARTING_BALANCE))


# ============== Currency Operations ==============

def get_balance(user_id) -> int:
    """
    Get a user's balance. Read-only: users without an account have the starting balance,
    but an account is only created once their coins actually change (game, daily reward, transfer).
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM currency WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        return row[0] if row else STARTING_BALANCE


def try_debit(user_id, amount: int) -> bool:
    """Atomically subtract amount if the user can afford it. Returns True on success."""
    with get_connection() as conn:
        cursor = conn.cursor()
        _ensure_account(cursor, user_id)
        cursor.execute("UPDATE currency SET balance = balance - ? WHERE user_id = ? AND balance >= ?",
                       (amount, user_id, amount))
        return cursor.rowcount == 1


def credit(user_id, amount: int) -> int:
    """Atomically add amount to the user's balance. Returns the new balance."""
    with get_connection() as conn:
        cursor = conn.cursor()
        _ensure_account(cursor, user_id)
        cursor.execute("UPDATE currency SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        cursor.execute("SELECT balance FROM currency WHERE user_id = ?", (user_id,))
        return cursor.fetchone()[0]


def transfer(from_id, to_id, amount: int) -> bool:
    """Atomically move amount between two users. Returns False if the sender can't afford it."""
    with get_connection() as conn:
        cursor = conn.cursor()
        _ensure_account(cursor, from_id)
        _ensure_account(cursor, to_id)
        cursor.execute("UPDATE currency SET balance = balance - ? WHERE user_id = ? AND balance >= ?",
                       (amount, from_id, amount))
        if cursor.rowcount != 1:
            return False
        cursor.execute("UPDATE currency SET balance = balance + ? WHERE user_id = ?", (amount, to_id))
        return True


def set_balance(user_id, amount: int):
    """Set a user's balance to an exact value (admin use)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        _ensure_account(cursor, user_id)
        cursor.execute("UPDATE currency SET balance = ? WHERE user_id = ?", (amount, user_id))


def get_rank(user_id) -> int | None:
    """1-based leaderboard position (same ordering as get_leaderboard), or None if the user has no account."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM currency WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row is None:
            return None
        cursor.execute("SELECT COUNT(*) + 1 FROM currency WHERE balance > ? OR (balance = ? AND user_id < ?)",
                       (row[0], row[0], user_id))
        return cursor.fetchone()[0]


def get_player_count() -> int:
    """Number of players on the leaderboard (everyone with an account), so it matches get_rank."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM currency")
        return cursor.fetchone()[0]


_LEADERBOARD_COLUMNS = """
    SELECT c.user_id, c.balance, c.username, c.avatar_hash, COALESCE(p.xp, 0)
    FROM currency c LEFT JOIN players p ON p.user_id = c.user_id
"""


def get_leaderboard(limit: int = 5) -> list[tuple[int, int, str | None, str | None, int]]:
    """Top users by balance as (user_id, balance, username, avatar_hash, xp). Ties keep a stable order."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(_LEADERBOARD_COLUMNS + " ORDER BY c.balance DESC, c.user_id LIMIT ?", (limit,))
        return cursor.fetchall()


def get_leaderboard_row(user_id) -> tuple[int, int, str | None, str | None, int] | None:
    """The same row as get_leaderboard, for one user. None if they have no account."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(_LEADERBOARD_COLUMNS + " WHERE c.user_id = ?", (user_id,))
        return cursor.fetchone()


def save_username(user_id, username: str, avatar_hash: str | None = None) -> bool:
    """
    Store the user's display name and avatar hash ("" = no custom avatar, None = leave as is)
    if they have an account. Only writes when something changed. Returns False if there is no account yet.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT username, avatar_hash FROM currency WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row is None:
            return False
        new_hash = row[1] if avatar_hash is None else avatar_hash
        if (row[0], row[1]) != (username, new_hash):
            cursor.execute("UPDATE currency SET username = ?, avatar_hash = ? WHERE user_id = ?",
                           (username, new_hash, user_id))
        return True


def daily_reward_for(streak: int) -> int:
    """Reward for the given streak day (1-based); stays at the maximum after the last configured day."""
    return DAILY_STREAK_REWARDS[min(max(streak, 1), len(DAILY_STREAK_REWARDS)) - 1]


@dataclass
class DailyClaim:
    claimed: bool        # False if the reward was already claimed today
    balance: int
    streak: int          # current streak in days
    reward: int          # coins given now (0 if not claimed)
    next_reward: int     # reward for tomorrow if the streak continues
    seconds_left: int    # until the next reward becomes available (00:00 UTC)
    is_new: bool = False # the claim created the account (starting balance included)


def claim_daily_reward(user_id, now: datetime | None = None) -> DailyClaim:
    """
    Claim the daily reward (resets at 00:00 UTC). Claiming on consecutive days builds a streak
    with growing rewards (DAILY_STREAK_REWARDS); missing a day starts again from day 1.
    """
    now = now or datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    seconds_left = int((now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1) - now).total_seconds())

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT balance, last_claim_date, daily_streak FROM currency WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        is_new = row is None
        last_claim, old_streak = (row[1], row[2] or 0) if row else (None, 0)

        if last_claim == today:
            return DailyClaim(False, row[0], old_streak, 0, daily_reward_for(old_streak + 1), seconds_left)

        streak = old_streak + 1 if last_claim == yesterday else 1
        reward = daily_reward_for(streak)
        _ensure_account(cursor, user_id)
        # The date condition makes the claim atomic: of two simultaneous claims only one updates the row.
        cursor.execute("""
            UPDATE currency SET balance = balance + ?, last_claim_date = ?, daily_streak = ?
            WHERE user_id = ? AND (last_claim_date IS NULL OR last_claim_date != ?)
        """, (reward, today, streak, user_id, today))
        claimed = cursor.rowcount == 1

        cursor.execute("SELECT balance, daily_streak FROM currency WHERE user_id = ?", (user_id,))
        balance, current_streak = cursor.fetchone()

    if not claimed:
        return DailyClaim(False, balance, current_streak, 0, daily_reward_for(current_streak + 1), seconds_left)
    return DailyClaim(True, balance, streak, reward, daily_reward_for(streak + 1), seconds_left, is_new)


def get_daily_streak(user_id, now: datetime | None = None) -> int:
    """The user's active streak: kept if they claimed today or yesterday, otherwise 0."""
    now = now or datetime.now(timezone.utc)
    active_dates = (now.strftime("%Y-%m-%d"), (now - timedelta(days=1)).strftime("%Y-%m-%d"))
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT last_claim_date, daily_streak FROM currency WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
    return (row[1] or 0) if row and row[0] in active_dates else 0


def claim_bailout(user_id, now: datetime | None = None) -> tuple[str, int]:
    """
    Give BAILOUT_AMOUNT to a player with an empty balance, once per UTC day.
    Returns (status, balance): status is 'ok', 'has_coins' or 'already_claimed'.
    """
    today = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    with get_connection() as conn:
        cursor = conn.cursor()
        _ensure_account(cursor, user_id)
        # All the conditions are in one statement, so simultaneous claims can't both succeed.
        cursor.execute("""
            UPDATE currency SET balance = balance + ?, last_bailout = ?
            WHERE user_id = ? AND balance <= 0 AND (last_bailout IS NULL OR last_bailout != ?)
        """, (BAILOUT_AMOUNT, today, user_id, today))
        claimed = cursor.rowcount == 1
        cursor.execute("SELECT balance FROM currency WHERE user_id = ?", (user_id,))
        balance = cursor.fetchone()[0]
    if claimed:
        return "ok", balance
    return ("has_coins" if balance > 0 else "already_claimed"), balance


def start_work_shift(user_id, cooldown: int, now: datetime | None = None) -> tuple[bool, int, int]:
    """
    Start a /work shift if the last one was at least `cooldown` seconds ago.
    Returns (started, seconds until the next shift, shifts done including this one).
    """
    now = now or datetime.now(timezone.utc)
    earliest = (now - timedelta(seconds=cooldown)).isoformat(timespec="seconds")
    with get_connection() as conn:
        cursor = conn.cursor()
        _ensure_account(cursor, user_id)
        # The cooldown check and the update are one statement, so two shifts can't start at once.
        cursor.execute("""
            UPDATE currency SET last_work = ?, work_shifts = COALESCE(work_shifts, 0) + 1
            WHERE user_id = ? AND (last_work IS NULL OR last_work <= ?)
        """, (now.isoformat(timespec="seconds"), user_id, earliest))
        started = cursor.rowcount == 1
        last_work, shifts = cursor.execute("SELECT last_work, COALESCE(work_shifts, 0) FROM currency WHERE user_id = ?",
                                           (user_id,)).fetchone()
    if started:
        return True, cooldown, shifts
    left = cooldown - (now - datetime.fromisoformat(last_work)).total_seconds()
    return False, max(1, int(left)), shifts


def wants_bet_confirmation(user_id) -> bool:
    with get_connection() as conn:
        row = conn.execute("SELECT confirm_big_bets FROM currency WHERE user_id = ?", (user_id,)).fetchone()
    return row is None or row[0] != 0


def set_bet_confirmation(user_id, enabled: bool):
    with get_connection() as conn:
        cursor = conn.cursor()
        _ensure_account(cursor, user_id)
        cursor.execute("UPDATE currency SET confirm_big_bets = ? WHERE user_id = ?", (int(enabled), user_id))


def take_backpay_notice(user_id) -> tuple[int, int] | None:
    """(coins, badges) paid for the player's old badges if they haven't been told yet, and mark them as told."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE badge_backpay SET notified = 1 WHERE user_id = ? AND notified = 0", (user_id,))
        if cursor.rowcount != 1:
            return None
        return cursor.execute("SELECT coins, badges FROM badge_backpay WHERE user_id = ?", (user_id,)).fetchone()


def take_xp_comeback_notice(user_id) -> int | None:
    """The XP given back for the old daily XP limit if the player hasn't been told yet, and mark them as told."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE xp_comeback SET notified = 1 WHERE user_id = ? AND notified = 0", (user_id,))
        if cursor.rowcount != 1:
            return None
        return cursor.execute("SELECT xp FROM xp_comeback WHERE user_id = ?", (user_id,)).fetchone()[0]


def take_topup_notice(user_id) -> int | None:
    """The coins paid for badge rewards that went up if the player hasn't been told yet, and mark them as told."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE badge_topup SET notified = 1 WHERE user_id = ? AND notified = 0", (user_id,))
        if cursor.rowcount != 1:
            return None
        return cursor.execute("SELECT coins FROM badge_topup WHERE user_id = ?", (user_id,)).fetchone()[0]


def save_feedback(user_id, user_name: str, kind: str, place: str, message: str, cooldown: int,
                  now: datetime | None = None) -> int | None:
    """
    Store a /feedback message. Returns its number, or None if the player sent one less than `cooldown`
    seconds ago (nothing is stored then).
    """
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(seconds=cooldown)).isoformat(timespec="seconds")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM feedback WHERE user_id = ? AND at > ?", (user_id, since))
        if cursor.fetchone():
            return None
        cursor.execute("INSERT INTO feedback (at, user_id, user_name, kind, place, message) VALUES (?, ?, ?, ?, ?, ?)",
                       (now.isoformat(timespec="seconds"), user_id, user_name, kind, place, message))
        return cursor.lastrowid


def get_feedback(limit: int) -> list[tuple]:
    """The latest feedback, newest first: (id, at, user_id, user_name, kind, place, message)."""
    with get_connection() as conn:
        return conn.execute("SELECT id, at, user_id, user_name, kind, place, message FROM feedback "
                            "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


def mark_announcement_shown(target_id, announcement_id: str) -> bool:
    """Record that this announcement was shown to a server (or user). Returns True only the first time."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO announcements_shown (target_id, announcement_id) VALUES (?, ?)
            ON CONFLICT(target_id) DO UPDATE SET announcement_id = excluded.announcement_id
            WHERE announcement_id != excluded.announcement_id
        """, (target_id, announcement_id))
        return cursor.rowcount == 1


def get_changelog_seen(user_id) -> tuple[str | None, str | None, bool]:
    """(last changelog entry the player was told about, the day of their first game, veteran) for bot/changelog.py."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT entry_id FROM changelog_seen WHERE user_id = ?", (user_id,))
        seen = cursor.fetchone()
        cursor.execute("SELECT first_played, veteran FROM players WHERE user_id = ?", (user_id,))
        player = cursor.fetchone()
    return (seen[0] if seen else None, player[0] if player else None, bool(player[1]) if player else False)


def mark_changelog_seen(user_id, entry_id: str) -> bool:
    """Record the newest entry the player was told about. Returns True only if it changed (so they're told once)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO changelog_seen (user_id, entry_id) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET entry_id = excluded.entry_id
            WHERE entry_id != excluded.entry_id
        """, (user_id, entry_id))
        return cursor.rowcount == 1


# ============== Stats Operations ==============

def update_stats(user_id, payout: int, bet: int, final_grid=None):
    """
    Record a finished slots/coinflip round.
    payout is the total amount returned to the player (0 on a loss).
    A payout equal to the bet counts as a game played but neither a win nor a loss.
    """
    profit = max(0, payout - bet)
    win = payout > bet
    loss = payout < bet

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO stats (user_id, games_played, wins, losses, total_earned, largest_win)
            VALUES (?, 1, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                games_played = games_played + 1,
                wins = wins + excluded.wins,
                losses = losses + excluded.losses,
                total_earned = total_earned + excluded.total_earned,
                largest_win = MAX(largest_win, excluded.largest_win)
        """, (user_id, int(win), int(loss), profit, profit))

        if final_grid is not None:
            for row in final_grid:
                for symbol in row:
                    cursor.execute("""
                        INSERT INTO symbol_counts (user_id, symbol, count) VALUES (?, ?, 1)
                        ON CONFLICT(user_id, symbol) DO UPDATE SET count = count + 1
                    """, (user_id, symbol))


def update_blackjack_stats(user_id, profit: int, is_win: bool, is_push: bool = False):
    """Record a finished blackjack round. Pushes count as neither win nor loss."""
    wins = int(is_win)
    losses = int(not is_win and not is_push)
    earned = profit if is_win else 0

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO blackjack_stats (user_id, blackjack_wins, blackjack_losses, blackjack_total_earned, blackjack_largest_win)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                blackjack_wins = blackjack_wins + excluded.blackjack_wins,
                blackjack_losses = blackjack_losses + excluded.blackjack_losses,
                blackjack_total_earned = blackjack_total_earned + excluded.blackjack_total_earned,
                blackjack_largest_win = MAX(blackjack_largest_win, excluded.blackjack_largest_win)
        """, (user_id, wins, losses, earned, earned))


def get_user_profile(user_id) -> dict:
    """Get comprehensive user profile data."""
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT games_played, wins, losses, total_earned, largest_win FROM stats WHERE user_id = ?", (user_id,))
        stats_row = cursor.fetchone()

        cursor.execute("SELECT blackjack_wins, blackjack_losses, blackjack_total_earned, blackjack_largest_win FROM blackjack_stats WHERE user_id = ?", (user_id,))
        blackjack_row = cursor.fetchone()

        cursor.execute("SELECT balance FROM currency WHERE user_id = ?", (user_id,))
        balance_row = cursor.fetchone()

        cursor.execute("SELECT symbol FROM symbol_counts WHERE user_id = ? ORDER BY count DESC LIMIT 1", (user_id,))
        symbol_row = cursor.fetchone()

    return {
        "balance": balance_row[0] if balance_row else STARTING_BALANCE,
        "stats": stats_row,
        "blackjack": blackjack_row,
        "most_common_symbol": symbol_row[0] if symbol_row else None,
    }


# ============== Progression Operations ==============

def record_game_result(user_id, game: str, won: bool, net: int, xp_gain: int, today: str) -> tuple[int, int]:
    """
    Add a finished game to the player's per-game stats and XP.
    Returns (xp_before, xp_after).
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO players (user_id, xp, first_played) VALUES (?, 0, ?)", (user_id, today))
        cursor.execute("UPDATE players SET first_played = ? WHERE user_id = ? AND first_played IS NULL", (today, user_id))
        cursor.execute("SELECT xp FROM players WHERE user_id = ?", (user_id,))
        xp_before = cursor.fetchone()[0]
        cursor.execute("UPDATE players SET xp = xp + ? WHERE user_id = ?", (xp_gain, user_id))
        cursor.execute("""
            INSERT INTO game_stats (user_id, game, games, wins, net) VALUES (?, ?, 1, ?, ?)
            ON CONFLICT(user_id, game) DO UPDATE SET
                games = games + 1,
                wins = wins + excluded.wins,
                net = net + excluded.net
        """, (user_id, game, int(won), net))
        cursor.execute("""
            INSERT INTO player_days (day, user_id, games, xp) VALUES (?, ?, 1, ?)
            ON CONFLICT(day, user_id) DO UPDATE SET games = games + 1, xp = COALESCE(xp, 0) + excluded.xp
        """, (today, user_id, xp_gain))
    if game != "duel" and net >= COIN_EVENT_MIN:  # duels log themselves, with the opponent
        record_coin_event(user_id, game, net)
    return xp_before, xp_before + xp_gain


def claim_level_reward(user_id, today: str, amount: int, daily_limit: int) -> int:
    """
    Pay up to `amount` coins of level-up rewards, but no more than daily_limit in total today (UTC).
    Returns the coins actually paid.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO player_days (day, user_id, games) VALUES (?, ?, 0)", (today, user_id))
        cursor.execute("SELECT COALESCE(level_coins, 0) FROM player_days WHERE day = ? AND user_id = ?",
                       (today, user_id))
        paid = max(0, min(amount, daily_limit - cursor.fetchone()[0]))
        if paid:
            cursor.execute("UPDATE player_days SET level_coins = COALESCE(level_coins, 0) + ? WHERE day = ? AND user_id = ?",
                           (paid, today, user_id))
            _ensure_account(cursor, user_id)
            cursor.execute("UPDATE currency SET balance = balance + ? WHERE user_id = ?", (paid, user_id))
    return paid


def get_player_progress(user_id) -> tuple[int, str | None]:
    """(xp, first_played date as YYYY-MM-DD or None). Veterans' first game was before dates were recorded."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT xp, CASE WHEN veteran THEN NULL ELSE first_played END FROM players WHERE user_id = ?",
                       (user_id,))
        row = cursor.fetchone()
    return (row[0], row[1]) if row else (0, None)


def get_game_stats(user_id) -> dict[str, tuple[int, int, int]]:
    """Per-game stats recorded since progression was added: {game: (games, wins, net)}."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT game, games, wins, net FROM game_stats WHERE user_id = ?", (user_id,))
        return {game: (games, wins, net) for game, games, wins, net in cursor.fetchall()}


def award_badges(user_id, badge_ids: list[str], today: str) -> list[str]:
    """Give badges the user doesn't have yet. Returns only the newly earned ones, in the given order."""
    new = []
    with get_connection() as conn:
        cursor = conn.cursor()
        for badge_id in badge_ids:
            cursor.execute("INSERT OR IGNORE INTO badges (user_id, badge, earned_at) VALUES (?, ?, ?)",
                           (user_id, badge_id, today))
            if cursor.rowcount == 1:
                new.append(badge_id)
    return new


def get_badges(user_id) -> set[str]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT badge FROM badges WHERE user_id = ?", (user_id,))
        return {row[0] for row in cursor.fetchall()}


# ============== Owner Statistics ==============

def record_coin_event(user_id, kind: str, amount: int, detail: str = ""):
    """Log a big win or transfer. Small amounts are ignored to keep the table small."""
    if amount < COIN_EVENT_MIN:
        return
    with get_connection() as conn:
        conn.execute("INSERT INTO coin_events (at, user_id, kind, amount, detail) VALUES (?, ?, ?, ?, ?)",
                     (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"), user_id, kind, amount, detail))


# ============== Duel Operations ==============

def open_duel(challenger_id, opponent_id, bet: int) -> int | None:
    """Take the challenger's bet and hold it for the duel. Returns the duel ID, or None if they can't afford it."""
    with get_connection() as conn:
        cursor = conn.cursor()
        _ensure_account(cursor, challenger_id)
        cursor.execute("UPDATE currency SET balance = balance - ? WHERE user_id = ? AND balance >= ?",
                       (bet, challenger_id, bet))
        if cursor.rowcount != 1:
            return None
        cursor.execute("INSERT INTO pending_duels (challenger_id, opponent_id, bet, created_at) VALUES (?, ?, ?, ?)",
                       (challenger_id, opponent_id, bet, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")))
        return cursor.lastrowid


def accept_duel(duel_id: int, winner_id) -> tuple[str, int]:
    """
    Take the opponent's bet and pay both bets to the winner, in one transaction.
    Returns ("ok", winner's balance), ("no_coins", opponent's balance) or ("gone", 0) if the duel is already over.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        row = cursor.execute("SELECT challenger_id, opponent_id, bet FROM pending_duels WHERE id = ?", (duel_id,)).fetchone()
        if row is None:
            return "gone", 0
        _, opponent_id, bet = row
        _ensure_account(cursor, opponent_id)
        cursor.execute("UPDATE currency SET balance = balance - ? WHERE user_id = ? AND balance >= ?",
                       (bet, opponent_id, bet))
        if cursor.rowcount != 1:
            return "no_coins", cursor.execute("SELECT balance FROM currency WHERE user_id = ?", (opponent_id,)).fetchone()[0]
        cursor.execute("DELETE FROM pending_duels WHERE id = ?", (duel_id,))
        _ensure_account(cursor, winner_id)
        cursor.execute("UPDATE currency SET balance = balance + ? WHERE user_id = ?", (bet * 2, winner_id))
        return "ok", cursor.execute("SELECT balance FROM currency WHERE user_id = ?", (winner_id,)).fetchone()[0]


def refund_duel(duel_id: int) -> bool:
    """Give the challenger's bet back. Returns False if the duel was already accepted or refunded."""
    with get_connection() as conn:
        cursor = conn.cursor()
        row = cursor.execute("SELECT challenger_id, bet FROM pending_duels WHERE id = ?", (duel_id,)).fetchone()
        if row is None:
            return False
        cursor.execute("DELETE FROM pending_duels WHERE id = ?", (duel_id,))
        cursor.execute("UPDATE currency SET balance = balance + ? WHERE user_id = ?", (row[1], row[0]))
        return True


def refund_pending_duels() -> int:
    """Refund every duel still waiting for an answer. Called at startup, when no duel can be answered any more."""
    with get_connection() as conn:
        cursor = conn.cursor()
        rows = cursor.execute("SELECT challenger_id, bet FROM pending_duels").fetchall()
        for challenger_id, bet in rows:
            cursor.execute("UPDATE currency SET balance = balance + ? WHERE user_id = ?", (bet, challenger_id))
        cursor.execute("DELETE FROM pending_duels")
        return len(rows)


def get_bot_stats(now: datetime | None = None, days: int = 7) -> dict:
    """Numbers for /admin stats. Daily activity is only known from the day this table was added."""
    now = now or datetime.now(timezone.utc)
    day_names = [(now - timedelta(days=offset)).strftime("%Y-%m-%d") for offset in range(days)]
    with get_connection() as conn:
        cursor = conn.cursor()
        one = lambda query, *args: cursor.execute(query, args).fetchone()[0]  # noqa: E731

        per_day = []
        for day in day_names:
            per_day.append({
                "day": day,
                "active": one("SELECT COUNT(*) FROM player_days WHERE day = ?", day),
                "games": one("SELECT COALESCE(SUM(games), 0) FROM player_days WHERE day = ?", day),
                "new": one("SELECT COUNT(*) FROM players WHERE first_played = ? AND NOT veteran", day),
            })

        # Of the new players whose first game was at least a day ago (within the period), how many played on a later day?
        cohort = one("SELECT COUNT(*) FROM players WHERE first_played >= ? AND first_played < ? AND NOT veteran",
                     day_names[-1], day_names[0])
        returned = one("""
            SELECT COUNT(*) FROM players p
            WHERE p.first_played >= ? AND p.first_played < ? AND NOT p.veteran
              AND EXISTS (SELECT 1 FROM player_days d WHERE d.user_id = p.user_id AND d.day > p.first_played)
        """, day_names[-1], day_names[0])
        veterans_back = one("""
            SELECT COUNT(DISTINCT d.user_id) FROM player_days d JOIN players p ON p.user_id = d.user_id
            WHERE p.veteran AND d.day >= ?
        """, day_names[-1])

        return {
            "days": per_day,
            "accounts": one("SELECT COUNT(*) FROM currency"),
            "never_played": one("""
                SELECT COUNT(*) FROM currency c
                WHERE NOT EXISTS (SELECT 1 FROM players p WHERE p.user_id = c.user_id)
            """),
            "cohort": cohort,
            "returned": returned,
            "veterans_back": veterans_back,
            "games": cursor.execute(
                "SELECT game, SUM(games), COUNT(*), SUM(net) FROM game_stats GROUP BY game ORDER BY SUM(games) DESC"
            ).fetchall(),
            "events": cursor.execute("""
                SELECT e.at, e.user_id, c.username, e.kind, e.amount, e.detail
                FROM coin_events e LEFT JOIN currency c ON c.user_id = e.user_id
                ORDER BY e.amount DESC LIMIT 8
            """).fetchall(),
        }
