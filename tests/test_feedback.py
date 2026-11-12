import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

import main
from bot.commands import feedback

from conftest import make_interaction, make_user, sent_embed

IDEA = SimpleNamespace(value="idea", name="💡 Idea")
BUG = SimpleNamespace(value="bug", name="🐞 Bug")


@pytest.fixture
def owner(monkeypatch):
    """The bot owner (id 42), whose DMs are recorded."""
    user = make_user(42)
    user.send = AsyncMock()

    async def owner_ids(client):
        return {42}
    monkeypatch.setattr(feedback, "owner_ids", owner_ids)
    return user


def send(interaction, kind, message, owner):
    async def go():
        client = main.BankRollBot()
        client.get_user = lambda user_id: owner if user_id == owner.id else None
        feedback.setup(client)
        await client.tree.get_command("feedback").callback(interaction, kind, message)
    asyncio.run(go())


def from_server(user_id=1):
    interaction = make_interaction(user_id, done=False)
    interaction.guild.name = "Taru's Casino"
    return interaction


def test_feedback_reaches_the_owner(db, owner):
    interaction = from_server()
    send(interaction, IDEA, "Add poker please", owner)
    reply = interaction.response.send_message.call_args
    assert "sent to the developer" in reply.args[0] and reply.kwargs["ephemeral"] is True
    embed = owner.send.call_args.kwargs["embed"]
    assert embed.title == "💡 Idea #1" and embed.description == "Add poker please"
    fields = {f.name: f.value for f in embed.fields}
    assert fields == {"From": "user1 (`1`)", "Where": "Taru's Casino"}


def test_feedback_is_saved_even_if_the_dm_fails(db, owner):
    owner.send.side_effect = discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "Cannot send")
    interaction = from_server()
    send(interaction, BUG, "The wheel froze", owner)
    assert "sent to the developer" in interaction.response.send_message.call_args.args[0]
    (number, _, user_id, name, kind, place, message), = db.get_feedback(10)
    assert (number, user_id, name, kind, place, message) == (1, 1, "user1", "bug", "Taru's Casino", "The wheel froze")


def test_one_message_every_few_minutes(db, owner):
    send(from_server(), IDEA, "First idea", owner)
    second = from_server()
    send(second, IDEA, "Second idea", owner)
    assert "few minutes" in second.response.send_message.call_args.args[0]
    assert owner.send.await_count == 1 and len(db.get_feedback(10)) == 1
    send(from_server(user_id=2), IDEA, "Someone else", owner)
    assert owner.send.await_count == 2, "the limit is per player"


def test_cooldown_ends(db):
    now = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)
    assert db.save_feedback(1, "a", "idea", "DMs", "one", 300, now=now) == 1
    assert db.save_feedback(1, "a", "idea", "DMs", "two", 300, now=now + timedelta(minutes=4)) is None
    assert db.save_feedback(1, "a", "idea", "DMs", "two", 300, now=now + timedelta(minutes=6)) == 2


def test_place_of_dms_and_user_installs():
    dm = make_interaction(guild_id=None)
    dm.guild = None
    assert feedback.place_of(dm) == "DMs"
    elsewhere = make_interaction(guild_id=555)
    elsewhere.guild = None
    assert feedback.place_of(elsewhere) == "a server without the bot (555)"


def test_admin_feedback_lists_the_latest(db, monkeypatch):
    monkeypatch.setattr(main.admin, "ADMIN_GUILD_ID", 123)
    db.save_feedback(1, "Alice", "idea", "DMs", "Add poker", 300)
    db.save_feedback(2, "Bob", "bug", "Taru's Casino", "Wheel froze", 300)

    async def go():
        client = main.BankRollBot()
        main.admin.setup(client)
        group = client.tree.get_command("admin", guild=discord.Object(123))
        interaction = make_interaction(42, done=False)
        await group.get_command("feedback").callback(interaction)
        return sent_embed(interaction.response.send_message)
    embed = asyncio.run(go())
    assert embed.fields[0].name.startswith("🐞 Bug #2") and embed.fields[0].name.endswith("Bob")
    assert "Wheel froze" in embed.fields[0].value and "Taru's Casino" in embed.fields[0].value
    assert embed.fields[1].name.startswith("💡 Idea #1")
