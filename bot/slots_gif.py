"""
Draws a slots spin as an animated GIF with Pillow. Knows nothing about Discord or the database.

The reels spin and stop one by one, then the winning cells flash and the result is shown,
so the outcome is part of the animation. The GIF plays once.
"""

import io
import random
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from .config import SLOT_SYMBOLS, SYMBOL_WEIGHTS
from .profile_card import ASSETS, FONT_FILE

WIDTH, HEIGHT = 420, 390
CELL = 100
ICON = 72
ICON_INSET = (CELL - ICON) // 2
REELS_LEFT = (WIDTH - 3 * CELL) // 2
REELS_TOP = 24

FRAME_MS = 60
STOP_FRAMES = (12, 17, 22)  # the frame each reel stops on, left to right
EXTRA_SYMBOLS = 12          # how many symbols scroll past before a reel lands
FLASHES = 3
FLASH_ON_MS, FLASH_OFF_MS = 160, 110
LAST_FRAME_MS = 4000

BACKGROUND = (19, 18, 30)
REEL_BG = (32, 30, 48)
REEL_BORDER = (70, 66, 100)
MUTED = (150, 146, 170)
GREEN = (46, 204, 113)
GOLD = (241, 196, 15)
RED = (231, 76, 60)
HIGHLIGHT = (70, 60, 30)

SYMBOL_ICONS = {"\U0001f34b": "1f34b", "\U0001f352": "1f352", "\U0001f349": "1f349",
                "\U0001f514": "1f514", "⭐": "2b50", "\U0001f48e": "1f48e"}

_WEIGHTS = [SYMBOL_WEIGHTS[s] for s in SLOT_SYMBOLS]


def animation_seconds(has_winning_lines: bool) -> float:
    """How long the GIF takes to reach its result, including the flashes on a win."""
    spin = (STOP_FRAMES[-1] + 1) * FRAME_MS
    flashes = FLASHES * (FLASH_ON_MS + FLASH_OFF_MS) if has_winning_lines else 0
    return (spin + flashes) / 1000


@lru_cache(maxsize=None)
def _icon(symbol: str) -> Image.Image:
    with Image.open(ASSETS / "icons" / f"{SYMBOL_ICONS[symbol]}.png") as icon:
        return icon.convert("RGBA").resize((ICON, ICON), Image.LANCZOS)


@lru_cache(maxsize=None)
def _font(size: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(FONT_FILE), size)
    font.set_variation_by_name("ExtraBold")
    return font


def _base_frame() -> Image.Image:
    frame = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(frame)
    for col in range(3):
        x = REELS_LEFT + col * CELL
        draw.rounded_rectangle((x + 3, REELS_TOP, x + CELL - 4, REELS_TOP + 3 * CELL - 1), radius=14,
                               fill=REEL_BG, outline=REEL_BORDER, width=2)
    return frame


def _draw_reel(frame: Image.Image, strip: list[str], col: int, progress: float):
    """Draw one reel, clipped to its window. progress goes from 0 (start of the strip) to 1 (landed)."""
    offset = CELL * (len(strip) - 3) * (1 - progress)
    first = int(offset // CELL)
    shift = int(offset - first * CELL)  # how far below its slot the top symbol has moved

    window = Image.new("RGBA", (CELL, 3 * CELL), (0, 0, 0, 0))
    for row in range(-1, 3):
        index = len(strip) - 3 - first + row
        y = row * CELL + shift + ICON_INSET
        if not 0 <= index < len(strip) or y + ICON <= 0 or y >= 3 * CELL:
            continue
        icon = _icon(strip[index])
        if y < 0:  # alpha_composite can't start above the window
            icon, y = icon.crop((0, -y, ICON, ICON)), 0
        window.alpha_composite(icon, (ICON_INSET, y))
    frame.paste(window, (REELS_LEFT + col * CELL, REELS_TOP), window)


def _ease_out(t: float) -> float:
    return 1 - (1 - t) ** 3


def _caption(frame: Image.Image, text: str, color: tuple[int, int, int], size: int = 28):
    ImageDraw.Draw(frame).text((WIDTH / 2, REELS_TOP + 3 * CELL + 36), text, font=_font(size), fill=color, anchor="mm")


def _result_caption(payout: int, bet: int) -> tuple[str, tuple[int, int, int]]:
    if payout > bet:
        return f"YOU WON +{payout - bet:,}", GREEN
    if payout == bet:
        return "BET RETURNED", GOLD
    return f"YOU LOST {bet:,}", RED


def render_spin_gif(grid: list[list[str]], winning_cells: set[tuple[int, int]], bet: int, payout: int,
                    seed: int | None = None) -> bytes:
    """Draw a spin that lands on grid (3 rows of 3 symbols). winning_cells holds (row, column) pairs."""
    rng = random.Random(seed)
    strips = [rng.choices(SLOT_SYMBOLS, weights=_WEIGHTS, k=EXTRA_SYMBOLS) + [grid[row][col] for row in range(3)]
              for col in range(3)]
    base = _base_frame()
    frames, durations = [], []

    for number in range(STOP_FRAMES[-1] + 1):
        frame = base.copy()
        for col in range(3):
            _draw_reel(frame, strips[col], col, min(1.0, _ease_out(number / STOP_FRAMES[col])))
        _caption(frame, "SPINNING...", MUTED, 22)
        frames.append(frame)
        durations.append(FRAME_MS)

    text, color = _result_caption(payout, bet)

    def result_frame(highlighted: bool) -> Image.Image:
        frame = base.copy()
        draw = ImageDraw.Draw(frame)
        if highlighted:
            for row, col in winning_cells:
                x, y = REELS_LEFT + col * CELL, REELS_TOP + row * CELL
                draw.rounded_rectangle((x + 7, y + 4, x + CELL - 8, y + CELL - 5), radius=12,
                                       fill=HIGHLIGHT, outline=GOLD, width=3)
        for row in range(3):
            for col in range(3):
                icon = _icon(grid[row][col])
                frame.paste(icon, (REELS_LEFT + col * CELL + ICON_INSET, REELS_TOP + row * CELL + ICON_INSET), icon)
        _caption(frame, text, color)
        return frame

    last = result_frame(bool(winning_cells))
    if winning_cells:
        dark = result_frame(False)
        for _ in range(FLASHES):
            frames += [last, dark]
            durations += [FLASH_ON_MS, FLASH_OFF_MS]
    frames.append(last)
    durations.append(LAST_FRAME_MS)

    # One palette built from a spinning and a final frame keeps the file small and the colors stable.
    sheet = Image.new("RGB", (WIDTH * 2, HEIGHT))
    sheet.paste(frames[0], (0, 0))
    sheet.paste(last, (WIDTH, 0))
    palette = sheet.quantize(colors=128, method=Image.MEDIANCUT, dither=Image.NONE)
    converted = [frame.quantize(palette=palette, dither=Image.NONE) for frame in frames]

    output = io.BytesIO()
    # No loop option: the GIF plays once.
    converted[0].save(output, format="GIF", save_all=True, append_images=converted[1:],
                      duration=durations, optimize=False, disposal=1)
    return output.getvalue()
