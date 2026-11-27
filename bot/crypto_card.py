"""
Pictures for /crypto: the market overview and a bet's card (live, then its result), in the profile card's style.
Coins are shown as a letter in the coin's color, not their logos (those are other people's trademarks).
"""

import io
from dataclasses import dataclass

from PIL import Image, ImageDraw

from .profile_card import BACKGROUND_BOTTOM, BACKGROUND_TOP, MUTED, PANEL, SCALE as S, TEXT, _font

W = 1000
GREEN, RED, GOLD = (46, 204, 113), (231, 76, 60), (255, 206, 84)
GRID = (48, 46, 64)
EARLIER_LINE = (200, 196, 220)
COINS = {
    "BTC": ("Bitcoin", (247, 147, 26)), "ETH": ("Ethereum", (120, 140, 240)), "SOL": ("Solana", (160, 90, 255)),
    "BNB": ("BNB", (243, 186, 47)), "XRP": ("XRP", (170, 180, 200)), "DOGE": ("Dogecoin", (200, 170, 60)),
    "LINK": ("Chainlink", (55, 91, 210)), "AVAX": ("Avalanche", (232, 65, 66)), "SUI": ("Sui", (77, 162, 255)),
}
RESULT_COLORS = {"won": GREEN, "lost": RED, "push": MUTED}


@dataclass
class BetCard:
    coin: str
    up: bool
    bet: int
    minutes: int
    payout_if_won: int
    entry: float
    entry_at: float
    ends_at: float
    points: list[tuple[float, float]]   # (time, price) from a while before the bet up to now or the close
    now: float
    status: str = "open"                # open, won, lost or push
    close: float | None = None
    winnings: int = 0                   # coins won (won) or lost (lost)
    balance: int | None = None
    crowd: tuple[int, int] | None = None  # (bets on up, bets on down) lately, or None if too few to show


def price_text(price: float) -> str:
    if price >= 100:
        return f"${price:,.2f}"
    if price >= 1:
        return f"${price:,.4f}"
    if price >= 0.01:
        return f"${price:.5f}"
    return f"${price:.8f}"


def history_minutes(minutes: int) -> int:
    """How much of the chart comes before the bet."""
    return max(5, minutes * 4)


# ---------- drawing helpers (coordinates in final pixels) ----------

def _canvas(height: int) -> Image.Image:
    img = Image.new("RGBA", (W * S, height * S))
    draw = ImageDraw.Draw(img)
    for y in range(height * S):
        t = y / (height * S)
        draw.line([(0, y), (W * S, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(BACKGROUND_TOP, BACKGROUND_BOTTOM)))
    return img


def _png(img: Image.Image) -> bytes:
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, img.width - 1, img.height - 1), radius=28 * S, fill=255)
    img.putalpha(mask)
    img = img.resize((img.width // S, img.height // S), Image.LANCZOS)
    output = io.BytesIO()
    img.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _text(draw, xy, value, size, color=TEXT, weight="Bold", anchor="la"):
    draw.text((xy[0] * S, xy[1] * S), value, font=_font(size, weight), fill=color, anchor=anchor)


def _width(value: str, size: int, weight="Bold") -> float:
    return _font(size, weight).getlength(value) / S


def _panel(img, box, fill=PANEL, radius=18):
    layer = Image.new("RGBA", img.size)
    ImageDraw.Draw(layer).rounded_rectangle([v * S for v in box], radius=radius * S, fill=fill)
    img.alpha_composite(layer)


def _coin_badge(draw, x, y, r, coin):
    color = COINS[coin][1]
    draw.ellipse(((x - r) * S, (y - r) * S, (x + r) * S, (y + r) * S), fill=color)
    draw.ellipse(((x - r + 4) * S, (y - r + 4) * S, (x + r - 4) * S, (y + r - 4) * S), outline=(255, 255, 255, 90),
                 width=2 * S)
    _text(draw, (x, y), coin[0], int(r * 1.05), (255, 255, 255), anchor="mm")


def _arrow(draw, x, y, size, up, color):
    half = size / 2
    points = [(x, y - half), (x + half, y + half), (x - half, y + half)] if up else \
        [(x, y + half), (x + half, y - half), (x - half, y - half)]
    draw.polygon([(px * S, py * S) for px, py in points], fill=color)


def _pill(img, x, y, label, color, up, size=20, pad=14):
    width = _width(label, size) + pad * 2 + size + 6
    height = size + 18
    _panel(img, (x, y, x + width, y + height), fill=color + (60,), radius=height // 2)
    draw = ImageDraw.Draw(img)
    _arrow(draw, x + pad + size / 2 - 2, y + height / 2, size * 0.7, up, color)
    _text(draw, (x + pad + size + 6, y + height / 2), label, size, anchor="lm")


def _dashed(draw, start, end, color, dash=10, gap=8, width=2):
    (x0, y0), (x1, y1) = start, end
    length = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
    if not length:
        return
    position = 0.0
    while position < length:
        a, b = position / length, min(position + dash, length) / length
        draw.line([((x0 + (x1 - x0) * a) * S, (y0 + (y1 - y0) * a) * S),
                   ((x0 + (x1 - x0) * b) * S, (y0 + (y1 - y0) * b) * S)], fill=color, width=width * S)
        position += dash + gap


# ---------- the bet card ----------

def _bet_chart(img, box, card: BetCard):
    left, top, right, bottom = box
    start = card.entry_at - history_minutes(card.minutes) * 60
    end = card.ends_at
    points = [p for p in card.points if start <= p[0] <= max(end, card.now)]
    prices = [p for _, p in points] + [card.entry]
    lo, hi = min(prices), max(prices)
    span = (hi - lo) or card.entry * 0.001 or 1
    lo, hi = lo - span * 0.15, hi + span * 0.15

    def at(t, price):
        x = left + (right - left) * min(1.0, max(0.0, (t - start) / (end - start)))
        return x, bottom - (bottom - top) * (price - lo) / (hi - lo)

    draw = ImageDraw.Draw(img)
    for k in range(1, 4):
        y = top + (bottom - top) * k / 4
        draw.line([(left * S, y * S), (right * S, y * S)], fill=GRID, width=S)

    before = [at(t, p) for t, p in points if t < card.entry_at] + [at(card.entry_at, card.entry)]
    after = [at(card.entry_at, card.entry)] + [at(t, p) for t, p in points if t > card.entry_at]
    color = RESULT_COLORS.get(card.status, GOLD)

    if card.status != "open" and len(after) > 1:
        layer = Image.new("RGBA", img.size)
        area = after + [(after[-1][0], bottom), (after[0][0], bottom)]
        ImageDraw.Draw(layer).polygon([(x * S, y * S) for x, y in area], fill=color + (45,))
        img.alpha_composite(layer)
        draw = ImageDraw.Draw(img)

    if len(before) > 1:
        draw.line([(x * S, y * S) for x, y in before], fill=EARLIER_LINE, width=3 * S, joint="curve")
    if len(after) > 1:
        draw.line([(x * S, y * S) for x, y in after], fill=color, width=4 * S, joint="curve")

    entry_y = at(card.entry_at, card.entry)[1]
    _dashed(draw, (left, entry_y), (right, entry_y), (255, 255, 255, 120))
    ex, ey = at(card.entry_at, card.entry)
    draw.ellipse(((ex - 7) * S, (ey - 7) * S, (ex + 7) * S, (ey + 7) * S), fill=TEXT)

    nx, ny = after[-1]
    if card.status == "open":
        _dashed(draw, (right, top), (right, bottom), (255, 255, 255, 140), dash=8, gap=6)
        _text(draw, (right, top - 14), "FINISH", 13, MUTED, anchor="rm")
        glow = Image.new("RGBA", img.size)
        ImageDraw.Draw(glow).ellipse(((nx - 12) * S, (ny - 12) * S, (nx + 12) * S, (ny + 12) * S), fill=GOLD + (70,))
        img.alpha_composite(glow)
        draw = ImageDraw.Draw(img)
        draw.ellipse(((nx - 6) * S, (ny - 6) * S, (nx + 6) * S, (ny + 6) * S), fill=GOLD)
    elif len(after) > 1:
        draw.ellipse(((nx - 7) * S, (ny - 7) * S, (nx + 7) * S, (ny + 7) * S), fill=color)


def render_bet_card(card: BetCard) -> bytes:
    height = 540
    img = _canvas(height)
    draw = ImageDraw.Draw(img)
    name = COINS[card.coin][0]

    _coin_badge(draw, 72, 72, 32, card.coin)
    _text(draw, (118, 52), name.upper(), 30)
    _text(draw, (118, 92), f"{card.coin}/USDT · {card.minutes} min bet", 17, MUTED, "Medium", "lm")
    label = f"{'UP' if card.up else 'DOWN'} · {card.bet:,}"
    pays = f"pays {card.payout_if_won:,}"
    pill_x = W - 40 - _width(pays, 18, "SemiBold") - 30 - (_width(label, 20) + 54)
    _pill(img, pill_x, 54, label, GREEN if card.up else RED, card.up)
    draw = ImageDraw.Draw(img)
    _text(draw, (W - 40, 72), pays, 18, MUTED, "SemiBold", "rm")

    _panel(img, (40, 125, W - 40, 395))
    _bet_chart(img, (60, 150, W - 60, 375), card)
    draw = ImageDraw.Draw(img)

    last = card.close if card.close is not None else (card.points[-1][1] if card.points else card.entry)
    change = (last - card.entry) / card.entry * 100 if card.entry else 0.0
    color = GREEN if change > 0 else RED if change < 0 else MUTED
    _text(draw, (60, 425), "ENTRY", 14, MUTED, "SemiBold")
    _text(draw, (60, 448), price_text(card.entry), 24)
    _text(draw, (330, 425), "NOW" if card.status == "open" else "CLOSE", 14, MUTED, "SemiBold")
    _text(draw, (330, 448), price_text(last), 24)
    if change:
        _arrow(draw, 330 + _width(price_text(last), 24) + 22, 463, 14, change > 0, color)
    _text(draw, (330, 488), f"{change:+.3f}%", 17, color, "SemiBold")

    if card.status == "open":
        left = max(0, int(card.ends_at - card.now))
        _text(draw, (W - 60, 425), "TIME LEFT", 14, MUTED, "SemiBold", "ra")
        _text(draw, (W - 60, 448), f"{left // 60}:{left % 60:02d}", 30, GOLD, anchor="ra")
        if card.crowd:
            up, down = card.crowd
            share = up / (up + down)
            bar_left, bar_right, y = 600, W - 60, 500
            leader = f"{share:.0%} bet UP" if share >= 0.5 else f"{1 - share:.0%} bet DOWN"
            _text(draw, (bar_left, 488), f"{leader} on {card.coin} today", 14, MUTED, "SemiBold", "ls")
            draw.rounded_rectangle((bar_left * S, y * S, bar_right * S, (y + 10) * S), radius=5 * S, fill=RED)
            if share:
                draw.rounded_rectangle((bar_left * S, y * S, (bar_left + max(10, (bar_right - bar_left) * share)) * S,
                                        (y + 10) * S), radius=5 * S, fill=GREEN)
    else:
        big = {"won": f"WIN +{card.winnings:,}", "lost": f"LOSS −{card.winnings:,}", "push": "PUSH"}[card.status]
        _text(draw, (W - 60, 470), big, 46, RESULT_COLORS[card.status], anchor="rm")
        under = "Price didn't move: bet returned" if card.status == "push" else ""
        if card.balance is not None:
            under = (under + " · " if under else "") + f"Balance {card.balance:,}"
        _text(draw, (W - 60, 512), under, 16, MUTED, "Medium", "rm")
    return _png(img)


# ---------- the market overview ----------

def render_market_card(series: dict[str, list[tuple[float, float]]], paused: set[str] = frozenset()) -> bytes:
    """Every coin's price, its change over the series (the last hour) and a small chart. Paused coins say so."""
    cols = 3
    tile_w, tile_h, gap = 293, 120, 14
    rows = (len(series) + cols - 1) // cols
    height = 120 + rows * tile_h + (rows - 1) * gap + 40
    img = _canvas(height)
    draw = ImageDraw.Draw(img)
    _text(draw, (40, 46), "CRYPTO MARKET", 32)
    _text(draw, (40, 88), "Live prices · last hour · bet with /crypto bet", 17, MUTED, "Medium")
    _text(draw, (W - 40, 60), "LIVE", 18, GREEN, anchor="rm")
    dot_x = W - 40 - _width("LIVE", 18) - 16
    draw.ellipse(((dot_x - 6) * S, 54 * S, (dot_x + 6) * S, 66 * S), fill=GREEN)

    for n, (coin, points) in enumerate(series.items()):
        x = 40 + (n % cols) * (tile_w + gap)
        y = 120 + (n // cols) * (tile_h + gap)
        _panel(img, (x, y, x + tile_w, y + tile_h))
        draw = ImageDraw.Draw(img)
        _coin_badge(draw, x + 34, y + 36, 20, coin)
        _text(draw, (x + 64, y + 36), coin, 22, anchor="lm")
        if coin in paused:
            _text(draw, (x + tile_w - 16, y + 36), "PAUSED", 15, MUTED, "SemiBold", "rm")
            _text(draw, (x + 18, y + 88), "Trading paused on the exchange", 15, MUTED, "Medium", "lm")
            continue
        if not points:
            _text(draw, (x + 18, y + 88), "no price yet", 17, MUTED, "Medium", "lm")
            continue
        first, last = points[0][1], points[-1][1]
        change = (last - first) / first * 100 if first else 0.0
        color = GREEN if change >= 0 else RED
        _text(draw, (x + tile_w - 16, y + 36), f"{change:+.2f}%", 17, color, "SemiBold", "rm")
        _text(draw, (x + 18, y + 88), price_text(last), 19, TEXT, "SemiBold", "lm")
        if len(points) > 1:
            prices = [p for _, p in points]
            lo, hi = min(prices), max(prices)
            t0, t1 = points[0][0], points[-1][0]
            sx0, sx1, sy0, sy1 = x + 168, x + tile_w - 16, y + 70, y + 106
            line = [((sx0 + (sx1 - sx0) * (t - t0) / ((t1 - t0) or 1)) * S,
                     (sy1 - (sy1 - sy0) * (p - lo) / ((hi - lo) or 1)) * S) for t, p in points]
            draw.line(line, fill=color, width=2 * S, joint="curve")
    return _png(img)
