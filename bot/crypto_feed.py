"""
Live crypto prices for /crypto, from Binance's public market data (no key needed, not blocked by region).

One background task asks for every coin's price every few seconds and keeps the last hour in memory
(about 800 points per coin) for the charts. At startup the hour is filled from 1-minute candles.
A bet's entry and closing prices are the first prices seen *after* the moment they're needed, so a player
watching a faster price somewhere else can't know them in advance.
"""

import asyncio
import json
import logging
import time
from collections import deque

import aiohttp

from .config import CRYPTO_COINS

logger = logging.getLogger(__name__)

API = "https://data-api.binance.vision/api/v3"
POLL_SECONDS = 5
FRESH_SECONDS = 20       # older than this, prices count as unavailable and no new bets start
KEEP_SECONDS = 60 * 60
STATUS_EVERY = 60 * 60   # how often to check which pairs are trading
TIMEOUT = aiohttp.ClientTimeout(total=10)


def symbol(coin: str) -> str:
    return f"{coin}USDT"


async def fetch_prices(session: aiohttp.ClientSession) -> dict[str, float]:
    """Every coin's current price."""
    symbols = json.dumps([symbol(coin) for coin in CRYPTO_COINS], separators=(",", ":"))
    async with session.get(f"{API}/ticker/price", params={"symbols": symbols}) as reply:
        reply.raise_for_status()
        rows = await reply.json()
    by_symbol = {row["symbol"]: float(row["price"]) for row in rows}
    return {coin: by_symbol[symbol(coin)] for coin in CRYPTO_COINS if symbol(coin) in by_symbol}


async def fetch_trading(session: aiohttp.ClientSession) -> set[str]:
    """The coins whose pair is trading right now. A halted pair keeps reporting its last, frozen price."""
    symbols = json.dumps([symbol(coin) for coin in CRYPTO_COINS], separators=(",", ":"))
    async with session.get(f"{API}/exchangeInfo", params={"symbols": symbols}) as reply:
        reply.raise_for_status()
        info = await reply.json()
    trading = {row["symbol"] for row in info["symbols"] if row.get("status") == "TRADING"}
    return {coin for coin in CRYPTO_COINS if symbol(coin) in trading}


async def fetch_history(session: aiohttp.ClientSession, coin: str) -> list[tuple[float, float]]:
    """The last hour of one coin as (time, closing price) of 1-minute candles."""
    async with session.get(f"{API}/klines", params={"symbol": symbol(coin), "interval": "1m", "limit": 60}) as reply:
        reply.raise_for_status()
        rows = await reply.json()
    now = time.time()
    # The last candle is still running (it closes in the future), so it's left out.
    return [(row[6] / 1000, float(row[4])) for row in rows if row[6] / 1000 <= now]


class PriceFeed:
    def __init__(self):
        self.points: dict[str, deque[tuple[float, float]]] = {coin: deque() for coin in CRYPTO_COINS}
        self.updated_at: float | None = None
        self.trading: set[str] = set(CRYPTO_COINS)  # checked at startup and every hour
        self.new_prices = asyncio.Condition()
        self.task: asyncio.Task | None = None

    def add(self, prices: dict[str, float], at: float):
        for coin, price in prices.items():
            points = self.points[coin]
            if points and points[-1][0] >= at:
                continue
            points.append((at, price))
            while points and points[0][0] < at - KEEP_SECONDS:
                points.popleft()
        if prices:
            self.updated_at = at

    def is_trading(self, coin: str) -> bool:
        return coin in self.trading

    def is_fresh(self, now: float | None = None) -> bool:
        return self.updated_at is not None and (now or time.time()) - self.updated_at <= FRESH_SECONDS

    def latest(self, coin: str) -> tuple[float, float] | None:
        points = self.points[coin]
        return points[-1] if points else None

    def since(self, coin: str, start: float) -> list[tuple[float, float]]:
        return [point for point in self.points[coin] if point[0] >= start]

    def first_after(self, coin: str, moment: float) -> tuple[float, float] | None:
        """The earliest known price at or after `moment` (newest points are at the end)."""
        found = None
        for point in reversed(self.points[coin]):
            if point[0] < moment:
                break
            found = point
        return found

    async def price_after(self, coin: str, moment: float, timeout: float) -> tuple[float, float] | None:
        """The first price seen at or after `moment`, waiting up to `timeout` seconds for it."""
        deadline = time.time() + timeout
        async with self.new_prices:
            while (point := self.first_after(coin, moment)) is None:
                left = deadline - time.time()
                if left <= 0:
                    return None
                try:
                    await asyncio.wait_for(self.new_prices.wait(), left)
                except asyncio.TimeoutError:
                    return None
        return point

    async def run(self):
        """Background task: keep the prices coming until the bot stops."""
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            for coin in CRYPTO_COINS:
                try:
                    for at, price in await fetch_history(session, coin):
                        self.add({coin: price}, at)
                except Exception as error:
                    logger.warning("Couldn't load the price history of %s: %s", coin, error)
            failures = 0
            checked_at = 0.0
            while True:
                if time.time() - checked_at >= STATUS_EVERY:
                    try:
                        trading = await fetch_trading(session)
                        if trading != self.trading:
                            logger.info("Crypto pairs not trading: %s", ", ".join(sorted(set(CRYPTO_COINS) - trading))
                                        or "none")
                        self.trading = trading
                        checked_at = time.time()
                    except Exception as error:
                        logger.warning("Couldn't check which crypto pairs are trading: %s", error)
                try:
                    prices = await fetch_prices(session)
                    async with self.new_prices:
                        self.add(prices, time.time())
                        self.new_prices.notify_all()
                    if failures:
                        logger.info("Crypto prices are back after %d failed request(s)", failures)
                    failures = 0
                except Exception as error:
                    failures += 1
                    if failures in (1, 10) or failures % 100 == 0:
                        logger.warning("Couldn't get crypto prices (%d in a row): %s", failures, error)
                await asyncio.sleep(POLL_SECONDS)

    def start(self):
        if self.task is None:
            self.task = asyncio.create_task(self.run())


feed = PriceFeed()
