# BankRoll Discord bot
## Main features
This is a bot for discord which can be used for the entertainment on a discord server. It uses discord libraries and some in-built python libraries (such as os, random, asyncio, and time). Sqlite is used here for database,    bot token is stored in the .env file.<br />
<ins>Some of the lines of code are unnecessary, such as json files. This is due to the fact that I've used json files at first to store users' data.</ins> 
## Funtionality
In this bot, there are only chat games that include blackjack, coinflip and slots. All of these have some sort of animation, which were made by quickly editing messages.
#### <ins>Slots function</ins> 
It can show 6 symbols (emojis) and works pretty much as a real slots machine, however, there is a filler that is used to slightly decrease the chances of winning. Each symbol has its own weight stored in a dictionary which is used as a chance choosing this symbol to output it. The way of choosing the symbol is not fair and is set by weight of a symbol, because the combination of different symbols will give a user a different payout, so there are more chances of winning the smallest payout than compared to winning the biggest prize.<br/>
3x3 grid is generated to output the results of the spin and the animation of it




> [!NOTE]
> This bot is not considered gambling as it does not use the real currency and users can't lose their means.
