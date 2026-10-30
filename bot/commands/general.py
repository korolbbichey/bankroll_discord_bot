"""
General commands for the BankRoll Discord Bot.
"""

import discord

from ..config import SLOT_PAYOUTS, DAILY_STREAK_REWARDS, MIN_BET, MAX_BET
from ..utils import fmt

TOS_URL = "https://gist.github.com/korolbbichey/ec9757512835365e37c3c8823d096ccb"

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
        "`/blackjack <bet>` — Hit, Stand or Double down\n"
        "`/coinflip <guess> <bet>` — guess right to double your bet\n"
        f"`<bet>`: {fmt(MIN_BET)}–{fmt(MAX_BET)} coins, or `all` / `half` of your balance"
    ), inline=False)
    embed.add_field(name="💰 Economy", value=(
        "`/balance [user]` — check a balance\n"
        f"`/daily_reward` — 💰 {fmt(DAILY_STREAK_REWARDS[0])}–{fmt(DAILY_STREAK_REWARDS[-1])} daily, grows with a 🔥 streak\n"
        "`/pay <user> <amount>` — send coins to a friend\n"
        "`/leaderboard` — richest players and your position\n"
        "`/profile [user]` — level, title, badges and stats"
    ), inline=False)
    embed.add_field(name="🎰 Slot payouts (per line)", value="\n".join(
        f"{combo} — **{multiplier}x**" for combo, multiplier in SLOT_PAYOUTS.items()
    ), inline=False)
    embed.add_field(name="🌍 Play anywhere", value=PLAY_ANYWHERE, inline=False)
    embed.add_field(name="📜 Terms of Service", value=f"[Read here]({TOS_URL})", inline=False)
    return embed


def build_announcement_embed() -> discord.Embed:
    """The one-time update announcement (see ANNOUNCEMENT_ID in config)."""
    embed = discord.Embed(
        title="🆕 Bankroll Global Update!",
        description="Bankroll just got a big upgrade — here's what's new:",
        color=discord.Color.gold(),
    )
    payouts = " · ".join(f"{combo[0]} {multiplier}x" for combo, multiplier in SLOT_PAYOUTS.items())
    embed.add_field(name="🎰 New slots", value=(
        "No more clowns, and **every line pays** — rows, columns and diagonals.\n"
        f"{payouts}\n"
        "Results now show exactly which lines won."
    ), inline=False)
    embed.add_field(name="🃏 Blackjack", value="New **Double down** button, and blackjack pays 3:2.", inline=False)
    embed.add_field(name="💸 Economy", value=(
        "`/pay` — send coins to friends\n"
        f"`/daily_reward` — 🔥 daily streaks: claim every day for up to **{fmt(DAILY_STREAK_REWARDS[-1])}** coins"
    ), inline=False)
    embed.add_field(name="🌍 Play anywhere", value=PLAY_ANYWHERE, inline=False)
    embed.add_field(name="✨ Fresh look", value="Redesigned `/leaderboard` and `/profile`, and a fairer, more stable bot.", inline=False)
    embed.set_footer(text="Start with /help • Have fun!")
    return embed


def setup(client):
    """Setup general commands."""

    @client.tree.command(name="help", description="List all commands, slot payouts and the Terms of Service")
    async def help_command(interaction: discord.Interaction):
        await interaction.response.send_message(embed=build_help_embed(), ephemeral=True)
