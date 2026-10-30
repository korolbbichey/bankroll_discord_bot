"""
Draws the blackjack table as a PNG with Pillow, in the same style as the slot machine.
Knows nothing about Discord or the database. A new picture is drawn for every action in the game.
"""

import io
from functools import lru_cache

from PIL import Image, ImageDraw

from .profile_card import ASSETS
from .slots_gif import GOLD_DARK, GOLD_LIGHT, MUTED, _font, _paste_gold_plate, _rounded_mask, _vertical_gradient

WIDTH, HEIGHT = 640, 560
CARD_W, CARD_H = 92, 130
CARD_GAP = 12
MIN_STEP = 40  # cards overlap down to this spacing when a hand gets long
DEALER_Y, PLAYER_Y = 112, 298

FELT_TOP = (18, 96, 66)
FELT_BOTTOM = (8, 54, 40)
CARD_FACE = (252, 250, 244)
CARD_EDGE = (190, 186, 176)
INK_BLACK = (28, 26, 34)
INK_RED = (205, 40, 50)
CARD_BACK = (122, 24, 48)
CARD_BACK_LINE = (214, 170, 80)
PILL = (6, 36, 28)
TEXT = (240, 238, 248)

SUIT_ICONS = {"♠": "2660", "♥": "2665", "♦": "2666", "♣": "2663"}


@lru_cache(maxsize=None)
def _table() -> Image.Image:
    frame = _vertical_gradient((WIDTH, HEIGHT), FELT_TOP, FELT_BOTTOM)
    gold = _vertical_gradient((WIDTH, HEIGHT), GOLD_LIGHT, GOLD_DARK)
    ring = Image.new("L", (WIDTH * 2, HEIGHT * 2), 0)
    draw = ImageDraw.Draw(ring)
    draw.rounded_rectangle((8, 8, WIDTH * 2 - 9, HEIGHT * 2 - 9), radius=44, fill=255)
    draw.rounded_rectangle((32, 32, WIDTH * 2 - 33, HEIGHT * 2 - 33), radius=30, fill=0)
    frame.paste(gold, (0, 0), ring.resize((WIDTH, HEIGHT), Image.LANCZOS))

    _paste_gold_plate(frame, (WIDTH // 2 - 120, 26, WIDTH // 2 + 120, 72), radius=12)
    sign = Image.new("L", (WIDTH, HEIGHT), 0)
    ImageDraw.Draw(sign).text((WIDTH / 2, 49), "BLACKJACK", font=_font(24), fill=255, anchor="mm")
    frame.paste(Image.new("RGB", (WIDTH, HEIGHT), GOLD_LIGHT), (0, 0), sign)

    _paste_gold_plate(frame, (32, HEIGHT - 84, WIDTH - 32, HEIGHT - 28), radius=14)
    return frame


@lru_cache(maxsize=None)
def _suit(suit: str, size: int) -> Image.Image:
    with Image.open(ASSETS / "icons" / f"{SUIT_ICONS[suit]}.png") as icon:
        return icon.convert("RGBA").resize((size, size), Image.LANCZOS)


def _card_base(fill: tuple) -> Image.Image:
    card = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    card.paste(Image.new("RGB", (CARD_W, CARD_H), CARD_EDGE), (0, 0), _rounded_mask((CARD_W, CARD_H), 10))
    inner = (CARD_W - 4, CARD_H - 4)
    card.paste(Image.new("RGB", inner, fill), (2, 2), _rounded_mask(inner, 9))
    return card


@lru_cache(maxsize=None)
def _card(rank: str, suit: str) -> Image.Image:
    card = _card_base(CARD_FACE)
    draw = ImageDraw.Draw(card)
    color = INK_RED if suit in "♥♦" else INK_BLACK
    draw.text((10, 6), rank, font=_font(24), fill=color)
    card.alpha_composite(_suit(suit, 18), (10, 36))
    card.alpha_composite(_suit(suit, 50), ((CARD_W - 50) // 2 + 6, (CARD_H - 50) // 2 + 16))
    return card


@lru_cache(maxsize=None)
def _card_back() -> Image.Image:
    card = _card_base(CARD_BACK)
    draw = ImageDraw.Draw(card)
    draw.rounded_rectangle((8, 8, CARD_W - 9, CARD_H - 9), radius=6, outline=CARD_BACK_LINE, width=2)
    for offset in range(-CARD_H, CARD_W, 14):
        draw.line((offset, 12, offset + CARD_H - 24, CARD_H - 12), fill=CARD_BACK_LINE + (70,), width=1)
    draw.rounded_rectangle((8, 8, CARD_W - 9, CARD_H - 9), radius=6, outline=CARD_BACK_LINE, width=2)
    mask = Image.new("L", (CARD_W, CARD_H), 0)
    ImageDraw.Draw(mask).rounded_rectangle((10, 10, CARD_W - 11, CARD_H - 11), radius=5, fill=255)
    plain = _card_base(CARD_BACK)
    ImageDraw.Draw(plain).rounded_rectangle((8, 8, CARD_W - 9, CARD_H - 9), radius=6, outline=CARD_BACK_LINE, width=2)
    return Image.composite(card, plain, mask)


def _draw_hand(frame: Image.Image, hand: list[tuple[str, str]], y: int, hide_second: bool):
    count = len(hand)
    step = CARD_W + CARD_GAP
    available = WIDTH - 2 * 44 - CARD_W
    if count > 1:
        step = max(MIN_STEP, min(step, available // (count - 1)))
    total = CARD_W + step * (count - 1)
    x = (WIDTH - total) // 2
    for index, (rank, suit) in enumerate(hand):
        card = _card_back() if hide_second and index == 1 else _card(rank, suit)
        frame.alpha_composite(card, (x + index * step, y))


def _draw_label(frame: Image.Image, text: str, y: int):
    draw = ImageDraw.Draw(frame)
    font = _font(15)
    width = int(font.getlength(text)) + 24
    left = (WIDTH - width) // 2
    draw.rounded_rectangle((left, y, left + width, y + 26), radius=13, fill=PILL + (255,))
    draw.text((WIDTH / 2, y + 13), text, font=font, fill=TEXT, anchor="mm")


def render_table(player: list[tuple[str, str]], dealer: list[tuple[str, str]], player_value: int,
                 dealer_value: int | None, status: str, status_color: tuple[int, int, int],
                 hide_dealer: bool = False) -> bytes:
    """Draw the table. With hide_dealer the dealer's second card is face down and dealer_value isn't shown."""
    frame = _table().convert("RGBA")
    _draw_label(frame, "DEALER" if dealer_value is None else f"DEALER · {dealer_value}", DEALER_Y - 32)
    _draw_hand(frame, dealer, DEALER_Y, hide_dealer)
    _draw_label(frame, f"YOU · {player_value}", PLAYER_Y - 32)
    _draw_hand(frame, player, PLAYER_Y, False)

    draw = ImageDraw.Draw(frame)
    center = (WIDTH / 2, HEIGHT - 56)
    draw.text((center[0], center[1] + 2), status, font=_font(26), fill=(0, 0, 0), anchor="mm")
    draw.text(center, status, font=_font(26), fill=status_color, anchor="mm")

    output = io.BytesIO()
    frame.convert("RGB").save(output, format="PNG", optimize=True)
    return output.getvalue()
