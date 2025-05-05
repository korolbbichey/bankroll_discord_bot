import discord
from discord.ext import commands
import os
import random
import asyncio
from dotenv import load_dotenv
import logging
import json
import sqlite3
import time
from datetime import datetime

CURRENCY_FILE = "currency_data.json"

DB_FILE = "bot_data.db"



def init_db():
    conn = sqlite3.connect("bot_data.db")
    cursor = conn.cursor()
    
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS currency (
        user_id INTEGER PRIMARY KEY,
        balance INTEGER DEFAULT 100
    )''')

    
    cursor.execute('''CREATE TABLE IF NOT EXISTS stats (
        user_id INTEGER PRIMARY KEY,
        games_played INTEGER DEFAULT 0,
        wins INTEGER DEFAULT 0,
        losses INTEGER DEFAULT 0,
        total_earned INTEGER DEFAULT 0,
        most_common_symbol TEXT DEFAULT '',
        largest_win INTEGER DEFAULT 0
    )''')

    
    cursor.execute('''CREATE TABLE IF NOT EXISTS challenges (
        user_id INTEGER PRIMARY KEY,
        daily_wins INTEGER DEFAULT 0,
        weekly_wins INTEGER DEFAULT 0
    )''')

    conn.commit()
    conn.close()


init_db()

def init_blackjack_stats():
    conn = sqlite3.connect("bot_data.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS blackjack_stats (
            user_id INTEGER PRIMARY KEY,
            blackjack_wins INTEGER DEFAULT 0,
            blackjack_losses INTEGER DEFAULT 0,
            blackjack_total_earned INTEGER DEFAULT 0,
            blackjack_largest_win INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

init_blackjack_stats()

def reset_challenges(user_id):
    conn = sqlite3.connect("bot_data.db")
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM challenges WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()

    current_time = int(time.time())
    daily_reset_time = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    weekly_reset_time = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).replace(weekday=6).timestamp())  # Reset on Sunday

    if result:
        
        daily_reset = result[3] < daily_reset_time
        weekly_reset = result[4] < weekly_reset_time

        if daily_reset or weekly_reset:
            cursor.execute("""
                UPDATE challenges SET
                    daily_wins = ?,
                    weekly_wins = ?,
                    last_daily_reset = ?,
                    last_weekly_reset = ?
                WHERE user_id = ?
            """, (0, 0, current_time, current_time, user_id))
            conn.commit()

    conn.close()

def update_challenge_progress(user_id, game_type="blackjack"):
    conn = sqlite3.connect("bot_data.db")
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM challenges WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()

    if result:
        daily_wins, weekly_wins, _, _ = result[1:5]
        
        if game_type == "blackjack":
            daily_wins += 1
            weekly_wins += 1
        
        cursor.execute("""
            UPDATE challenges SET
                daily_wins = ?,
                weekly_wins = ?
            WHERE user_id = ?
        """, (daily_wins, weekly_wins, user_id))
        conn.commit()

    conn.close()


def get_balance(user_id):
    conn = sqlite3.connect("bot_data.db")
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM currency WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    if result is None:
        cursor.execute("INSERT INTO currency (user_id, balance) VALUES (?, 100)", (user_id,))
        conn.commit()
        balance = 100
    else:
        balance = result[0]
    conn.close()
    return balance

def update_balance(user_id, new_balance):
    conn = sqlite3.connect("bot_data.db")
    cursor = conn.cursor()
    cursor.execute("REPLACE INTO currency (user_id, balance) VALUES (?, ?)", (user_id, new_balance))
    conn.commit()
    conn.close()

def update_stats(user_id, winnings, bet, final_grid=None):
    conn = sqlite3.connect("bot_data.db")
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM stats WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()

    
    most_common_symbol = None
    if final_grid is not None:
        most_common_counts = {}
        for row in final_grid:
            for symbol in row:
                most_common_counts[symbol] = most_common_counts.get(symbol, 0) + 1
        most_common_symbol = max(most_common_counts, key=most_common_counts.get)

    profit = max(0, winnings - bet)
    win = winnings > bet

    if result:
        games_played, wins, losses, total_earned, _, largest_win = result[1:]
        wins += 1 if win else 0
        losses += 0 if win else 1
        total_earned += profit
        largest_win = max(largest_win, profit)

        
        cursor.execute(""" 
            UPDATE stats SET
                games_played = games_played + 1,
                wins = ?,
                losses = ?,
                total_earned = ?,
                most_common_symbol = ?,
                largest_win = ?
            WHERE user_id = ?
        """, (wins, losses, total_earned, most_common_symbol if most_common_symbol else "", largest_win, user_id))
    else:
        cursor.execute(""" 
            INSERT INTO stats (user_id, games_played, wins, losses, total_earned, most_common_symbol, largest_win)
            VALUES (?, 1, ?, ?, ?, ?, ?)
        """, (user_id, 1 if win else 0, 0 if win else 1, profit, most_common_symbol if most_common_symbol else "", profit))

    conn.commit()
    conn.close()
    


STATS_FILE = "stats_data.json"


logging.basicConfig(level=logging.INFO)


load_dotenv("bot_key.env")


bot_token = os.getenv("DISCORD_BOT_TOKEN")
if not bot_token:
    raise ValueError("Bot token not found in .env file. Check the file path and variable name.")

logging.info("Bot token loaded successfully.")  


intents = discord.Intents.default()
intents.message_content = True

GUILD_ID = 1318433011116544010  

slot_symbols = ["🍒", "🍉", "🔔", "⭐", "💎", "🤡"]
symbol_weights = {
    "🍒": 0.27,    
    "🍉": 0.2,    
    "🔔": 0.1,   
    "⭐": 0.08,     
    "💎": 0.05,   
    "🤡": 0.3      
}
payouts = {
    "🍒🍒🍒": 5,
    "🍉🍉🍉": 10,
    "🔔🔔🔔": 20,
    "⭐⭐⭐": 50,
    "💎💎💎": 100
}

class Client(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='/', intents=intents)
        self.games = {}  

    async def on_ready(self):
        print(f'Logged on as {self.user}')
        try:
            synced = await self.tree.sync()
            print(f"Synced {len(synced)} command(s) globally.")
        except Exception as e:
            print(f"Failed to sync commands: {e}")


client = Client()

@client.tree.command(name="balance", description="Check your virtual currency balance")
async def balance(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    balance = get_balance(user_id)
    await interaction.response.defer(thinking=True)
    await asyncio.sleep(0.5)
    await interaction.followup.send(f"{interaction.user.name}, your balance is 💰 {balance}")



@client.tree.command(name="slots", description="Play a slot machine with a bet")
async def slots(interaction: discord.Interaction, bet: int):
    user_id = str(interaction.user.id)

    if bet <= 0:
        await interaction.response.send_message("Invalid bet amount.")
        return

    balance = get_balance(user_id)
    if bet > balance:
        await interaction.response.send_message("You don't have enough balance to bet that amount.")
        return

    class SlotView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)
            self.message = None
            self.bet = bet
            self.keep_spinning = True
            self.active = True

        def freeze(self):
            for item in self.children:
                item.disabled = True

        def unfreeze(self):
            for item in self.children:
                item.disabled = False

        async def disable_view(self):
            self.active = False
            self.freeze()
            if self.message:
                await self.message.edit(view=self)

        @discord.ui.button(label="⬆ Increase Bet", style=discord.ButtonStyle.secondary)
        async def increase_bet(self, interaction_button: discord.Interaction, button: discord.ui.Button):
            if not self.active:
                await interaction_button.response.send_message("This game has ended.", ephemeral=True)
                return
            if str(interaction_button.user.id) != user_id:
                await interaction_button.response.send_message("This isn't your game!", ephemeral=True)
                return
            if self.bet + 1 <= get_balance(user_id):
                self.bet += 1
                await interaction_button.response.defer()
                await self.message.edit(content=f"🎲 Bet increased to {self.bet}", view=self)
            else:
                await interaction_button.response.send_message("Not enough balance to increase bet!", ephemeral=True)

        @discord.ui.button(label="⬇ Decrease Bet", style=discord.ButtonStyle.secondary)
        async def decrease_bet(self, interaction_button: discord.Interaction, button: discord.ui.Button):
            if not self.active:
                await interaction_button.response.send_message("This game has ended.", ephemeral=True)
                return
            if str(interaction_button.user.id) != user_id:
                await interaction_button.response.send_message("This isn't your game!", ephemeral=True)
                return
            if self.bet > 1:
                self.bet -= 1
                await interaction_button.response.defer()
                await self.message.edit(content=f"🎲 Bet decreased to {self.bet}", view=self)
            else:
                await interaction_button.response.send_message("Minimum bet is 1!", ephemeral=True)

        @discord.ui.button(label="Spin Again 🎰", style=discord.ButtonStyle.success)
        async def spin_again(self, interaction_button: discord.Interaction, button: discord.ui.Button):
            if not self.active:
                await interaction_button.response.send_message("This game has ended.", ephemeral=True)
                return
            if str(interaction_button.user.id) != user_id:
                await interaction_button.response.send_message("This isn't your game!", ephemeral=True)
                return
            await self.spin(interaction_button)

        @discord.ui.button(label="Stop 🚫", style=discord.ButtonStyle.danger)
        async def stop(self, interaction_button: discord.Interaction, button: discord.ui.Button):
            if not self.active:
                await interaction_button.response.send_message("This game has already ended.", ephemeral=True)
                return
            if str(interaction_button.user.id) != user_id:
                await interaction_button.response.send_message("This isn't your game!", ephemeral=True)
                return
            self.keep_spinning = False
            await self.disable_view()
            await interaction_button.response.edit_message(content="🎰 Game ended.", view=self)
            
        async def animate_vertical_spin(self):
            rows, columns = 3, 3
            lock_steps = [1, 2, 3]  
            final_symbols = [  
                [random.choice(slot_symbols) for _ in range(rows)] for _ in range(columns)
            ]

            for step in range(4):  
                grid = []

                for row in range(rows):
                    current_row = []
                    for col in range(columns):
                        if step >= lock_steps[col]:
                            current_row.append(final_symbols[col][row])
                        else:
                            current_row.append(random.choice(slot_symbols))
                    grid.append(current_row)

                content = f"🎰 Spinning...\n{format_grid(grid)}\n🎲 Current Bet: {self.bet}"
                await self.message.edit(content=content)
                await asyncio.sleep(0.4)

            
            final_grid = [[final_symbols[col][row] for col in range(columns)] for row in range(rows)]
            return final_grid

        async def spin(self, interaction_obj):
            if get_balance(user_id) < self.bet:
                await interaction_obj.followup.send("❌ You don't have enough coins to spin again!", ephemeral=True)
                self.keep_spinning = False
                if self.message:
                    await self.disable_view()
                return

            
            update_balance(user_id, get_balance(user_id) - self.bet)

            if not self.message:
                await interaction_obj.response.defer()
                self.message = await interaction_obj.followup.send("🎰 Spinning...")

            self.freeze()
            await self.message.edit(view=self)

            final_grid = await self.animate_vertical_spin()
            winnings = calculate_winnings(final_grid, self.bet)

            
            update_balance(user_id, get_balance(user_id) + winnings)
            update_stats(user_id, winnings, self.bet, final_grid)

            
            if winnings > 0:
                
                conn = sqlite3.connect("bot_data.db")
                cursor = conn.cursor()
                cursor.execute("SELECT daily_wins FROM challenges WHERE user_id = ?", (user_id,))
                daily_wins_row = cursor.fetchone()

                if daily_wins_row:
                    daily_wins = daily_wins_row[0] + 1
                    cursor.execute("UPDATE challenges SET daily_wins = ? WHERE user_id = ?", (daily_wins, user_id))
                else:
                    cursor.execute("INSERT INTO challenges (user_id, daily_wins) VALUES (?, ?)", (user_id, 1))

                conn.commit()
                conn.close()

            new_balance = get_balance(user_id)
            result_text = (
                f"🎰 Final Result!\n{format_grid(final_grid)}\n"
                f"You {'won' if winnings > 0 else 'lost'} {abs(winnings - self.bet)} coins!\n"
                f"New balance: 💰 {new_balance}\n"
                f"🎲 Current Bet: {self.bet}"
            )

            self.unfreeze()
            await self.message.edit(content=result_text, view=self)



    def generate_grid():
        return [[random.choices(slot_symbols, weights=[symbol_weights[s] for s in slot_symbols])[0] for _ in range(3)] for _ in range(3)]

    def format_grid(grid):
        return "```\n" + "\n".join([" | ".join(row) for row in grid]) + "\n```"

    view = SlotView()
    await view.spin(interaction)


def calculate_winnings(grid, bet):
    
    for line in grid + list(zip(*grid)) + [[grid[i][i] for i in range(3)], [grid[i][2-i] for i in range(3)]]:
        line_str = "".join(line)
        if line_str in payouts:
            return payouts[line_str] * bet
    return 0

@client.tree.command(name="leaderboard", description="Show the top users with the most virtual currency")
async def leaderboard(interaction: discord.Interaction):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, balance FROM currency ORDER BY balance DESC LIMIT 5")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        await interaction.response.send_message("No currency data available yet.")
        return

    embed = discord.Embed(
        title="🏆 Leaderboard — Top Richest Players",
        description="Here are the top 5 users with the highest balance!",
        color=discord.Color.red()
    )

    for i, (user_id, balance) in enumerate(rows, start=1):
        try:
            user = await client.fetch_user(int(user_id))
            embed.add_field(
                name=f"{i}. {user.name}",
                value=f"💰 {balance} coins",
                inline=False
            )
        except discord.NotFound:
            embed.add_field(
                name=f"{i}. Unknown User ({user_id})",
                value=f"💰 {balance} coins",
                inline=False
            )

    await interaction.response.send_message(embed=embed)


@client.tree.command(name="profile", description="View your game stats and balance")
async def profile(interaction: discord.Interaction, user: discord.User = None):
    target = user or interaction.user
    uid = target.id
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    
    cursor.execute("SELECT games_played, wins, losses, total_earned, most_common_symbol, largest_win FROM stats WHERE user_id = ?", (uid,))
    row = cursor.fetchone()

    
    cursor.execute("SELECT blackjack_wins, blackjack_losses, blackjack_total_earned, blackjack_largest_win FROM blackjack_stats WHERE user_id = ?", (uid,))
    blackjack_row = cursor.fetchone()

    
    cursor.execute("SELECT balance FROM currency WHERE user_id = ?", (uid,))
    balance_row = cursor.fetchone()
    conn.close()

    balance = balance_row[0] if balance_row else 100

    if not row:
        await interaction.response.send_message(f"{target.name} hasn't played any games yet!", ephemeral=True)
        return

    games, wins, losses, total_earned, most_common_symbol, largest_win = row
    blackjack_wins, blackjack_losses, blackjack_total_earned, blackjack_largest_win = blackjack_row if blackjack_row else (0, 0, 0, 0)
    win_rate = (wins / games * 100) if games > 0 else 0

    try:
        most_common = json.loads(most_common_symbol)
        most_common_sorted = sorted(most_common.items(), key=lambda x: x[1], reverse=True)
        common_symbol_text = most_common_sorted[0][0] if most_common_sorted else "N/A"
    except Exception:
        common_symbol_text = "N/A"

    embed = discord.Embed(
        title=f"{target.name}'s Game Stats 🎮",
        color=discord.Color.gold()
    )
    embed.set_thumbnail(url=target.display_avatar.url)

    
    embed.add_field(name="💰 Balance", value=str(balance), inline=True)
    embed.add_field(name="🎮 Games Played", value=str(games), inline=True)
    embed.add_field(name="✅ Wins", value=str(wins), inline=True)
    embed.add_field(name="❌ Losses", value=str(losses), inline=True)
    embed.add_field(name="📈 Win Rate", value=f"{win_rate:.2f}%", inline=True)
    embed.add_field(name="💸 Total Earned", value=str(total_earned), inline=True)
    embed.add_field(name="⭐ Most Common Symbol", value=common_symbol_text, inline=True)
    embed.add_field(name="🏆 Largest Win", value=str(largest_win), inline=True)

    embed.add_field(name="\u200b", value="\u200b", inline=False)  

   
    embed.add_field(name="♠️ Blackjack Wins", value=str(blackjack_wins), inline=True)
    embed.add_field(name="♦️ Blackjack Losses", value=str(blackjack_losses), inline=True)
    embed.add_field(name="💵 Blackjack Total Earned", value=str(blackjack_total_earned), inline=True)
    embed.add_field(name="🎯 Blackjack Largest Win", value=str(blackjack_largest_win), inline=True)

    await interaction.response.send_message(embed=embed)





@client.tree.command(name="tos", description="Get a link to terms of service")
async def tos(interactiom: discord.Interaction):
    await interactiom.user.send("https://gist.github.com/korolbbichey/ec9757512835365e37c3c8823d096ccb")

@client.tree.command(name="help", description="Get a list of all available commands in a private message")
async def help_command(interaction: discord.Interaction):
    help_text = """
📖 **Bankroll Command List**

```
/balance              - Check your virtual coin balance
/slots <bet>          - Play a slot machine game with your bet
/leaderboard          - View the top 5 richest players
/profile [@user]      - View your own or someone else's stats
/daily_reward         - Claim daily reward(Updates every day)
/blackjack            - Play a blackjack game with your bet
/tos                  - View the Terms of Service 
💡 Need help? Contact the dev or visit the support server! ```
"""
    try:
        await interaction.user.send(help_text)
        await interaction.response.send_message("✅ Help has been sent to your DMs!", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("❌ I couldn't send you a DM. Please check your privacy settings!", ephemeral=True)
        
@client.tree.command(name="add_balance", description="Manually add virtual currency to a player's balance")
async def add_balance(interaction: discord.Interaction, user: discord.User, amount: int):
    
    if amount <= 0:
        await interaction.response.send_message("Amount must be positive!", ephemeral=True)
        return

    
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        return

    user_id = user.id

   
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM currency WHERE user_id = ?", (user_id,) )
    result = cursor.fetchone()

    if result is None:
        
        cursor.execute("INSERT INTO currency (user_id, balance) VALUES (?, ?)", (user_id, amount))
    else:
        
        current_balance = result[0]
        new_balance = current_balance + amount
        cursor.execute("REPLACE INTO currency (user_id, balance) VALUES (?, ?)", (user_id, new_balance))

    conn.commit()
    conn.close()

    
    await interaction.response.send_message(f"Successfully added 💰 {amount} to {user.name}'s balance. New balance: 💰 {new_balance}")
    
from datetime import datetime

@client.tree.command(name="daily_reward", description="Claim your daily reward")
async def daily_reward(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    
    cursor.execute("PRAGMA table_info(currency)")
    columns = [column[1] for column in cursor.fetchall()]
    if "last_claim_date" not in columns:
        cursor.execute("ALTER TABLE currency ADD COLUMN last_claim_date TEXT")

    
    cursor.execute("SELECT balance, last_claim_date FROM currency WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()

    today = datetime.today().date()

    if result:
        balance, last_claim_str = result

        if last_claim_str:
            last_claim_date = datetime.strptime(last_claim_str, "%Y-%m-%d").date()
            if last_claim_date == today:
                await interaction.response.send_message("You’ve already claimed your daily reward today. Try again tomorrow!", ephemeral=True)
                conn.close()
                return
    else:
        
        balance = 100
        cursor.execute("INSERT INTO currency (user_id, balance, last_claim_date) VALUES (?, ?, ?)", (user_id, balance, today.strftime("%Y-%m-%d")))
        conn.commit()
        reward = 50
        await interaction.response.send_message(f"You've been initialized and received your first daily reward of 💰 {reward}!")
        conn.close()
        return


    reward = 50
    new_balance = balance + reward

    cursor.execute("UPDATE currency SET balance = ?, last_claim_date = ? WHERE user_id = ?", (new_balance, today.strftime("%Y-%m-%d"), user_id))
    conn.commit()
    conn.close()

    await interaction.response.send_message(f"✅ You've claimed your daily reward of 💰 {reward}! Your new balance is 💰 {new_balance}.", ephemeral=True)
    
@client.tree.command(name="blackjack", description="Play a game of Blackjack with a bet")
async def blackjack(interaction: discord.Interaction, bet: int):
    user_id = str(interaction.user.id)
    if bet <= 0:
        await interaction.response.send_message("⚠️ Bet must be greater than zero.", ephemeral=True)
        return

    balance = get_balance(user_id)
    if bet > balance:
        await interaction.response.send_message("❌ You don't have enough balance to bet that amount.", ephemeral=True)
        return

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
            super().__init__(timeout=60)
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

        def format_hand(self, hand, hide_second=False):
            return " ".join(['🂠' if i == 1 and hide_second else f"`{card}`" for i, card in enumerate(hand)])

        async def update_message(self, interaction, hide_dealer=True, footer="Choose an action."):
            embed = discord.Embed(title="🃏 Blackjack", color=discord.Color.dark_green())
            embed.add_field(name="Your Hand", value=f"{self.format_hand(self.player_hand)} ({self.hand_value(self.player_hand)})", inline=False)
            embed.add_field(name="Dealer's Hand", value=self.format_hand(self.dealer_hand, hide_second=hide_dealer), inline=False)
            embed.set_footer(text=footer)
            if self.message:
                await self.message.edit(embed=embed, view=self)
            else:
                self.message = await interaction.followup.send(embed=embed, view=self)

        def end_game_embed(self, outcome, winnings):
            embed = discord.Embed(title=f"🎲 {outcome}", color=discord.Color.gold())
            embed.add_field(name="Your Hand", value=f"{self.format_hand(self.player_hand)} ({self.hand_value(self.player_hand)})", inline=False)
            embed.add_field(name="Dealer's Hand", value=f"{self.format_hand(self.dealer_hand)} ({self.hand_value(self.dealer_hand)})", inline=False)
            embed.add_field(name="💰 Result", value=f"You {'won' if winnings > 0 else 'lost'} {abs(winnings)} coins", inline=False)
            return embed

        def disable_all(self):
            for item in self.children:
                item.disabled = True

        @discord.ui.button(label="🃏 Hit", style=discord.ButtonStyle.primary)
        async def hit(self, interaction_button: discord.Interaction, _):
            if self.ended:
                return await interaction_button.response.send_message("Game has already ended.", ephemeral=True)
            self.player_hand.append(self.deck.pop())
            if self.hand_value(self.player_hand) > 21:
                update_balance(user_id, balance - self.bet)
                update_stats(user_id, -self.bet, self.bet, None)
                self.ended = True
                self.disable_all()
                await interaction_button.response.edit_message(embed=self.end_game_embed("💥 You Busted!", -self.bet), view=self)
            else:
                await interaction_button.response.defer()
                await self.update_message(interaction_button)

        @discord.ui.button(label="✋ Stand", style=discord.ButtonStyle.secondary)
        async def stand(self, interaction_button: discord.Interaction, _):
            if self.ended:
                return await interaction_button.response.send_message("Game has already ended.", ephemeral=True)
            
            while self.hand_value(self.dealer_hand) < 17:
                self.dealer_hand.append(self.deck.pop())

            player_val = self.hand_value(self.player_hand)
            dealer_val = self.hand_value(self.dealer_hand)

            if dealer_val > 21 or player_val > dealer_val:
                outcome = "🏆 You Win!"
                winnings = self.bet
            elif player_val == dealer_val:
                outcome = "🤝 It's a Tie!"
                winnings = 0
            else:
                outcome = "😢 You Lose!"
                winnings = -self.bet

            update_balance(user_id, balance + winnings)
            update_stats(user_id, winnings, self.bet, None)

            self.ended = True
            self.disable_all()
            await interaction_button.response.edit_message(embed=self.end_game_embed(outcome, winnings), view=self)

    

    await interaction.response.defer()
    view = BlackjackView()
    await view.update_message(interaction)

@client.tree.command(name="coinflip", description="Flip a coin and win double your bet if you guess right!")
async def coinflip(interaction: discord.Interaction, guess: str, bet: int):
    user_id = str(interaction.user.id)
    guess = guess.lower()

    if guess not in ["heads", "tails"]:
        await interaction.response.send_message("Please choose either 'heads' or 'tails'.", ephemeral=True)
        return

    if bet <= 0:
        await interaction.response.send_message("Your bet must be greater than 0.", ephemeral=True)
        return

    balance = get_balance(user_id)
    if bet > balance:
        await interaction.response.send_message("You don't have enough coins for that bet.", ephemeral=True)
        return

    
    embed = discord.Embed(
        title="🪙 Coin Flip!",
        description="Flipping the coin...",
        color=discord.Color.random()
    )
    embed.set_footer(text="You guessed: " + guess.capitalize())
    message = await interaction.response.send_message(embed=embed)
    message = await interaction.original_response()

    
    flip_sequence = ["Heads 🟤", "Tails ⚪", "Heads 🟤", "Tails ⚪", "Heads 🟤", "Tails ⚪"]
    for flip in flip_sequence:
        embed.description = f"Flipping the coin...\n**{flip}**"
        await message.edit(embed=embed)
        await asyncio.sleep(0.5)

    
    outcome = random.choice(["heads", "tails"])
    emoji = "🟤" if outcome == "heads" else "⚪"
    win = guess == outcome

    if win:
        winnings = bet * 2
        update_balance(user_id, balance + bet)
        result = f"🎉 It landed on **{outcome.capitalize()} {emoji}**!\nYou win **{bet}** coins!"
    else:
        update_balance(user_id, balance - bet)
        result = f"😢 It landed on **{outcome.capitalize()} {emoji}**!\nYou lost **{bet}** coins."

    
    embed.title = "🪙 Coin Flip Result"
    embed.description = result + f"\n\n💰 New Balance: **{get_balance(user_id)}**"
    embed.color = discord.Color.green() if win else discord.Color.red()

    await message.edit(embed=embed)


client.run(bot_token)

