"""
General commands for the BankRoll Discord Bot.
"""

import discord

TOS_URL = "https://gist.github.com/korolbbichey/ec9757512835365e37c3c8823d096ccb"

HELP_TEXT = """
📖 **Bankroll Command List**

```
/balance                - Check your virtual coin balance
/daily_reward           - Claim daily reward (resets 00:00 UTC)
/slots <bet>            - 3x3 slot machine, every line pays
/blackjack <bet>        - Blackjack: Hit, Stand or Double down
/coinflip <guess> <bet> - Flip a coin and bet on the outcome
/leaderboard            - View the top 5 richest players
/profile [@user]        - View your own or someone else's stats
/tos                    - View the Terms of Service
```
💡 Need help? Contact the dev or visit the support server!
"""


def setup(client):
    """Setup general commands."""

    @client.tree.command(name="tos", description="Get a link to terms of service")
    async def tos(interaction: discord.Interaction):
        await interaction.response.send_message(f"📜 Terms of Service: {TOS_URL}", ephemeral=True)

    @client.tree.command(name="help", description="Get a list of all available commands")
    async def help_command(interaction: discord.Interaction):
        await interaction.response.send_message(HELP_TEXT, ephemeral=True)
