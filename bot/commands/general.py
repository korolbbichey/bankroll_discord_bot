"""
General commands for the BankRoll Discord Bot.
"""

from datetime import datetime

import discord

from ..config import AUTOPLAY_MAX_SPINS, BAILOUT_AMOUNT, SLOT_PAYOUTS, DAILY_STREAK_REWARDS, MIN_BET, MAX_BET
from ..utils import fmt
from ..changelog import CHANGELOG, UPDATES_SHOWN

TOS_URL = "https://gist.github.com/korolbbichey/ec9757512835365e37c3c8823d096ccb"

ROULETTE_PAYOUTS = (
    "🔴 Red / ⚫ Black · Odd / Even · 1-18 / 19-36 — **2x**\n"
    "1st / 2nd / 3rd 12 — **3x** · A single number 0-36 — **36x**"
)

PLAY_ANYWHERE = (
    "Add Bankroll to your profile and use it on any server or in DMs — "
    "open the bot's profile → **Add App** → **Add to My Apps**."
)


def build_help_embed() -> discord.Embed:
    embed = discord.Embed(
        title="📖 Bankroll — Commands",
        description="Casino games with virtual coins. No real money involved!",
        color=discord.Color.gold(),
    )
    embed.add_field(name="🎮 Games", value=(
        "`/slots <bet>` — 3x3 slot machine, every line pays\n"
        f"`/slots <bet> spins:20 stop_loss:100` — autoplay up to {AUTOPLAY_MAX_SPINS} spins\n"
        "`/blackjack <bet>` — Hit, Stand or Double down\n"
        "`/coinflip <guess> <bet>` — guess right to double your bet\n"
        "`/roulette <on> <bet>` — bet on a color, odd/even, a dozen or a number\n"
        "`/duel <user> <bet>` — challenge a friend, the winner takes both bets\n"
        f"`<bet>`: {fmt(MIN_BET)}–{fmt(MAX_BET)} coins, or `all` / `half` of your balance"
    ), inline=False)
    embed.add_field(name="💰 Economy", value=(
        "`/balance [user]` — check a balance\n"
        f"`/daily_reward` — 💰 {fmt(DAILY_STREAK_REWARDS[0])}–{fmt(DAILY_STREAK_REWARDS[-1])} daily, grows with a 🔥 streak\n"
        "`/work` — a quick casino job for coins, once an hour\n"
        f"`/bailout` — out of coins? Get 💰 {fmt(BAILOUT_AMOUNT)}, once a day\n"
        "`/pay <user> <amount>` — send coins to a friend\n"
        "`/leaderboard` — richest players and your position\n"
        "`/profile [user]` — player card: level, title and stats\n"
        "`/badges [user]` — every badge, how to earn it and the coins it pays\n"
        "`/updates` — what changed in the bot lately\n"
        "`/feedback` — send an idea or a bug report to the developer"
    ), inline=False)
    embed.add_field(name="🎰 Slot payouts (per line)", value="\n".join(
        f"{combo} — **{multiplier}x**" for combo, multiplier in SLOT_PAYOUTS.items()
    ), inline=False)
    embed.add_field(name="🎡 Roulette payouts", value=ROULETTE_PAYOUTS, inline=False)
    embed.add_field(name="🌍 Play anywhere", value=PLAY_ANYWHERE, inline=False)
    embed.add_field(name="📜 Terms of Service", value=f"[Read here]({TOS_URL})", inline=False)
    return embed


def build_announcement_embed() -> discord.Embed:
    """The one-time update announcement (see ANNOUNCEMENT_ID in config)."""
    embed = discord.Embed(
        title="🎡 Roulette is here!",
        description="A new game, new ways to play with friends and more badges to collect:",
        color=discord.Color.gold(),
    )
    embed.add_field(name="🎡 Roulette", value=(
        "`/roulette <on> <bet>` — an animated European wheel.\n" + ROULETTE_PAYOUTS
    ), inline=False)
    embed.add_field(name="⚔️ Duels", value=(
        "`/duel <user> <bet>` — challenge a friend to a coin flip, the winner takes both bets"
    ), inline=False)
    embed.add_field(name="💼 More ways to earn", value=(
        "`/work` — a quick casino job once an hour: serve drinks, count chips, catch cheaters. Get promoted for more pay\n"
        "🏅 Badges now pay coins (up to 1,500), and so does every level-up"
    ), inline=False)
    embed.add_field(name="🏅 8 new badges", value=(
        "⚔️ Duelist · 🥇 Champion · 🎯 Bullseye · 🟢 Green Zero · 💰 Jackpot · 🗺️ Grand Tour · 🎖️ Veteran · ⚡ Unstoppable\n"
        "`/badges` — see how to earn them all and what each pays"
    ), inline=False)
    embed.add_field(name="🔁 Slots autoplay", value=(
        "Faster spins, plus autoplay: press **Auto** or use `/slots <bet> spins:20 stop_loss:100`.\n"
        "It stops at your stop-loss, on a big win or when you press Stop."
    ), inline=False)
    embed.add_field(name="✨ Also new", value=(
        "🪙 A 3D coin with a real king and a laurel wreath on its sides\n"
        f"🛟 `/bailout` — out of coins? Get 💰 {fmt(BAILOUT_AMOUNT)} once a day\n"
        "🎮 Quick-play buttons under `/daily_reward`"
    ), inline=False)
    embed.set_footer(text="Start with /help • Thanks for all the ideas, keep them coming!")
    return embed


def build_updates_embed() -> discord.Embed:
    """The latest changelog entries, newest first."""
    embed = discord.Embed(title="📰 What's new in Bankroll", color=discord.Color.gold())
    for entry in CHANGELOG[:UPDATES_SHOWN]:
        day = datetime.strptime(entry.date, "%Y-%m-%d").strftime("%b %d").replace(" 0", " ")
        embed.add_field(name=f"{day} — {entry.title}", value="\n".join(f"• {line}" for line in entry.lines)[:1024],
                        inline=False)
    embed.set_footer(text="Ideas or bugs? Tell us, they shape the next update!")
    return embed


def setup(client):
    """Setup general commands."""

    @client.tree.command(name="updates", description="What changed in the bot lately")
    async def updates_command(interaction: discord.Interaction):
        await interaction.response.send_message(embed=build_updates_embed(), ephemeral=True)

    @client.tree.command(name="help", description="List all commands, slot payouts and the Terms of Service")
    async def help_command(interaction: discord.Interaction):
        await interaction.response.send_message(embed=build_help_embed(), ephemeral=True)
