"""
Admin commands for the BankRoll Discord Bot.

Balances are global across every server the bot is in, so these commands are
restricted to the bot owner(s), not to server administrators. They are only
registered in ADMIN_GUILD_ID, so nobody else even sees them.
"""

import logging

import discord
from discord import app_commands

from ..config import OWNER_IDS, ADMIN_GUILD_ID
from ..database import credit, try_debit, get_balance, get_bot_stats, get_feedback, set_balance
from .feedback import KINDS
from .work import rank_for
from ..progression import BADGES, BADGES_BY_ID, level_for_xp, record_badges
from ..utils import fmt

logger = logging.getLogger(__name__)

Amount = app_commands.Range[int, 1, 1_000_000_000]


def setup(client):
    """Setup admin commands."""
    if ADMIN_GUILD_ID is None:
        logger.warning("ADMIN_GUILD_ID is not set, /admin commands are disabled.")
        return

    admin = app_commands.Group(
        name="admin",
        description="Bot owner tools",
        guild_ids=[ADMIN_GUILD_ID],
        default_permissions=discord.Permissions(administrator=True),
        # Never available through User Install or in DMs, unlike the public commands.
        allowed_installs=app_commands.AppInstallationType(guild=True, user=False),
        allowed_contexts=app_commands.AppCommandContext(guild=True, dm_channel=False, private_channel=False),
    )

    @admin.command(name="give", description="Add coins to a player")
    @app_commands.describe(user="Player", amount="Amount to add")
    async def give(interaction: discord.Interaction, user: discord.User, amount: Amount):
        new_balance = credit(user.id, amount)
        logger.info("%s gave %d to %s", interaction.user, amount, user.id)
        await interaction.response.send_message(f"✅ Gave 💰 {fmt(amount)} to {user.mention}. New balance: 💰 {fmt(new_balance)}", ephemeral=True)

    @admin.command(name="take", description="Remove coins from a player")
    @app_commands.describe(user="Player", amount="Amount to remove")
    async def take(interaction: discord.Interaction, user: discord.User, amount: Amount):
        if not try_debit(user.id, amount):
            await interaction.response.send_message(f"❌ {user.mention} only has 💰 {fmt(get_balance(user.id))}.", ephemeral=True)
            return
        logger.info("%s took %d from %s", interaction.user, amount, user.id)
        await interaction.response.send_message(f"✅ Took 💰 {fmt(amount)} from {user.mention}. New balance: 💰 {fmt(get_balance(user.id))}", ephemeral=True)

    @admin.command(name="set", description="Set a player's balance to an exact amount")
    @app_commands.describe(user="Player", amount="New balance")
    async def set_(interaction: discord.Interaction, user: discord.User, amount: app_commands.Range[int, 0, 1_000_000_000]):
        set_balance(user.id, amount)
        logger.info("%s set balance of %s to %d", interaction.user, user.id, amount)
        await interaction.response.send_message(f"✅ {user.mention}'s balance is now 💰 {fmt(amount)}", ephemeral=True)

    async def badge_choices(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        text = current.lower()
        return [app_commands.Choice(name=f"{b.emoji} {b.name} — {b.description}"[:100], value=b.id)
                for b in BADGES if text in b.name.lower() or text in b.id][:25]

    @admin.command(name="badge", description="Give a player a badge they earned but didn't get (pays its reward)")
    @app_commands.describe(user="Player", badge="Badge to give")
    @app_commands.autocomplete(badge=badge_choices)
    async def give_badge(interaction: discord.Interaction, user: discord.User, badge: str):
        if badge not in BADGES_BY_ID:
            await interaction.response.send_message("❌ No such badge. Pick one from the list.", ephemeral=True)
            return
        found = BADGES_BY_ID[badge]
        progress = record_badges(user.id, [badge])
        if not progress.new_badges:
            await interaction.response.send_message(f"ℹ️ {user.mention} already has {found.emoji} {found.name}.",
                                                    ephemeral=True)
            return
        logger.info("%s gave badge %s to %s", interaction.user, badge, user.id)
        await interaction.response.send_message(
            f"✅ Gave {found.emoji} **{found.name}** to {user.mention} with its reward of 💰 {fmt(progress.coins)}. "
            f"New balance: 💰 {fmt(get_balance(user.id))}", ephemeral=True)

    @admin.command(name="stats", description="Players, retention, popular games and the biggest coin movements")
    async def stats(interaction: discord.Interaction):
        data = get_bot_stats()
        embed = discord.Embed(title="📊 Bankroll stats", color=discord.Color.blurple())

        rate = f"{data['returned'] / data['cohort'] * 100:.0f}%" if data["cohort"] else "—"
        embed.add_field(name="👥 Players", value=(
            f"Accounts: **{fmt(data['accounts'])}**\n"
            f"Never played a game: **{fmt(data['never_played'])}**\n"
            f"New players who came back later: **{rate}** ({data['returned']} of {data['cohort']}, last 7 days)\n"
            f"Old players who played this week: **{fmt(data['veterans_back'])}**"
        ), inline=False)

        embed.add_field(name="📅 Last 7 days (UTC)", value="\n".join(
            f"`{d['day'][5:]}` new **{d['new']}** · active **{d['active']}** · games **{fmt(d['games'])}**"
            f" · bets **{fmt(d['wagered'])}** · house {-d['net']:+,}"
            for d in data["days"]
        ), inline=False)

        top_levels = "\n".join(
            f"Lv **{level_for_xp(xp)}** — {name or user_id} ({fmt(xp)} XP)" for user_id, name, xp in data["top_xp"]
        ) or "Nobody yet"
        top_work = "\n".join(
            f"**{rank_for(shifts)[0]}** — {name or user_id} ({fmt(shifts)} shifts)"
            for user_id, name, shifts in data["top_shifts"]
        ) or "Nobody yet"
        embed.add_field(name="🏆 Highest levels", value=top_levels, inline=True)
        embed.add_field(name="💼 Highest /work ranks", value=top_work, inline=True)

        embed.add_field(name="🎮 Games, all time", value="\n".join(
            f"{game}: **{fmt(total)}** games · {fmt(players)} players · players' net {net:+,}"
            for game, total, players, net in data["games"]
        ) or "No data yet", inline=False)

        embed.add_field(name="💰 Biggest coin movements", value="\n".join(
            f"`{at[5:]}` {name or user_id} — {kind} **+{fmt(amount)}**" + (f" ({detail})" if detail else "")
            for at, user_id, name, kind, amount, detail in data["events"]
        ) or "None logged yet", inline=False)
        embed.set_footer(text="Bets = coins wagered (turnover), house = what the bot won from players that day. "
                              "Bets are counted from Nov 14 onward.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @admin.command(name="feedback", description="The latest ideas and bug reports from /feedback")
    async def feedback_list(interaction: discord.Interaction):
        rows = get_feedback(10)
        embed = discord.Embed(title="📬 Latest feedback", color=discord.Color.blurple())
        for number, at, user_id, name, kind, place, message in rows:
            embed.add_field(name=f"{KINDS.get(kind, kind)} #{number} · {at[5:16].replace('T', ' ')} · {name or user_id}",
                            value=f"{message[:900]}\n*`{user_id}` · {place}*", inline=False)
        if not rows:
            embed.description = "No feedback yet."
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def owner_only(interaction: discord.Interaction) -> bool:
        # A False result raises CheckFailure, which the tree error handler reports to the user.
        return interaction.user.id in OWNER_IDS or await client.is_owner(interaction.user)

    admin.interaction_check = owner_only
    client.tree.add_command(admin)
