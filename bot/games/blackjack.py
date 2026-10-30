"""
Blackjack game for the BankRoll Discord Bot.
"""

import discord
from discord import app_commands
import asyncio
import io
import random
import logging

from ..config import GAME_TIMEOUT
from ..database import get_balance, try_debit, credit, update_blackjack_stats
from ..utils import validate_bet, fmt, Bet, DRAW_SLOTS
from ..progression import Progress, track_game, send_notice
from ..blackjack_card import render_table
from ..slots_gif import GOLD_LIGHT, GREEN, MUTED, RED

logger = logging.getLogger(__name__)

TABLE_NAME = "table.png"

RANKS = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
SUITS = ['♠', '♥', '♦', '♣']


def create_deck() -> list[tuple[str, str]]:
    deck = [(rank, suit) for rank in RANKS for suit in SUITS]
    random.shuffle(deck)
    return deck


def hand_value(hand) -> int:
    value, aces = 0, 0
    for rank, _ in hand:
        if rank in ('J', 'Q', 'K'):
            value += 10
        elif rank == 'A':
            value += 11
            aces += 1
        else:
            value += int(rank)
    while value > 21 and aces:
        value -= 10
        aces -= 1
    return value


def is_natural(hand) -> bool:
    return len(hand) == 2 and hand_value(hand) == 21


def format_hand(hand, hide_second=False) -> str:
    return " ".join('`🂠`' if i == 1 and hide_second else f"`{rank}{suit}`" for i, (rank, suit) in enumerate(hand))


class BlackjackView(discord.ui.View):
    def __init__(self, user_id: int, bet: int):
        super().__init__(timeout=GAME_TIMEOUT)
        self.user_id = user_id
        self.bet = bet
        self.deck = create_deck()
        self.player = [self.deck.pop(), self.deck.pop()]
        self.dealer = [self.deck.pop(), self.deck.pop()]
        self.settled = False
        self.doubled = False
        self.progress: Progress | None = None  # set when the game is settled
        self.status = ("HIT, STAND OR DOUBLE", MUTED)  # the line on the table picture
        self.last_interaction: discord.Interaction | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your game!", ephemeral=True)
            return False
        if self.settled:
            await interaction.response.send_message("Game has already ended.", ephemeral=True)
            return False
        return True

    # ---------- rendering ----------

    def playing_embed(self) -> discord.Embed:
        embed = discord.Embed(title="🃏 Blackjack", color=discord.Color.dark_green())
        embed.add_field(name="Your Hand", value=f"{format_hand(self.player)} ({hand_value(self.player)})", inline=False)
        embed.add_field(name="Dealer's Hand", value=format_hand(self.dealer, hide_second=True), inline=False)
        embed.add_field(name="💰 Bet", value=f"{fmt(self.bet)} coins", inline=False)
        embed.set_footer(text="Hit, Stand or Double down.")
        return embed

    def result_embed(self, outcome: str, profit: int, balance: int, note: str = "") -> discord.Embed:
        color = discord.Color.green() if profit > 0 else (discord.Color.gold() if profit == 0 else discord.Color.red())
        embed = discord.Embed(title=f"🎲 {outcome}", color=color)
        embed.add_field(name="Your Hand", value=f"{format_hand(self.player)} ({hand_value(self.player)})", inline=False)
        embed.add_field(name="Dealer's Hand", value=f"{format_hand(self.dealer)} ({hand_value(self.dealer)})", inline=False)
        if profit > 0:
            result = f"You won {fmt(profit)} coins"
        elif profit == 0:
            result = "Your bet was returned"
        else:
            result = f"You lost {fmt(-profit)} coins"
        embed.add_field(name="💰 Result", value=result + note, inline=False)
        embed.add_field(name="💵 New Balance", value=f"{fmt(balance)} coins", inline=False)
        return embed

    async def show(self, interaction: discord.Interaction, embed: discord.Embed):
        """Show the game on a drawn table. The interaction must be deferred. Without a picture, the embed's text is enough."""
        try:
            async with DRAW_SLOTS:
                png = await asyncio.to_thread(
                    render_table, self.player, self.dealer, hand_value(self.player),
                    hand_value(self.dealer) if self.settled else None, *self.status, not self.settled,
                )
        except Exception:
            logger.exception("Failed to draw the blackjack table, showing text instead")
            await interaction.edit_original_response(embed=embed, view=self, attachments=[])
            return

        # The hands are on the picture, so the text doesn't repeat them.
        for index in reversed(range(len(embed.fields))):
            if embed.fields[index].name in ("Your Hand", "Dealer's Hand"):
                embed.remove_field(index)
        embed.set_image(url=f"attachment://{TABLE_NAME}")
        await interaction.edit_original_response(
            embed=embed, view=self, attachments=[discord.File(io.BytesIO(png), filename=TABLE_NAME)]
        )

    # ---------- game logic ----------

    def settle(self, outcome: str, profit: int, note: str = "", natural: bool = False) -> discord.Embed:
        """Pay out and record stats exactly once. profit is relative to the (already debited) bet."""
        self.settled = True
        self.stop()
        for item in self.children:
            item.disabled = True

        payout = self.bet + profit  # 0 on a loss, bet on a push, bet+profit on a win
        balance = credit(self.user_id, payout) if payout > 0 else get_balance(self.user_id)
        update_blackjack_stats(self.user_id, profit, is_win=profit > 0, is_push=profit == 0)
        self.progress = track_game(self.user_id, "blackjack", self.bet, payout, natural=natural, doubled=self.doubled)
        if natural:
            self.status = (f"BLACKJACK +{fmt(profit)}", GOLD_LIGHT)
        elif profit > 0:
            self.status = (f"YOU WON +{fmt(profit)}", GREEN)
        elif profit == 0:
            self.status = ("PUSH", GOLD_LIGHT)
        elif hand_value(self.player) > 21:
            self.status = (f"BUSTED -{fmt(-profit)}", RED)
        else:
            self.status = (f"YOU LOST {fmt(-profit)}", RED)
        return self.result_embed(outcome, profit, balance, note)

    def check_naturals(self) -> discord.Embed | None:
        player_bj, dealer_bj = is_natural(self.player), is_natural(self.dealer)
        if player_bj and dealer_bj:
            return self.settle("🤝 Both Blackjack - Push!", 0)
        if player_bj:
            return self.settle("🎰 BLACKJACK!", int(self.bet * 1.5), " (Blackjack pays 3:2!)", natural=True)
        if dealer_bj:
            return self.settle("🃏 Dealer has Blackjack!", -self.bet)
        return None

    def resolve_stand(self) -> discord.Embed:
        while hand_value(self.dealer) < 17:
            self.dealer.append(self.deck.pop())

        player_val, dealer_val = hand_value(self.player), hand_value(self.dealer)
        if dealer_val > 21:
            return self.settle("🏆 Dealer Busts - You Win!", self.bet)
        if player_val > dealer_val:
            return self.settle("🏆 You Win!", self.bet)
        if player_val == dealer_val:
            return self.settle("🤝 It's a Tie!", 0)
        return self.settle("😢 You Lost!", -self.bet)

    # ---------- buttons ----------

    @discord.ui.button(label="🃏 Hit", style=discord.ButtonStyle.primary)
    async def hit(self, interaction: discord.Interaction, _):
        self.last_interaction = interaction
        self.player.append(self.deck.pop())
        self.double.disabled = True

        value = hand_value(self.player)
        if value > 21:
            embed = self.settle("💥 You Busted!", -self.bet)
        elif value == 21:
            embed = self.resolve_stand()
        else:
            embed = self.playing_embed()
        await interaction.response.defer()
        await self.show(interaction, embed)
        await send_notice(interaction, self.progress)

    @discord.ui.button(label="✋ Stand", style=discord.ButtonStyle.secondary)
    async def stand(self, interaction: discord.Interaction, _):
        self.last_interaction = interaction
        embed = self.resolve_stand()
        await interaction.response.defer()
        await self.show(interaction, embed)
        await send_notice(interaction, self.progress)

    @discord.ui.button(label="💰 Double", style=discord.ButtonStyle.success)
    async def double(self, interaction: discord.Interaction, _):
        self.last_interaction = interaction
        if not try_debit(self.user_id, self.bet):
            await interaction.response.send_message("❌ Not enough coins to double down.", ephemeral=True)
            return
        self.bet *= 2
        self.doubled = True
        self.player.append(self.deck.pop())
        if hand_value(self.player) > 21:
            embed = self.settle("💥 You Busted!", -self.bet)
        else:
            embed = self.resolve_stand()
        await interaction.response.defer()
        await self.show(interaction, embed)
        await send_notice(interaction, self.progress)

    async def on_timeout(self):
        if self.settled:
            return
        embed = self.resolve_stand()
        embed.set_footer(text="⌛ Timed out — stood automatically.")
        if self.last_interaction:
            try:
                await self.show(self.last_interaction, embed)
                await send_notice(self.last_interaction, self.progress)
            except discord.HTTPException:
                pass


def setup(client):
    """Setup blackjack command."""

    @client.tree.command(name="blackjack", description="Play a game of Blackjack with a bet")
    @app_commands.describe(bet="Coins to bet: a number, all or half")
    async def blackjack(interaction: discord.Interaction, bet: Bet):
        user_id = interaction.user.id
        is_valid, error_msg = validate_bet(bet, get_balance(user_id))
        if not is_valid or not try_debit(user_id, bet):
            await interaction.response.send_message(f"❌ {error_msg or 'You do not have enough balance for that bet.'}", ephemeral=True)
            return

        view = BlackjackView(user_id, bet)
        view.last_interaction = interaction
        try:
            embed = view.check_naturals()
            if embed is None:
                if bet > get_balance(user_id):
                    view.double.disabled = True
                embed = view.playing_embed()
            await interaction.response.defer()
            await view.show(interaction, embed)
            await send_notice(interaction, view.progress)
        except Exception:
            if not view.settled:
                view.stop()
                credit(user_id, bet)
                logger.exception("Blackjack failed to start, bet refunded")
            raise
