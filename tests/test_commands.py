import asyncio
from unittest.mock import AsyncMock

import discord
import pytest

import main
from bot.config import STARTING_BALANCE, ANNOUNCEMENT_ID

from conftest import make_interaction, make_user, sent_embed


@pytest.fixture
def bot():
    """A bot with every command registered, never connected to Discord."""
    async def build():
        client = main.BankRollBot()
        for module in (main.economy, main.admin, main.general, main.slots, main.blackjack, main.coinflip):
            module.setup(client)
        return client
    return asyncio.run(build())


def command(bot, name):
    return bot.tree.get_command(name)


def test_public_commands_are_registered(bot):
    names = sorted(c.name for c in bot.tree.get_commands())
    assert names == ["balance", "blackjack", "coinflip", "daily_reward", "help", "leaderboard", "pay", "profile", "slots"]


def test_bet_options_have_discord_side_limits(bot):
    for name in ("slots", "blackjack", "coinflip"):
        bet = next(p for p in command(bot, name).parameters if p.name == "bet")
        assert (bet.min_value, bet.max_value) == (main.slots.MIN_BET, main.slots.MAX_BET)


def test_pay(bot, db):
    async def go():
        interaction = make_interaction(1)
        await command(bot, "pay").callback(interaction, make_user(2, global_name="Bob"), 30)
        assert db.get_balance(2) == STARTING_BALANCE + 30
        for target, amount, error in [(make_user(1), 5, "yourself"), (make_user(9, bot=True), 5, "bot"), (make_user(2), 10**6, "Not enough")]:
            interaction = make_interaction(1)
            await command(bot, "pay").callback(interaction, target, amount)
            assert error in interaction.response.send_message.call_args.args[0]
    asyncio.run(go())
    assert db.get_balance(1) == STARTING_BALANCE - 30
    assert db.get_leaderboard(1)[0][2] == "Bob", "the recipient's name is stored too"


def test_leaderboard_uses_stored_names_without_api_calls(bot, db):
    db.set_balance(1, 1_234_567)
    db.set_balance(2, 500)
    db.save_username(1, "Alice")
    db.save_username(2, "Bob_*")
    bot.fetch_user = AsyncMock(side_effect=AssertionError("must not call the Discord API"))

    async def go():
        interaction = make_interaction(2, done=False)
        await command(bot, "leaderboard").callback(interaction)
        return sent_embed(interaction.response.send_message)
    embed = asyncio.run(go())
    assert embed.description.splitlines() == ["🥇 **Alice** — 1,234,567 coins", "🥈 **Bob\\_\\*** — 500 coins"]
    assert "Your position: #2" in embed.footer.text


def test_leaderboard_fetches_and_stores_missing_names(bot, db):
    db.set_balance(5, 900)
    bot.fetch_user = AsyncMock(return_value=make_user(5, global_name="Fetched"))

    async def go():
        interaction = make_interaction(1, done=False)
        await command(bot, "leaderboard").callback(interaction)
        interaction.response.defer.assert_awaited()
        return sent_embed(interaction.followup.send)
    assert "Fetched" in asyncio.run(go()).description
    assert db.get_leaderboard(1)[0][2] == "Fetched"


def test_profile_embed(bot, db):
    db.set_balance(1, 2500)
    db.update_stats(1, 30, 10, [["🍒"] * 3] * 3)
    db.update_blackjack_stats(1, 10, True)

    async def go():
        interaction = make_interaction(1, user=make_user(1, global_name="Alice"))
        await command(bot, "profile").callback(interaction, None)
        return sent_embed(interaction.response.send_message)
    embed = asyncio.run(go())
    assert embed.title == "🎮 Alice's profile"
    assert [f.name for f in embed.fields] == ["💰 Balance", "🎰 Slots & Coinflip", "🃏 Blackjack"]
    assert "2,500" in embed.fields[0].value and "Rank #1" in embed.fields[0].value
    assert "Favorite symbol: 🍒" in embed.fields[1].value


def test_announcement_once_per_server(bot):
    async def completion(interaction):
        await bot.on_app_command_completion(interaction, None)
        return interaction.followup.send

    async def go():
        first = await completion(make_interaction(1, guild_id=100))
        assert first.await_count == 1 and first.call_args.kwargs["ephemeral"] is False
        assert (await completion(make_interaction(2, guild_id=100))).await_count == 0
        assert (await completion(make_interaction(1, guild_id=200))).await_count == 1
        dm = await completion(make_interaction(3, guild_id=None))
        assert dm.call_args.kwargs["ephemeral"] is True
        assert (await completion(make_interaction(4, guild_id=300, done=False))).await_count == 0
    asyncio.run(go())
    assert ANNOUNCEMENT_ID


def test_names_are_remembered_after_commands(bot, db):
    db.credit(1, 0)
    user = make_user(1, global_name="First")

    async def go():
        await bot.on_app_command_completion(make_interaction(user=user, guild_id=None), None)
        user.global_name = "Second"
        await bot.on_app_command_completion(make_interaction(user=user, guild_id=None), None)
    asyncio.run(go())
    assert db.get_leaderboard(1)[0][2] == "Second"
    assert bot.known_names[1] == "Second"


def test_help_embed_lists_payouts(bot):
    async def go():
        interaction = make_interaction(1)
        await command(bot, "help").callback(interaction)
        return sent_embed(interaction.response.send_message)
    embed = asyncio.run(go())
    assert "Bets: 1–10,000 coins" in embed.fields[0].value
    assert "🍋🍋🍋 — **1x**" in embed.fields[2].value


def test_announcement_embed():
    embed = main.general.build_announcement_embed()
    assert embed.title == "🆕 Bankroll Global Update!"
    assert [f.name for f in embed.fields] == ["🎰 New slots", "🃏 Blackjack", "💸 Economy", "✨ Fresh look"]
    assert "🍋 1x" in embed.fields[0].value and "💎 50x" in embed.fields[0].value
    assert discord.Color.gold() == embed.color
    assert len(embed) <= 6000, "within Discord's embed size limit"
