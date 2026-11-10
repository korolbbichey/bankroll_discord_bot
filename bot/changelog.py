"""
What changed in the bot, for players.

Every player-facing change gets an entry here in the same commit. After the deploy each player is told about
new entries once, privately, after their next command (see main.py), and /updates lists the latest ones.
Big updates also have their own public announcement (ANNOUNCEMENT_ID in config).
"""

from dataclasses import dataclass
from datetime import date

NOTICE_DAYS = 14   # older entries are only in /updates, not sent to players coming back after a long break
NOTICE_MAX_LINES = 8
UPDATES_SHOWN = 5


@dataclass(frozen=True)
class Entry:
    id: str            # unique and never changed: players' "seen" marks point at it
    date: str          # YYYY-MM-DD (UTC)
    title: str
    lines: tuple[str, ...]
    notify: bool = True  # False when players were already told another way (a big update's announcement)


# Newest first.
CHANGELOG: list[Entry] = [
    Entry("2026-11-10-badges", "2026-11-10", "Badge rewards rebalanced", (
        "💯 **Full House** now pays **10,000** coins",
        "💸 Big Spender and 🔥 On Fire now pay 500",
        "🌱 New badge **Warming Up**: claim the daily reward 3 days in a row (150)",
        "💰 Jackpot is now for a 25x win in slots",
        "🎯 Bullseye, 🟢 Green Zero and 🥇 Champion pay 150, ⚔️ Duelist 50",
        "Had a badge that pays more now? You got the difference. Nothing was taken back. Full list: `/badges`",
    )),
    Entry("2026-11-10-levels", "2026-11-10", "Level up as much as you play", (
        "📈 No more daily XP limit: every game counts toward your level again",
        "🎁 Level-up rewards are limited to 1,000 coins a day instead. Badge rewards have no limit",
    )),
    Entry("2026-11-10-autoplay", "2026-11-10", "Smoother autoplay", (
        "🔁 Autoplay plays each spin's animation once: the numbers update together with the next spin",
        "🎰 Slots, roulette and coinflip no longer replay the animation when the result appears",
    )),
    Entry("2026-11-09-bets", "2026-11-09", "Bigger bets and a new badge", (
        "💰 Max bet is now **100,000**",
        "💯 New legendary badge **Full House**: fill the whole slot grid with one symbol",
        "💸 **Big Spender** is now for any bet of 10,000 or more",
        "📊 XP from games is limited to 1,500 a day (UTC); you can keep playing after that",
        "🔁 Up to 3 autoplays at once, and level-up messages no longer repeat",
    )),
    Entry("2026-11-06-roulette", "2026-11-06", "Roulette is here!", (
        "🎡 `/roulette`: an animated European wheel",
        "💼 `/work` once an hour, and badges and level-ups pay coins",
        "🏅 8 new badges, 🔁 slots autoplay and a 3D coin",
    ), notify=False),
]


def _days_between(earlier: str, later: str) -> int:
    return (date.fromisoformat(later) - date.fromisoformat(earlier)).days


def unseen_entries(last_seen: str | None, first_played: str | None, veteran: bool, today: str) -> list[Entry]:
    """
    Entries to tell a player about: newer than the last one they were told about, recent, and from after they
    started playing (a new player doesn't need to hear what changed before they came).
    """
    ids = [entry.id for entry in CHANGELOG]
    newer = CHANGELOG[:ids.index(last_seen)] if last_seen in ids else CHANGELOG
    entries = [e for e in newer if e.notify and _days_between(e.date, today) <= NOTICE_DAYS]
    if not veteran:
        if first_played is None:  # hasn't played a game yet
            return []
        entries = [e for e in entries if first_played < e.date]
    return entries


def notice_text(entries: list[Entry]) -> str:
    """One private message for every entry the player missed."""
    lines = [line for entry in entries for line in entry.lines]
    shown = lines[:NOTICE_MAX_LINES]
    more = len(lines) - len(shown)
    text = "📰 **What's new in Bankroll**\n" + "\n".join(f"• {line}" for line in shown)
    if more:
        text += f"\n…and {more} more"
    return text + "\nAll changes: `/updates`"


def latest_id() -> str:
    return CHANGELOG[0].id
