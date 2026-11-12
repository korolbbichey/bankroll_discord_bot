import asyncio
from datetime import date

import pytest

import main
from bot import changelog
from bot.changelog import CHANGELOG, Entry, notice_text, unseen_entries
from bot.commands import general

from conftest import make_interaction

NEW = Entry("new", "2026-11-20", "New", ("🆕 new thing",))
OLD = Entry("old", "2026-11-10", "Old", ("🕰️ old thing",))
TOLD = Entry("told", "2026-11-05", "Big update", ("🎡 told in the announcement",), notify=False)


@pytest.fixture
def entries(monkeypatch):
    monkeypatch.setattr(changelog, "CHANGELOG", [NEW, OLD, TOLD])


def test_changelog_is_well_formed():
    ids = [entry.id for entry in CHANGELOG]
    assert len(set(ids)) == len(ids), "ids are unique"
    dates = [date.fromisoformat(entry.date) for entry in CHANGELOG]
    assert dates == sorted(dates, reverse=True), "newest first"
    assert all(entry.lines and entry.title for entry in CHANGELOG)


def test_only_entries_after_the_last_seen_one(entries):
    assert unseen_entries(None, "2026-11-01", False, "2026-11-20") == [NEW, OLD]
    assert unseen_entries("old", "2026-11-01", False, "2026-11-20") == [NEW]
    assert unseen_entries("new", "2026-11-01", False, "2026-11-20") == []
    assert unseen_entries("removed-id", "2026-11-01", False, "2026-11-20") == [NEW, OLD]


def test_new_players_hear_only_about_later_changes(entries):
    assert unseen_entries(None, "2026-11-15", False, "2026-11-20") == [NEW]
    assert unseen_entries(None, "2026-11-20", False, "2026-11-20") == [], "started on the day of the change"
    assert unseen_entries(None, None, False, "2026-11-20") == [], "hasn't played a game yet"
    assert unseen_entries(None, None, True, "2026-11-20") == [NEW, OLD], "veterans played before dates were kept"


def test_old_entries_are_not_sent(entries):
    assert unseen_entries(None, "2026-11-01", False, "2026-11-30") == [NEW], "OLD is more than 14 days old"


def test_notice_text(entries):
    text = notice_text([NEW, OLD])
    assert text.startswith("📰 **What's new in Bankroll**")
    assert "• 🆕 new thing\n• 🕰️ old thing" in text and text.endswith("`/updates`")
    many = Entry("many", "2026-11-20", "Many", tuple(f"line {n}" for n in range(11)))
    assert "line 7" in notice_text([many]) and "line 8" not in notice_text([many])
    assert "…and 3 more" in notice_text([many])


def told(db, user_id, today="2026-11-20", command="balance"):
    async def go():
        client = main.BankRollBot()
        interaction = make_interaction(user_id)
        interaction.command.name = command
        await client.maybe_tell_changes(interaction)
        return interaction.followup.send
    original = main.datetime

    class Today(original):
        @classmethod
        def now(cls, tz=None):
            return original.fromisoformat(today + "T12:00:00+00:00")
    main.datetime = Today
    try:
        return asyncio.run(go())
    finally:
        main.datetime = original


def test_players_are_told_once(db, entries):
    db.record_game_result(1, "slots", False, -10, 10, "2026-11-01")
    first = told(db, 1)
    assert first.await_count == 1 and first.call_args.kwargs["ephemeral"] is True
    assert "new thing" in first.call_args.args[0] and "old thing" in first.call_args.args[0]
    assert told(db, 1).await_count == 0, "only once"


def test_next_entry_is_told_alone(db, entries, monkeypatch):
    db.record_game_result(1, "slots", False, -10, 10, "2026-11-01")
    monkeypatch.setattr(changelog, "CHANGELOG", [OLD, TOLD])
    told(db, 1)
    monkeypatch.setattr(changelog, "CHANGELOG", [NEW, OLD, TOLD])
    later = told(db, 1)
    assert "new thing" in later.call_args.args[0] and "old thing" not in later.call_args.args[0]


def test_players_who_never_played_are_not_told(db, entries):
    assert told(db, 7).await_count == 0
    db.record_game_result(7, "slots", False, -10, 10, "2026-11-21")
    assert told(db, 7, today="2026-11-21").await_count == 0, "nothing changed since they started"


def test_not_told_after_updates_command(db, entries):
    db.record_game_result(1, "slots", False, -10, 10, "2026-11-01")
    assert told(db, 1, command="updates").await_count == 0
    assert told(db, 1).await_count == 1, "the next command still tells them"


def test_updates_command(db):
    async def go():
        client = main.BankRollBot()
        general.setup(client)
        interaction = make_interaction(1, done=False)
        await client.tree.get_command("updates").callback(interaction)
        return interaction.response.send_message.call_args
    call = asyncio.run(go())
    embed = call.kwargs["embed"]
    assert call.kwargs["ephemeral"] is True
    assert [field.name.split(" — ", 1)[1] for field in embed.fields] == [e.title for e in CHANGELOG[:5]], "newest first"
    newest = CHANGELOG[0]
    day = date.fromisoformat(newest.date)
    assert embed.fields[0].name == f"{day:%b} {day.day} — {newest.title}"
    assert embed.fields[0].value.startswith(f"• {newest.lines[0]}")
