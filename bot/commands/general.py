"""
General commands for the BankRoll Discord Bot.
"""

import discord

from ..config import SLOT_PAYOUTS, DAILY_REWARD, MIN_BET, MAX_BET

TOS_URL = "https://gist.github.com/korolbbichey/ec9757512835365e37c3c8823d096ccb"


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
        f"Bets: {MIN_BET}–{MAX_BET} coins"
    ), inline=False)
    embed.add_field(name="💰 Economy", value=(
        "`/balance [user]` — check a balance\n"
        f"`/daily_reward` — claim 💰 {DAILY_REWARD} every day (resets 00:00 UTC)\n"
        "`/pay <user> <amount>` — send coins to a friend\n"
        "`/leaderboard` — richest players and your position\n"
        "`/profile [user]` — game statistics"
    ), inline=False)
    embed.add_field(name="🎰 Slot payouts (per line)", value="\n".join(
        f"{combo} — **{multiplier}x**" for combo, multiplier in SLOT_PAYOUTS.items()
    ), inline=False)
    embed.add_field(name="📜 Terms of Service", value=f"[Read here]({TOS_URL})", inline=False)
    return embed


def setup(client):
    """Setup general commands."""

    @client.tree.command(name="help", description="List all commands, slot payouts and the Terms of Service")
    async def help_command(interaction: discord.Interaction):
        await interaction.response.send_message(embed=build_help_embed(), ephemeral=True)
