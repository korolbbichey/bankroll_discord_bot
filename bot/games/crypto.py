"""
/crypto for the BankRoll Discord Bot: bet on whether a real coin's price goes up or down in 1, 5 or 10 minutes.

The bet is taken first, then the entry price is the first price seen after the command (see crypto_feed).
The card is redrawn every LIVE_EDIT_SECONDS until the end; the closing price is the first one seen after it.
A right guess pays CRYPTO_PAYOUT times the bet, an unchanged price returns it, and if no price comes
the bet is refunded. Bets left running by a restart are refunded at startup.
A command's reply can only be edited for 15 minutes, hence the 10-minute limit on bets.
"""

import asyncio
import io
import logging
import time

import discord
from discord import app_commands

from ..config import CRYPTO_COINS, CRYPTO_DURATIONS, CRYPTO_MAX_BET, CRYPTO_MAX_OPEN, CRYPTO_PAYOUT
from ..crypto_card import COINS, BetCard, history_minutes, price_text, render_bet_card, render_market_card
from .. import crypto_feed
from ..database import crypto_crowd, get_balance, open_crypto_bet, set_crypto_entry, settle_crypto_bet
from ..progression import send_notice, track_game
from ..utils import DRAW_SLOTS, Bet, confirm_big_bet, fmt, validate_bet

logger = logging.getLogger(__name__)

CARD_NAME = "crypto.png"
LIVE_EDIT_SECONDS = 30
ENTRY_WAIT = 20      # seconds to wait for the entry price before the bet is refunded
CLOSE_WAIT = 60      # the same for the closing price
CROWD_MIN_BETS = 5   # fewer bets than this on a coin today, and the "x% bet UP" bar isn't shown
UNAVAILABLE = "📉 Crypto prices aren't available right now. Try again in a minute."


def payout_if_won(bet: int) -> int:
    return round(bet * CRYPTO_PAYOUT)


def outcome(up: bool, entry: float, close: float) -> str:
    if close == entry:
        return "push"
    return "won" if (close > entry) == up else "lost"


def crowd(coin: str) -> tuple[int, int] | None:
    up, down = crypto_crowd(coin)
    return (up, down) if up + down >= CROWD_MIN_BETS else None


async def draw(render, data) -> discord.File:
    async with DRAW_SLOTS:
        png = await asyncio.to_thread(render, data)
    return discord.File(io.BytesIO(png), filename=CARD_NAME)


def text_embed(card: BetCard) -> discord.Embed:
    """The bet as text, when the picture can't be drawn."""
    direction = "⬆️ UP" if card.up else "⬇️ DOWN"
    if card.status == "open":
        title, color = f"📈 {card.coin} {direction} · {fmt(card.bet)}", discord.Color.gold()
    else:
        title = {"won": f"🎉 You won {fmt(card.winnings)}!", "lost": f"😢 You lost {fmt(card.winnings)}",
                 "push": "🤝 Price didn't move: bet returned"}[card.status]
        color = {"won": discord.Color.green(), "lost": discord.Color.red(), "push": discord.Color.light_grey()}[card.status]
    last = card.close if card.close is not None else (card.points[-1][1] if card.points else card.entry)
    lines = [f"Entry **{price_text(card.entry)}** → {'now' if card.status == 'open' else 'close'} **{price_text(last)}**"]
    if card.status == "open":
        lines.append(f"Ends <t:{int(card.ends_at)}:R> · pays {fmt(card.payout_if_won)}")
    elif card.balance is not None:
        lines.append(f"💰 Balance: **{fmt(card.balance)}**")
    return discord.Embed(title=title, description="\n".join(lines), color=color)


async def show(interaction: discord.Interaction, card: BetCard):
    """Draw the card into the reply; text if drawing fails."""
    try:
        file = await draw(render_bet_card, card)
    except Exception:
        logger.exception("Failed to draw the crypto card, sending text instead")
        await interaction.edit_original_response(embed=text_embed(card), attachments=[])
        return
    await interaction.edit_original_response(content=None, embed=None, attachments=[file])


async def start_crypto_bet(interaction: discord.Interaction, coin: str, up: bool, bet: int, minutes: int):
    user_id = interaction.user.id
    feed = crypto_feed.feed
    if not feed.is_fresh():
        await interaction.response.send_message(UNAVAILABLE, ephemeral=True)
        return
    if not feed.is_trading(coin):
        await interaction.response.send_message(
            f"⏸️ Trading of {coin} is paused on the exchange right now, so its price doesn't move. "
            "Pick another coin.", ephemeral=True)
        return
    if bet > CRYPTO_MAX_BET:
        await interaction.response.send_message(f"❌ The maximum crypto bet is {fmt(CRYPTO_MAX_BET)} coins.",
                                                ephemeral=True)
        return
    is_valid, error = validate_bet(bet, get_balance(user_id))
    if not is_valid:
        await interaction.response.send_message(f"❌ {error}", ephemeral=True)
        return
    bet_id = open_crypto_bet(user_id, coin, up, bet, minutes, CRYPTO_MAX_OPEN)
    if bet_id == "too_many":
        await interaction.response.send_message(
            f"⏳ You already have {CRYPTO_MAX_OPEN} crypto bets running. Wait for one to finish.", ephemeral=True)
        return
    if bet_id == "no_coins":
        await interaction.response.send_message("❌ You do not have enough balance for that bet.", ephemeral=True)
        return

    settled = False
    try:
        await interaction.response.defer(thinking=True)
        placed = time.time()
        entry_point = await feed.price_after(coin, placed, ENTRY_WAIT)
        if entry_point is None:
            settle_crypto_bet(bet_id, "refunded", bet)
            settled = True
            await interaction.edit_original_response(content=f"{UNAVAILABLE} Your {fmt(bet)} coins are back.")
            return
        entry_at, entry = entry_point
        set_crypto_entry(bet_id, entry)
        ends_at = entry_at + minutes * 60
        card = BetCard(coin=coin, up=up, bet=bet, minutes=minutes, payout_if_won=payout_if_won(bet), entry=entry,
                       entry_at=entry_at, ends_at=ends_at, points=[], now=entry_at, crowd=crowd(coin))

        def refresh(now: float):
            card.now = now
            card.points = feed.since(coin, entry_at - history_minutes(minutes) * 60)

        while (now := time.time()) < ends_at:
            refresh(now)
            try:
                await show(interaction, card)
            except discord.HTTPException as error:  # e.g. the message was deleted: the bet still finishes
                logger.warning("Couldn't update a crypto bet card: %s", error)
            await asyncio.sleep(max(1.0, min(LIVE_EDIT_SECONDS, ends_at - time.time())))

        close_point = await feed.price_after(coin, ends_at, CLOSE_WAIT)
        if close_point is None:
            balance = settle_crypto_bet(bet_id, "refunded", bet)
            settled = True
            await interaction.edit_original_response(
                content=f"{UNAVAILABLE.split('.')[0]}, so the bet couldn't finish. Your {fmt(bet)} coins are back. "
                        f"💰 Balance: **{fmt(balance or 0)}**", embed=None, attachments=[])
            return
        close = close_point[1]
        status = outcome(up, entry, close)
        payout = {"won": payout_if_won(bet), "lost": 0, "push": bet}[status]
        balance = settle_crypto_bet(bet_id, status, payout, close)
        settled = True
        progress = track_game(user_id, "crypto", bet, payout)

        refresh(close_point[0])
        card.status, card.close, card.balance = status, close, balance
        card.winnings = payout - bet if status == "won" else bet if status == "lost" else 0
        await show(interaction, card)
        await send_notice(interaction, progress)
    except Exception:
        if not settled:
            settle_crypto_bet(bet_id, "refunded", bet)
            logger.exception("A crypto bet failed and was refunded")
            try:
                await interaction.followup.send(f"❌ Something went wrong. Your {fmt(bet)} coins are back.",
                                                ephemeral=True)
            except discord.HTTPException:
                pass
        else:
            logger.exception("Failed to show a finished crypto bet")


def setup(client):
    """Setup the /crypto commands."""
    crypto = app_commands.Group(name="crypto", description="Bet on real crypto prices")

    @crypto.command(name="market", description="Live prices of every coin you can bet on")
    async def market(interaction: discord.Interaction):
        feed = crypto_feed.feed
        if not feed.is_fresh():
            await interaction.response.send_message(UNAVAILABLE, ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        since = time.time() - 60 * 60
        series = {coin: feed.since(coin, since) for coin in CRYPTO_COINS}
        paused = {coin for coin in CRYPTO_COINS if not feed.is_trading(coin)}
        try:
            file = await draw(lambda data: render_market_card(*data), (series, paused))
        except Exception:
            logger.exception("Failed to draw the crypto market, sending text instead")
            lines = [f"**{coin}** {price_text(points[-1][1])}" for coin, points in series.items() if points]
            await interaction.followup.send(embed=discord.Embed(title="📈 Crypto market", description="\n".join(lines),
                                                                color=discord.Color.gold()))
            return
        await interaction.followup.send(file=file)

    @crypto.command(name="bet", description=f"Will the price go up or down? Win {CRYPTO_PAYOUT:g}x your bet")
    @app_commands.describe(coin="The coin", direction="Up or down from now", bet="Coins to bet: a number, all or half",
                           minutes="When the bet ends")
    @app_commands.choices(
        coin=[app_commands.Choice(name=f"{coin} · {COINS[coin][0]}", value=coin) for coin in CRYPTO_COINS],
        direction=[app_commands.Choice(name="⬆️ Up", value="up"), app_commands.Choice(name="⬇️ Down", value="down")],
        minutes=[app_commands.Choice(name=f"{m} minute{'s' if m != 1 else ''}", value=m) for m in CRYPTO_DURATIONS],
    )
    async def bet_command(interaction: discord.Interaction, coin: app_commands.Choice[str],
                          direction: app_commands.Choice[str], bet: Bet, minutes: app_commands.Choice[int]):
        up = direction.value == "up"

        def start(i):
            return start_crypto_bet(i, coin.value, up, bet, minutes.value)
        if not await confirm_big_bet(interaction, bet, start):
            await start(interaction)

    client.tree.add_command(crypto)
