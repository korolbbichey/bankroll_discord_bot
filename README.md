# BankRoll Discord bot
## Main features
This is a bot for discord which can be used for the entertainment on a discord server. It uses discord libraries and some in-built python libraries (such as os, random, asyncio, and time). Sqlite is used here for database,    bot token is stored in the .env file.<br />
<ins>Some of the lines of code are unnecessary, such as json files. This is due to the fact that I've used json files at first to store users' data.</ins> 
## Funtionality
#### Interactive Games
Includes chat-based games like blackjack, slots, and coinflip, with animations created by editing messages rapidly.
#### User Profile and Leaderboard
Tracks user stats, balances, and gameplay history via SQLite databases. Users can view their profiles, leaderboard rankings, and claim daily rewards.
#### Commands and Interactions
Implements slash commands for various functionalities such as /help, /balance, and /leaderboard.
####  Backend Architecture 
Uses SQLite for persistent data storage and .env files for sensitive data like bot tokens. JSON was initially utilized for data storage but later supplemented by the database.
#### Custom UI Elements
Features buttons for actions like increasing bets and spinning slots, enhancing interactivity. The repository integrates robust Python coding practices, including modular functions for database management and structured command handling.


> [!NOTE]
> This bot is not considered gambling as it does not use the real currency and users can't lose their means.
