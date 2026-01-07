"""
Blackjack game for the BankRoll Discord Bot.
"""

import discord
from discord import app_commands
import random

from ..config import GAME_TIMEOUT
from ..database import get_balance, update_balance, update_blackjack_stats
from ..utils import validate_bet


def setup(client):
    """Setup blackjack command."""

    @client.tree.command(name="blackjack", description="Play a game of Blackjack with a bet")
    @app_commands.describe(bet="Amount to bet (1-10000)")
    async def blackjack(interaction: discord.Interaction, bet: int):
        user_id = str(interaction.user.id)
        balance = get_balance(user_id)

        is_valid, error_msg = validate_bet(bet, balance)
        if not is_valid:
            await interaction.response.send_message(f"❌ {error_msg}", ephemeral=True)
            return

        # Deduct bet at start of game
        update_balance(user_id, balance - bet)

        def create_deck():
            cards = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
            deck = cards * 4
            random.shuffle(deck)
            return deck

        deck = create_deck()
        player_hand = [deck.pop(), deck.pop()]
        dealer_hand = [deck.pop(), deck.pop()]

        class BlackjackView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=GAME_TIMEOUT)
                self.player_hand = player_hand
                self.dealer_hand = dealer_hand
                self.deck = deck
                self.bet = bet
                self.message = None
                self.ended = False

            def hand_value(self, hand):
                value, aces = 0, 0
                for card in hand:
                    if card in ['J', 'Q', 'K']:
                        value += 10
                    elif card == 'A':
                        value += 11
                        aces += 1
                    else:
                        value += int(card)
                while value > 21 and aces:
                    value -= 10
                    aces -= 1
                return value

            def is_natural_blackjack(self, hand):
                """Check if hand is a natural blackjack (21 with 2 cards)."""
                return len(hand) == 2 and self.hand_value(hand) == 21

            def format_hand(self, hand, hide_second=False):
                return " ".join(['🂠' if i == 1 and hide_second else f"`{card}`" for i, card in enumerate(hand)])

            async def update_message(self, inter, hide_dealer=True, footer="Choose an action."):
                embed = discord.Embed(title="🃏 Blackjack", color=discord.Color.dark_green())
                embed.add_field(name="Your Hand", value=f"{self.format_hand(self.player_hand)} ({self.hand_value(self.player_hand)})", inline=False)
                embed.add_field(name="Dealer's Hand", value=self.format_hand(self.dealer_hand, hide_second=hide_dealer), inline=False)
                embed.add_field(name="💰 Bet", value=f"{self.bet} coins", inline=False)
                embed.set_footer(text=footer)
                if self.message:
                    await self.message.edit(embed=embed, view=self)
                else:
                    self.message = await inter.followup.send(embed=embed, view=self)

            def end_game_embed(self, outcome, winnings, is_blackjack=False):
                color = discord.Color.green() if winnings > 0 else (discord.Color.gold() if winnings == 0 else discord.Color.red())
                embed = discord.Embed(title=f"🎲 {outcome}", color=color)
                embed.add_field(name="Your Hand", value=f"{self.format_hand(self.player_hand)} ({self.hand_value(self.player_hand)})", inline=False)
                embed.add_field(name="Dealer's Hand", value=f"{self.format_hand(self.dealer_hand)} ({self.hand_value(self.dealer_hand)})", inline=False)
                result_text = f"You {'won' if winnings > 0 else 'lost'} {abs(winnings)} coins"
                if is_blackjack:
                    result_text += " (Blackjack bonus: 1.5x!)"
                embed.add_field(name="💰 Result", value=result_text, inline=False)
                embed.add_field(name="💵 New Balance", value=f"{get_balance(user_id)} coins", inline=False)
                return embed

            def disable_all(self):
                for item in self.children:
                    item.disabled = True

            async def finish_game(self, interaction_button, outcome, winnings, is_blackjack=False):
                """Finalize the game and update balances."""
                self.ended = True
                self.disable_all()
                if winnings > 0:
                    update_balance(user_id, get_balance(user_id) + self.bet + winnings)
                    update_blackjack_stats(user_id, winnings, True)
                elif winnings == 0:
                    update_balance(user_id, get_balance(user_id) + self.bet)
                    update_blackjack_stats(user_id, 0, False)
                else:
                    update_blackjack_stats(user_id, 0, False)
                await interaction_button.response.edit_message(embed=self.end_game_embed(outcome, winnings, is_blackjack), view=self)

            async def check_initial_blackjack(self, inter):
                """Check for natural blackjack on initial deal."""
                player_bj = self.is_natural_blackjack(self.player_hand)
                dealer_bj = self.is_natural_blackjack(self.dealer_hand)

                if player_bj and dealer_bj:
                    self.ended = True
                    self.disable_all()
                    update_balance(user_id, get_balance(user_id) + self.bet)
                    embed = self.end_game_embed("🤝 Both Blackjack - Push!", 0)
                    self.message = await inter.followup.send(embed=embed, view=self)
                    return True
                elif player_bj:
                    self.ended = True
                    self.disable_all()
                    winnings = int(self.bet * 1.5)
                    update_balance(user_id, get_balance(user_id) + self.bet + winnings)
                    update_blackjack_stats(user_id, winnings, True)
                    embed = self.end_game_embed("🎰 BLACKJACK!", winnings, is_blackjack=True)
                    self.message = await inter.followup.send(embed=embed, view=self)
                    return True
                return False

            @discord.ui.button(label="🃏 Hit", style=discord.ButtonStyle.primary)
            async def hit(self, interaction_button: discord.Interaction, _):
                if self.ended:
                    return await interaction_button.response.send_message("Game has already ended.", ephemeral=True)
                if str(interaction_button.user.id) != user_id:
                    return await interaction_button.response.send_message("This isn't your game!", ephemeral=True)

                self.player_hand.append(self.deck.pop())
                if self.hand_value(self.player_hand) > 21:
                    await self.finish_game(interaction_button, "💥 You Busted!", -self.bet)
                else:
                    await interaction_button.response.defer()
                    await self.update_message(interaction_button)

            @discord.ui.button(label="✋ Stand", style=discord.ButtonStyle.secondary)
            async def stand(self, interaction_button: discord.Interaction, _):
                if self.ended:
                    return await interaction_button.response.send_message("Game has already ended.", ephemeral=True)
                if str(interaction_button.user.id) != user_id:
                    return await interaction_button.response.send_message("This isn't your game!", ephemeral=True)

                while self.hand_value(self.dealer_hand) < 17:
                    self.dealer_hand.append(self.deck.pop())

                player_val = self.hand_value(self.player_hand)
                dealer_val = self.hand_value(self.dealer_hand)

                if dealer_val > 21:
                    outcome = "🏆 Dealer Busts - You Win!"
                    winnings = self.bet
                elif player_val > dealer_val:
                    outcome = "🏆 You Win!"
                    winnings = self.bet
                elif player_val == dealer_val:
                    outcome = "🤝 It's a Tie!"
                    winnings = 0
                else:
                    outcome = "😢 You Lose!"
                    winnings = -self.bet

                await self.finish_game(interaction_button, outcome, winnings)

        await interaction.response.defer()
        view = BlackjackView()

        if await view.check_initial_blackjack(interaction):
            return

        await view.update_message(interaction)
