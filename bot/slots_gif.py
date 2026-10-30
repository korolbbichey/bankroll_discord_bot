"""
Draws a slots spin as an animated GIF with Pillow: a small casino machine with chasing lights.
Knows nothing about Discord or the database.

The reels spin and stop one by one, then the winning cells light up and the result is shown,
so the outcome is part of the animation. The GIF plays once.
"""

import io
import math
import random
from functools import lru_cache

from PIL import Image, ImageChops, ImageDraw, ImageFont

from .config import SLOT_SYMBOLS, SYMBOL_WEIGHTS
from .profile_card import ASSETS, FONT_FILE

WIDTH, HEIGHT = 460, 500
CELL = 96
ICON = 72
ICON_INSET = (CELL - ICON) // 2
REELS_LEFT = (WIDTH - 3 * CELL) // 2
REELS_TOP = 92
REELS_BOTTOM = REELS_TOP + 3 * CELL
REEL_GAP = 4

FRAME_MS = 60
STOP_FRAMES = (12, 17, 22)  # the frame each reel stops on, left to right
EXTRA_SYMBOLS = 12          # how many symbols scroll past before a reel lands
BLUR_ABOVE_SPEED = 30       # pixels per frame
WIN_FRAMES = 12
WIN_FRAME_MS = 70
BIG_WIN_MULTIPLIER = 10     # a payout of this many bets gets the coin shower
LAST_FRAME_MS = 4000

CABINET_TOP = (58, 16, 44)
CABINET_BOTTOM = (22, 8, 30)
GOLD_LIGHT = (255, 226, 130)
GOLD = (241, 196, 15)
GOLD_DARK = (150, 100, 20)
REEL_BG = (250, 246, 235)
BULB_ON = (255, 240, 170)
BULB_OFF = (96, 62, 50)
PLATE = (20, 8, 24)
MUTED = (190, 170, 190)
GREEN = (70, 230, 130)
RED = (255, 95, 85)
WIN_CELL = (255, 214, 90)

SYMBOL_ICONS = {"\U0001f34b": "1f34b", "\U0001f352": "1f352", "\U0001f349": "1f349",
                "\U0001f514": "1f514", "⭐": "2b50", "\U0001f48e": "1f48e"}
COIN_ICON = "1fa99"

_WEIGHTS = [SYMBOL_WEIGHTS[s] for s in SLOT_SYMBOLS]


def animation_seconds(has_winning_lines: bool) -> float:
    """How long the GIF takes to reach its result, including the win effects."""
    spin = (STOP_FRAMES[-1] + 1) * FRAME_MS
    win = WIN_FRAMES * WIN_FRAME_MS if has_winning_lines else 0
    return (spin + win) / 1000


@lru_cache(maxsize=None)
def _icon(symbol: str) -> Image.Image:
    with Image.open(ASSETS / "icons" / f"{SYMBOL_ICONS[symbol]}.png") as icon:
        return icon.convert("RGBA").resize((ICON, ICON), Image.LANCZOS)


@lru_cache(maxsize=None)
def _blurred_icon(symbol: str) -> Image.Image:
    """The icon smeared vertically, for a reel moving fast."""
    icon = _icon(symbol)
    steps = 6
    pad = 30
    result = Image.new("RGBA", (ICON, ICON + pad), (0, 0, 0, 0))
    for step in range(steps):
        layer = Image.new("RGBA", result.size, (0, 0, 0, 0))
        layer.paste(icon, (0, step * pad // (steps - 1)))
        result = Image.blend(result, layer, 1 / (step + 1))
    return result


@lru_cache(maxsize=None)
def _coin(size: int) -> Image.Image:
    with Image.open(ASSETS / "icons" / f"{COIN_ICON}.png") as icon:
        return icon.convert("RGBA").resize((size, size), Image.LANCZOS)


@lru_cache(maxsize=None)
def _font(size: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(FONT_FILE), size)
    font.set_variation_by_name("ExtraBold")
    return font


def _vertical_gradient(size: tuple[int, int], top: tuple, bottom: tuple) -> Image.Image:
    """A vertical gradient. Colors may include alpha."""
    width, height = size
    channels = len(top)
    column = Image.new("RGBA" if channels == 4 else "RGB", (1, height))
    for y in range(height):
        t = y / max(1, height - 1)
        column.putpixel((0, y), tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))
    return column.resize((width, height))


def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    """A smooth rounded rectangle mask."""
    width, height = size
    mask = Image.new("L", (width * 4, height * 4), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width * 4 - 1, height * 4 - 1), radius=radius * 4, fill=255)
    return mask.resize((width, height), Image.LANCZOS)


def _paste_gold_plate(frame: Image.Image, box: tuple[int, int, int, int], radius: int, border: int = 4):
    """A dark plate with a metallic gold border."""
    left, top, right, bottom = box
    size = (right - left, bottom - top)
    gold = _vertical_gradient(size, GOLD_LIGHT, GOLD_DARK)
    frame.paste(gold, (left, top), _rounded_mask(size, radius))
    inner = (size[0] - 2 * border, size[1] - 2 * border)
    frame.paste(Image.new("RGB", inner, PLATE), (left + border, top + border), _rounded_mask(inner, max(1, radius - border)))


def _bulb_positions() -> list[tuple[int, int]]:
    """Evenly spaced points along the cabinet edge, clockwise."""
    inset, step = 13, 37
    left, top, right, bottom = inset, inset, WIDTH - inset, HEIGHT - inset
    points = []
    points += [(x, top) for x in range(left + 12, right - 6, step)]
    points += [(right, y) for y in range(top + 12, bottom - 6, step)]
    points += [(x, bottom) for x in range(right - 12, left + 6, -step)]
    points += [(left, y) for y in range(bottom - 12, top + 6, -step)]
    return points


@lru_cache(maxsize=None)
def _cabinet(phase: int) -> Image.Image:
    """The machine without reel contents. The lights chase in three phases."""
    frame = _vertical_gradient((WIDTH, HEIGHT), CABINET_TOP, CABINET_BOTTOM)

    # Gold frame around the cabinet
    gold = _vertical_gradient((WIDTH, HEIGHT), GOLD_LIGHT, GOLD_DARK)
    ring = Image.new("L", (WIDTH * 2, HEIGHT * 2), 0)
    ring_draw = ImageDraw.Draw(ring)
    ring_draw.rounded_rectangle((8, 8, WIDTH * 2 - 9, HEIGHT * 2 - 9), radius=44, fill=255)
    ring_draw.rounded_rectangle((48, 48, WIDTH * 2 - 49, HEIGHT * 2 - 49), radius=26, fill=0)
    frame.paste(gold, (0, 0), ring.resize((WIDTH, HEIGHT), Image.LANCZOS))

    # Lights: drawn large and shrunk, so they stay round
    lights = Image.new("RGBA", (WIDTH * 2, HEIGHT * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(lights)
    for index, (x, y) in enumerate(_bulb_positions()):
        lit = index % 3 == phase
        if lit:
            draw.ellipse(((x - 10) * 2, (y - 10) * 2, (x + 10) * 2, (y + 10) * 2), fill=BULB_ON + (70,))
        color = BULB_ON if lit else BULB_OFF
        draw.ellipse(((x - 5) * 2, (y - 5) * 2, (x + 5) * 2, (y + 5) * 2), fill=color + (255,))
    frame.paste(lights.resize((WIDTH, HEIGHT), Image.LANCZOS), (0, 0), lights.resize((WIDTH, HEIGHT), Image.LANCZOS))

    # Sign
    _paste_gold_plate(frame, (REELS_LEFT, 32, REELS_LEFT + 3 * CELL, 80), radius=12)
    text = Image.new("L", (WIDTH, HEIGHT), 0)
    ImageDraw.Draw(text).text((WIDTH / 2, 56), "BANKROLL", font=_font(28), fill=255, anchor="mm")
    frame.paste(_vertical_gradient((WIDTH, HEIGHT), GOLD_LIGHT, GOLD_LIGHT), (0, 0), text)

    # Reel surround and the result plate
    _paste_gold_plate(frame, (REELS_LEFT - 8, REELS_TOP - 8, REELS_LEFT + 3 * CELL + 8, REELS_BOTTOM + 8), radius=14)
    _paste_gold_plate(frame, (REELS_LEFT - 8, REELS_BOTTOM + 18, REELS_LEFT + 3 * CELL + 8, REELS_BOTTOM + 72), radius=14)

    # Empty reels
    reel_size = (CELL - REEL_GAP, 3 * CELL)
    for col in range(3):
        frame.paste(Image.new("RGB", reel_size, REEL_BG), (REELS_LEFT + col * CELL + REEL_GAP // 2, REELS_TOP),
                    _rounded_mask(reel_size, 8))
    return frame


@lru_cache(maxsize=None)
def _reel_shade() -> Image.Image:
    """Darkens the top and bottom of the reels so they read as cylinders."""
    size = (3 * CELL, 3 * CELL)
    fade = 70
    shade = Image.new("RGBA", size, (0, 0, 0, 0))
    shade.paste(_vertical_gradient((size[0], fade), (20, 8, 24, 190), (20, 8, 24, 0)), (0, 0))
    shade.paste(_vertical_gradient((size[0], fade), (20, 8, 24, 0), (20, 8, 24, 190)), (0, size[1] - fade))
    return shade


def _paste_clipped(target: Image.Image, icon: Image.Image, x: int, y: int):
    """alpha_composite can't start above the image, so cut off what doesn't fit."""
    if y < 0:
        if y + icon.height <= 0:
            return
        icon, y = icon.crop((0, -y, icon.width, icon.height)), 0
    if y < target.height:
        target.alpha_composite(icon.crop((0, 0, icon.width, min(icon.height, target.height - y))), (x, y))


def _reel_window(strip: list[str], progress: float, blurred: bool) -> Image.Image:
    """One reel's contents. progress goes from 0 (start of the strip) to 1 (landed), slightly past 1 on the bounce."""
    offset = CELL * (len(strip) - 3) * (1 - progress)
    first = math.floor(offset / CELL)
    shift = int(offset - first * CELL)  # how far below its slot the top symbol has moved

    window = Image.new("RGBA", (CELL, 3 * CELL), (0, 0, 0, 0))
    for row in range(-1, 3):
        index = len(strip) - 3 - first + row
        if not 0 <= index < len(strip):
            continue
        icon = _blurred_icon(strip[index]) if blurred else _icon(strip[index])
        _paste_clipped(window, icon, ICON_INSET, row * CELL + shift + ICON_INSET)
    return window


def _ease_out_back(t: float) -> float:
    """Slows down, goes slightly past the end, and settles: the reel's bounce."""
    overshoot = 0.5
    return 1 + (overshoot + 1) * (t - 1) ** 3 + overshoot * (t - 1) ** 2


def _reel_progress(number: int, stop_frame: int) -> float:
    return 1.0 if number >= stop_frame else _ease_out_back(number / stop_frame)


def _caption(frame: Image.Image, text: str, color: tuple[int, int, int], size: int = 30):
    center = (WIDTH / 2, REELS_BOTTOM + 45)
    draw = ImageDraw.Draw(frame)
    draw.text((center[0], center[1] + 2), text, font=_font(size), fill=(0, 0, 0), anchor="mm")
    draw.text(center, text, font=_font(size), fill=color, anchor="mm")


def _result_caption(payout: int, bet: int) -> tuple[str, tuple[int, int, int]]:
    if payout >= bet * BIG_WIN_MULTIPLIER:
        return f"BIG WIN +{payout - bet:,}", GOLD_LIGHT
    if payout > bet:
        return f"YOU WON +{payout - bet:,}", GREEN
    if payout == bet:
        return "BET RETURNED", GOLD_LIGHT
    return f"YOU LOST {bet:,}", RED


def _draw_sparkle(draw: ImageDraw.ImageDraw, x: float, y: float, size: float):
    """A four-pointed star."""
    inner = size / 4
    points = [(x, y - size), (x + inner, y - inner), (x + size, y), (x + inner, y + inner),
              (x, y + size), (x - inner, y + inner), (x - size, y), (x - inner, y - inner)]
    draw.polygon(points, fill=(255, 250, 215))


def _reels_frame(windows: list[Image.Image], phase: int, highlight: set[tuple[int, int]] = frozenset(),
                 glow: float = 0.0) -> Image.Image:
    frame = _cabinet(phase).convert("RGBA")
    for row, col in highlight:
        x, y = REELS_LEFT + col * CELL + REEL_GAP // 2, REELS_TOP + row * CELL
        size = (CELL - REEL_GAP - 6, CELL - 6)
        cell = Image.new("RGBA", size, WIN_CELL + (int(120 + 135 * glow),))
        frame.paste(cell, (x + 3, y + 3), _rounded_mask(size, 10))
    for col, window in enumerate(windows):
        frame.alpha_composite(window, (REELS_LEFT + col * CELL, REELS_TOP))
    frame.alpha_composite(_reel_shade(), (REELS_LEFT, REELS_TOP))
    return frame


def render_spin_gif(grid: list[list[str]], winning_cells: set[tuple[int, int]], bet: int, payout: int,
                    seed: int | None = None) -> bytes:
    """Draw a spin that lands on grid (3 rows of 3 symbols). winning_cells holds (row, column) pairs."""
    rng = random.Random(seed)
    strips = [rng.choices(SLOT_SYMBOLS, weights=_WEIGHTS, k=EXTRA_SYMBOLS) + [grid[row][col] for row in range(3)]
              for col in range(3)]
    travel = CELL * EXTRA_SYMBOLS
    frames, durations = [], []

    # ---------- spinning ----------
    for number in range(STOP_FRAMES[-1] + 1):
        windows = []
        for col in range(3):
            progress = _reel_progress(number, STOP_FRAMES[col])
            speed = abs(progress - _reel_progress(number + 1, STOP_FRAMES[col])) * travel
            windows.append(_reel_window(strips[col], progress, speed > BLUR_ABOVE_SPEED))
        frame = _reels_frame(windows, number % 3)
        _caption(frame, "SPINNING...", MUTED, 22)
        frames.append(frame)
        durations.append(FRAME_MS)

    # ---------- result ----------
    final = [_reel_window(strips[col], 1.0, False) for col in range(3)]
    text, color = _result_caption(payout, bet)

    if winning_cells:
        big_win = payout >= bet * BIG_WIN_MULTIPLIER
        sparkles = [(rng.randint(40, WIDTH - 40), rng.randint(90, REELS_BOTTOM), rng.randrange(WIN_FRAMES))
                    for _ in range(14)]
        coins = [(rng.randint(30, WIDTH - 60), rng.randint(-160, -30), rng.randint(14, 30)) for _ in range(16)]
        for number in range(WIN_FRAMES):
            frame = _reels_frame(final, number % 3, winning_cells, glow=(math.sin(number * 1.1) + 1) / 2)
            draw = ImageDraw.Draw(frame)
            for x, y, start in sparkles:
                age = (number - start) % WIN_FRAMES
                if age < 4:
                    _draw_sparkle(draw, x, y, [4, 11, 7, 3][age])
            if big_win:
                for x, y, speed in coins:
                    _paste_clipped(frame, _coin(26), x, y + number * speed)
            _caption(frame, text, color)
            frames.append(frame)
            durations.append(WIN_FRAME_MS)

    last = _reels_frame(final, 0, winning_cells, glow=1.0 if winning_cells else 0.0)
    _caption(last, text, color)
    frames.append(last)
    durations.append(LAST_FRAME_MS)

    # One palette built from several frames keeps the colors stable between them.
    samples = [frames[0], frames[len(frames) // 2], frames[-2], last]
    sheet = Image.new("RGB", (WIDTH * len(samples), HEIGHT))
    for index, sample in enumerate(samples):
        sheet.paste(sample.convert("RGB"), (index * WIDTH, 0))
    palette = sheet.quantize(colors=200, method=Image.MEDIANCUT, dither=Image.NONE)
    converted = [frame.convert("RGB").quantize(palette=palette, dither=Image.NONE) for frame in frames]

    output = io.BytesIO()
    # No loop option: the GIF plays once.
    converted[0].save(output, format="GIF", save_all=True, append_images=converted[1:],
                      duration=durations, optimize=False, disposal=1)
    return output.getvalue()
