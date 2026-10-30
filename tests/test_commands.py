import asyncio
from unittest.mock import AsyncMock

import discord
import pytest

import main
from bot.config import STARTING_BALANCE, ANNOUNCEMENT_ID

from bot.utils import BetTransformer

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
    assert names == ["badges", "balance", "blackjack", "coinflip", "daily_reward", "help", "leaderboard", "pay", "profile", "slots"]


def test_public_commands_support_user_install_everywhere(bot):
    """Discord payload: integration_types 0 = server install, 1 = user install;
    contexts 0 = server, 1 = DM with the bot, 2 = group DMs / other DMs."""
    for cmd in bot.tree.get_commands():
        payload = cmd.to_dict(bot.tree)
        assert sorted(payload["integration_types"]) == [0, 1], cmd.name
        assert sorted(payload["contexts"]) == [0, 1, 2], cmd.name


def test_admin_commands_stay_server_only(monkeypatch):
    monkeypatch.setattr(main.admin, "ADMIN_GUILD_ID", 123)

    async def build():
        client = main.BankRollBot()
        main.admin.setup(client)
        return client
    client = asyncio.run(build())
    assert client.tree.get_commands() == [], "admin commands are never global"
    group = client.tree.get_command("admin", guild=discord.Object(123))
    payload = group.to_dict(client.tree)
    assert payload["integration_types"] == [0] and payload["contexts"] == [0]


def test_bet_option_accepts_text_with_suggestions(bot):
    for name in ("slots", "blackjack", "coinflip"):
        bet = next(p for p in command(bot, name).parameters if p.name == "bet")
        assert bet.type == discord.AppCommandOptionType.string and bet.autocomplete, name


def test_bet_all_and_half(bot, db):
    """'all' / 'half' are resolved against the player's balance before the game starts."""
    db.set_balance(1, 300)

    async def go():
        bet = BetTransformer()
        assert await bet.transform(make_interaction(1), "half") == 150
        assert await bet.transform(make_interaction(1), "all") == 300
        assert await bet.transform(make_interaction(1), "1.5k") == 1500
    asyncio.run(go())


def test_bet_suggestions_show_amounts(bot, db):
    db.set_balance(1, 25_000)

    async def suggest(text):
        return [(c.name, c.value) for c in await BetTransformer().autocomplete(make_interaction(1), text)]

    async def go():
        assert await suggest("") == [("all — 10,000 coins", "all"), ("half — 10,000 coins", "half")]
        assert await suggest("h") == [("half — 10,000 coins", "half")]
        assert await suggest("2k") == [("2,000 coins", "2k")]
        assert await suggest("lots") == []
    asyncio.run(go())


def test_invalid_bet_gets_a_clear_message(bot):
    async def go():
        interaction = make_interaction(1, done=False)
        await bot.on_app_command_error(interaction, main.InvalidBet("❌ Bet must be a number, `all` or `half`."))
        args, kwargs = interaction.response.send_message.call_args
        assert args[0] == "❌ Bet must be a number, `all` or `half`." and kwargs["ephemeral"] is True
    asyncio.run(go())


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


def text_profile(bot, monkeypatch, interaction):
    """Run /profile with the image card failing, which falls back to the text embed."""
    def broken(*args):
        raise OSError("no font")
    monkeypatch.setattr(main.economy, "render_profile_card", broken)

    async def go():
        await command(bot, "profile").callback(interaction, None)
        return sent_embed(interaction.followup.send)
    return asyncio.run(go())


def test_profile_sends_an_image_card(bot, db):
    db.update_stats(1, 30, 10)

    async def go():
        interaction = make_interaction(1, done=False)
        await command(bot, "profile").callback(interaction, None)
        interaction.response.defer.assert_awaited()
        return interaction.followup.send.call_args.kwargs["file"]
    file = asyncio.run(go())
    assert file.filename == "profile.png"
    assert file.fp.read(8) == b"\x89PNG\r\n\x1a\n"


def test_profile_card_data_combines_all_games(bot, db, monkeypatch):
    db.set_balance(1, 2500)
    db.update_stats(1, 30, 10)
    db.update_stats(1, 0, 10)
    db.update_blackjack_stats(1, 50, True)
    db.claim_daily_reward(1)
    captured = {}

    def fake_render(data, avatar):
        captured["data"], captured["avatar"] = data, avatar
        return b"png"
    monkeypatch.setattr(main.economy, "render_profile_card", fake_render)

    async def go():
        interaction = make_interaction(1, user=make_user(1, global_name="Alice"))
        interaction.user.display_avatar.with_format.return_value.with_size.return_value.read = AsyncMock(return_value=b"avatar")
        await command(bot, "profile").callback(interaction, None)
    asyncio.run(go())
    data = captured["data"]
    assert captured["avatar"] == b"avatar"
    assert (data.name, data.games, data.win_rate, data.best_win, data.streak) == ("Alice", 3, "67%", 50, 1)
    assert data.balance == 2550 and data.rank == 1


def test_profile_card_works_without_an_avatar(bot, db):
    db.update_stats(1, 0, 10)

    async def go():
        interaction = make_interaction(1)
        read = interaction.user.display_avatar.with_format.return_value.with_size.return_value.read
        read.side_effect = discord.DiscordException("avatar unavailable")
        await command(bot, "profile").callback(interaction, None)
        return interaction.followup.send.call_args.kwargs["file"]
    assert asyncio.run(go()).filename == "profile.png"


def test_profile_falls_back_to_text(bot, db, monkeypatch):
    db.set_balance(1, 2500)
    db.update_stats(1, 30, 10, [["🍒"] * 3] * 3)
    db.update_blackjack_stats(1, 10, True)
    embed = text_profile(bot, monkeypatch, make_interaction(1, user=make_user(1, global_name="Alice")))
    assert embed.title == "🪙 Alice"
    assert embed.description.startswith("**Rookie** · Level 1\n")
    assert [f.name for f in embed.fields] == ["💰 Wallet", "🏅 Badges (0/13)", "📊 Stats"]
    assert "2,500" in embed.fields[0].value and "Rank #1" in embed.fields[0].value
    assert "None yet" in embed.fields[1].value and "🔒 Next:" in embed.fields[1].value
    assert "Lucky symbol 🍒" in embed.fields[2].value
    assert "**Blackjack** — 1 game ·" in embed.fields[2].value


def test_text_profile_shows_level_badges_and_favorite_game(bot, db, monkeypatch):
    from bot import progression
    db.set_balance(1, 500)
    for _ in range(8):  # 8 slot wins -> 8 * 15 = 120 XP -> level 2
        db.update_stats(1, 30, 10)
        progression.record_game(1, "slots", 10, 30)
    progression.record_game(1, "blackjack", 10, 20, natural=True)
    db.update_blackjack_stats(1, 10, True)
    embed = text_profile(bot, monkeypatch, make_interaction(1, user=make_user(1, global_name="Alice")))
    assert "Level 2" in embed.description and "35 / 200 XP" in embed.description
    assert embed.fields[1].name == "🏅 Badges (2/13)"
    assert "🍀 First Win" in embed.fields[1].value and "🃏 Natural 21" in embed.fields[1].value
    assert "Favorite game: **Slots**" in embed.fields[2].value
    assert "📅 Playing since" in embed.fields[2].value


def test_badges_command(bot, db):
    db.award_badges(1, ["first_win"], "2026-10-30")

    async def go():
        interaction = make_interaction(1, done=False, user=make_user(1, global_name="Alice"))
        await command(bot, "badges").callback(interaction, None)
        assert interaction.response.send_message.call_args.kwargs["ephemeral"] is True
        return sent_embed(interaction.response.send_message)
    embed = asyncio.run(go())
    assert embed.title == "🏅 Alice's badges — 1 / 13"
    assert "🍀 **First Win** — Win any game" in embed.description
    assert "🔒 **Explorer**" in embed.description


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


def test_announcement_via_user_install_is_private_and_per_user(bot):
    """In a server where only the player has the bot (User Install), the server isn't marked as announced."""
    async def completion(interaction):
        await bot.on_app_command_completion(interaction, None)
        return interaction.followup.send

    async def go():
        first = await completion(make_interaction(1, guild_id=500, guild_installed=False))
        assert first.await_count == 1 and first.call_args.kwargs["ephemeral"] is True
        assert (await completion(make_interaction(1, guild_id=500, guild_installed=False))).await_count == 0
        assert (await completion(make_interaction(2, guild_id=500, guild_installed=False))).await_count == 1
        public = await completion(make_interaction(3, guild_id=500))  # the server later installs the bot
        assert public.await_count == 1 and public.call_args.kwargs["ephemeral"] is False
    asyncio.run(go())


def test_daily_reward_command(bot, db):
    async def claim(user_id):
        interaction = make_interaction(user_id, done=False)
        await command(bot, "daily_reward").callback(interaction)
        return interaction.response.send_message

    async def go():
        first = await claim(1)
        embed = sent_embed(first)
        assert first.call_args.kwargs["ephemeral"] is True
        assert embed.title == "🎁 +50 coins!" and "Welcome" in embed.description
        assert [f.value for f in embed.fields] == ["1 day", "150"]
        assert "55 coins" in embed.footer.text

        again = sent_embed(await claim(1))
        assert again.title == "⏳ Already claimed today" and "55" in again.description
    asyncio.run(go())


def test_text_profile_shows_active_streak(bot, db, monkeypatch):
    db.claim_daily_reward(1)
    db.update_stats(1, 0, 10)
    embed = text_profile(bot, monkeypatch, make_interaction(1, done=False))
    assert "🔥 1 day streak" in embed.fields[0].value


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
    assert "1–10,000 coins, or `all` / `half`" in embed.fields[0].value
    assert "🍋🍋🍋 — **1x**" in embed.fields[2].value
    assert [f.name for f in embed.fields][-2:] == ["🌍 Play anywhere", "📜 Terms of Service"]
    assert "Add to My Apps" in embed.fields[-2].value


def test_announcement_embed():
    embed = main.general.build_announcement_embed()
    assert embed.title == "🆕 Bankroll Global Update!"
    assert [f.name for f in embed.fields] == ["🎰 New slots", "🃏 Blackjack", "💸 Economy", "🌍 Play anywhere", "✨ Fresh look"]
    assert "streak" in embed.fields[2].value
    assert "🍋 1x" in embed.fields[0].value and "💎 50x" in embed.fields[0].value
    assert discord.Color.gold() == embed.color
    assert len(embed) <= 6000, "within Discord's embed size limit"
