"""
/vote for the BankRoll Discord Bot: coins for voting for the bot on top.gg.

A player votes on the site (once every 12 hours), then uses /vote: the bot asks top.gg for their latest vote
and pays for it once. No webhook, so no public address is needed. TOPGG_TOKEN is the bot's token from
top.gg (bot settings → Integrations & API); without it /vote only shows the link.
The bot also keeps its server count up to date on top.gg, which needs the token's Write permission.
"""

import asyncio
import logging
import os
from datetime import datetime

import aiohttp
import discord

from ..config import VOTE_REWARD
from ..database import claim_vote_reward
from ..utils import fmt

logger = logging.getLogger(__name__)

API = "https://top.gg/api/v1/projects/@me/votes/{user_id}?source=discord"
METRICS_API = "https://top.gg/api/v1/projects/@me/metrics"
TIMEOUT = aiohttp.ClientTimeout(total=10)
POST_EVERY = 30 * 60  # seconds between server count updates on top.gg


class TopggError(Exception):
    """Top.gg didn't answer properly."""


async def latest_vote(user_id: int, token: str) -> dict | None:
    """The player's active vote ({created_at, expires_at, weight}), or None if they haven't voted in the last 12 hours."""
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(API.format(user_id=user_id), headers={"Authorization": f"Bearer {token}"}) as reply:
                if reply.status == 404:
                    return None
                if reply.status != 200:
                    raise TopggError(f"status {reply.status}")
                return await reply.json()
    except (aiohttp.ClientError, TimeoutError, ValueError) as error:
        raise TopggError(str(error)) from error


async def post_server_count(count: int, token: str) -> int:
    """Tell top.gg how many servers the bot is in. Returns the HTTP status (204 = done)."""
    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        async with session.patch(METRICS_API, json={"server_count": count},
                                 headers={"Authorization": f"Bearer {token}"}) as reply:
            return reply.status


async def keep_server_count_posted(client):
    """Background task: post the server count on top.gg after startup and then whenever it changes."""
    await client.wait_until_ready()
    posted = None
    while True:
        token = os.getenv("TOPGG_TOKEN")
        count = len(client.guilds)
        if token and count != posted:
            try:
                status = await post_server_count(count, token)
                if status < 300:
                    posted = count
                    logger.info("Posted the server count to top.gg: %d", count)
                elif status in (401, 403):
                    logger.warning("Top.gg refused the server count (status %d): the token needs the Write "
                                   "permission", status)
                else:
                    logger.warning("Top.gg refused the server count (status %d)", status)
            except (aiohttp.ClientError, TimeoutError) as error:
                logger.warning("Couldn't post the server count to top.gg: %s", error)
            except Exception:  # never let the task die: it would stop posting until the next restart
                logger.exception("Failed to post the server count to top.gg")
        await asyncio.sleep(POST_EVERY)


def vote_url(client) -> str:
    return f"https://top.gg/bot/{client.application_id}/vote"


def vote_button(client) -> discord.ui.View:
    view = discord.ui.View()
    view.add_item(discord.ui.Button(style=discord.ButtonStyle.link, label="Vote on top.gg", emoji="🗳️",
                                    url=vote_url(client)))
    return view


def timestamp(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def setup(client):
    """Setup the vote command."""

    @client.tree.command(name="vote", description=f"Vote for Bankroll on top.gg and get {VOTE_REWARD} coins")
    async def vote(interaction: discord.Interaction):
        token = os.getenv("TOPGG_TOKEN")
        how = ("1️⃣ Press the button below and vote on top.gg\n"
               f"2️⃣ Come back and use `/vote` again: that's when **{fmt(VOTE_REWARD)} coins** go to your balance\n\n"
               "You can vote every 12 hours, and weekend votes pay double!")
        if not token:
            await interaction.response.send_message(embed=discord.Embed(
                title="🗳️ Vote for Bankroll", description="Thanks for supporting the bot!",
                color=discord.Color.blurple()), view=vote_button(client))
            return

        await interaction.response.defer()
        try:
            found = await latest_vote(interaction.user.id, token)
        except TopggError as error:
            logger.warning("Top.gg vote check failed: %s", error)
            await interaction.followup.send("⚠️ Couldn't reach top.gg right now. If you voted, try `/vote` again "
                                            "in a minute: the reward won't go anywhere.", view=vote_button(client))
            return

        if found is None:
            embed = discord.Embed(title="🗳️ Vote for Bankroll", description=how, color=discord.Color.blurple())
            await interaction.followup.send(embed=embed, view=vote_button(client))
            return

        weight = max(1, int(found.get("weight") or 1))
        coins = VOTE_REWARD * weight
        balance = claim_vote_reward(interaction.user.id, found["created_at"], coins)
        again = f"Vote again <t:{timestamp(found['expires_at'])}:R>, then use `/vote` to get your coins."
        if balance is None:
            embed = discord.Embed(title="✅ You already got the reward for this vote",
                                  description=again, color=discord.Color.light_grey())
            await interaction.followup.send(embed=embed, view=vote_button(client))
            return
        embed = discord.Embed(title=f"🗳️ Thanks for voting! +{fmt(coins)} coins",
                              description=("🎉 Weekend votes pay double!\n" if weight > 1 else "")
                              + f"💰 Balance: **{fmt(balance)}**\n{again}",
                              color=discord.Color.green())
        await interaction.followup.send(embed=embed)
