"""
General commands for the BankRoll Discord Bot.
"""

import discord


def setup(client):
    """Setup general commands."""

    @client.tree.command(name="tos", description="Get a link to terms of service")
    async def tos(interaction: discord.Interaction):
        try:
            await interaction.user.send("https://gist.github.com/korolbbichey/ec9757512835365e37c3c8823d096ccb")
            await interaction.response.send_message("✅ Terms of Service link sent to your DMs!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I couldn't send you a DM. Please check your privacy settings!", ephemeral=True)

    @client.tree.command(name="help", description="Get a list of all available commands in a private message")
    async def help_command(interaction: discord.Interaction):
        help_text = """
📖 **Bankroll Command List**

```
/balance              - Check your virtual coin balance
/slots <bet>          - Play a slot machine game with your bet
/leaderboard          - View the top 5 richest players
/profile [@user]      - View your own or someone else's stats
/daily_reward         - Claim daily reward (Updates every day)
/blackjack <bet>      - Play a blackjack game with your bet
/coinflip <guess> <bet> - Flip a coin and bet on the outcome
/tos                  - View the Terms of Service
💡 Need help? Contact the dev or visit the support server!
```
"""
        try:
            await interaction.user.send(help_text)
            await interaction.response.send_message("✅ Help has been sent to your DMs!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I couldn't send you a DM. Please check your privacy settings!", ephemeral=True)
