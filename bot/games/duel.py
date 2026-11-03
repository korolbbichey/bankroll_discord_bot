"""
Duel game for the BankRoll Discord Bot: two players stake the same bet on a coin flip, the winner takes both.

The challenger's bet is taken when the duel is created and returned if it doesn't happen.
It is held in the database, so duels left open by a restart are refunded at startup.
Unlike the other games there is no house edge: coins only move between the two players.
"""

import asyncio
import io
import logging
import random

import discord
from discord import app_commands

from ..coinflip_gif import animation_seconds, render_flip_gif
from ..config import DUEL_TIMEOUT, RESULT_DELAY_MARGIN
from ..database import accept_duel, get_balance, open_duel, record_coin_event, refund_duel
from ..progression import send_notice, track_game
from ..slots_gif import GOLD_LIGHT
from ..utils import Bet, DRAW_SLOTS, display_name, fmt, validate_bet

logger = logging.getLogger(__name__)

GIF_NAME = "duel.gif"


class DuelView(discord.ui.View):
    def __init__(self, duel_id: int, challenger: discord.abc.User, opponent: discord.abc.User, bet: int):
        super().__init__(timeout=DUEL_TIMEOUT)
        self.duel_id = duel_id
        self.challenger = challenger
        self.opponent = opponent
        self.bet = bet
        self.finished = False  # set before any await, so a duel can only be accepted or cancelled once
        self.last_interaction: discord.Interaction | None = None

    def disable_buttons(self):
        for item in self.children:
            item.disabled = True

    def close(self) -> bool:
        """Mark the duel as over. Returns False if it was already over."""
        if self.finished:
            return False
        self.finished = True
        self.stop()
        self.disable_buttons()
        return True

    async def on_timeout(self):
        if not self.close() or not refund_duel(self.duel_id):
            return
        if self.last_interaction:
            embed = discord.Embed(title="⌛ Duel expired", color=discord.Color.light_grey(),
                                  description=f"{self.opponent.mention} didn't answer. {self.challenger.mention} got the bet back.")
            try:
                await self.last_interaction.edit_original_response(content=None, embed=embed, view=self)
            except discord.HTTPException:
                pass

    @discord.ui.button(label="⚔️ Accept", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, _):
        if interaction.user.id != self.opponent.id:
            await interaction.response.send_message("Only the challenged player can accept this duel.", ephemeral=True)
            return
        if self.finished:
            await interaction.response.send_message("This duel is already over.", ephemeral=True)
            return
        outcome = random.choice(["heads", "tails"])
        winner = self.challenger if outcome == "heads" else self.opponent
        # Takes the opponent's bet and pays the winner in one transaction, so no restart can lose either bet.
        status, balance = accept_duel(self.duel_id, winner.id)
        if status == "no_coins":
            await interaction.response.send_message(
                f"❌ You need **{fmt(self.bet)}** coins (balance: {fmt(balance)}).", ephemeral=True)
            return
        self.close()
        if status == "gone":
            await interaction.response.send_message("This duel is already over.", ephemeral=True)
            return

        await interaction.response.defer()
        await self.play(interaction, outcome, balance)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.secondary)
    async def decline(self, interaction: discord.Interaction, _):
        if interaction.user.id not in (self.opponent.id, self.challenger.id):
            await interaction.response.send_message("This isn't your duel!", ephemeral=True)
            return
        if not self.close() or not refund_duel(self.duel_id):
            await interaction.response.send_message("This duel is already over.", ephemeral=True)
            return
        who = "cancelled" if interaction.user.id == self.challenger.id else "declined"
        embed = discord.Embed(title=f"🏳️ Duel {who}", color=discord.Color.light_grey(),
                              description=f"{self.challenger.mention} got the bet back.")
        await interaction.response.edit_message(content=None, embed=embed, view=self)

    async def play(self, interaction: discord.Interaction, outcome: str, winner_balance: int):
        """The duel is already settled, so a failed animation can't cost anyone their coins."""
        winner, loser = (self.challenger, self.opponent) if outcome == "heads" else (self.opponent, self.challenger)
        pot = self.bet * 2
        record_coin_event(winner.id, "duel", self.bet, f"beat {loser.id}")
        progress = {
            winner.id: track_game(winner.id, "duel", self.bet, pot),
            loser.id: track_game(loser.id, "duel", self.bet, 0),
        }
        sides = (f"🟡 **Heads:** {self.challenger.mention}\n"
                 f"⚪ **Tails:** {self.opponent.mention}")

        try:
            async with DRAW_SLOTS:
                gif = await asyncio.to_thread(
                    render_flip_gif, outcome, "heads", self.bet, None,
                    "HEADS VS TAILS", f"{outcome.upper()} WINS {fmt(pot)}", GOLD_LIGHT,
                )
            flipping = discord.Embed(title="⚔️ Duel!", description=sides, color=discord.Color.blurple())
            flipping.set_image(url=f"attachment://{GIF_NAME}")
            flipping.set_footer(text=f"Bet: {fmt(self.bet)} each")
            await interaction.edit_original_response(
                content=None, embed=flipping, view=self,
                attachments=[discord.File(io.BytesIO(gif), filename=GIF_NAME)],
            )
            await asyncio.sleep(animation_seconds(False) + RESULT_DELAY_MARGIN)
            has_gif = True
        except Exception:
            logger.exception("Duel animation failed, sending the result as text")
            has_gif = False

        result = discord.Embed(
            title=f"🏆 {display_name(winner)} wins the duel!",
            description=f"{sides}\n\n{winner.mention} takes **{fmt(pot)}** coins • 💰 Balance: **{fmt(winner_balance)}**\n"
                        f"{loser.mention} lost **{fmt(self.bet)}** coins",
            color=discord.Color.gold(),
        )
        if has_gif:
            result.set_image(url=f"attachment://{GIF_NAME}")
        await interaction.edit_original_response(content=None, embed=result, view=self)
        await send_notice(interaction, progress[interaction.user.id])


def setup(client):
    """Setup duel command."""

    @client.tree.command(name="duel", description="Challenge another player: coin flip, the winner takes both bets")
    @app_commands.describe(user="Who to challenge", bet="Coins each player stakes: a number, all or half")
    async def duel(interaction: discord.Interaction, user: discord.User, bet: Bet):
        if interaction.guild_id is None:
            await interaction.response.send_message("❌ Duels only work on a server.", ephemeral=True)
            return
        if user.id == interaction.user.id:
            await interaction.response.send_message("❌ You can't duel yourself.", ephemeral=True)
            return
        if user.bot:
            await interaction.response.send_message("❌ You can't duel a bot.", ephemeral=True)
            return

        is_valid, error_msg = validate_bet(bet, get_balance(interaction.user.id))
        duel_id = open_duel(interaction.user.id, user.id, bet) if is_valid else None
        if duel_id is None:
            await interaction.response.send_message(f"❌ {error_msg or 'You do not have enough balance for that bet.'}", ephemeral=True)
            return

        view = DuelView(duel_id, interaction.user, user, bet)
        view.last_interaction = interaction
        embed = discord.Embed(
            title="⚔️ Duel challenge!",
            description=f"{interaction.user.mention} challenges {user.mention} for **{fmt(bet)}** coins each.\n"
                        f"Coin flip: the winner takes **{fmt(bet * 2)}**.",
            color=discord.Color.gold(),
        )
        embed.set_footer(text=f"New to Bankroll? You start with 100 coins. Expires in {DUEL_TIMEOUT} seconds.")
        try:
            await interaction.response.send_message(user.mention, embed=embed, view=view)
        except Exception:
            if view.close():
                refund_duel(duel_id)
            raise
