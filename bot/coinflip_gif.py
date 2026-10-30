"""
Draws a coin flip as an animated GIF with Pillow, in the same style as the slot machine.
Knows nothing about Discord or the database. The result is part of the animation; the GIF plays once.

The coin looks three-dimensional: it has an edge that shows while it turns, a metallic face
whose brightness follows the rotation, and a soft shadow on a round table.
"""

import io
import math
import random
from functools import lru_cache

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from .slots_gif import (
    CABINET_BOTTOM, CABINET_TOP, GOLD_DARK, GOLD_LIGHT, GREEN, LAST_FRAME_MS, MUTED, RED,
    _draw_sparkle, _font, _paste_gold_plate, _vertical_gradient,
)

WIDTH, HEIGHT = 400, 440
COIN_SIZE = 140
EDGE_DEPTH = 16       # how thick the coin looks when seen from the side
FLOOR_Y = 268         # where the coin rests (its center)
FLIP_HEIGHT = 112     # how high it rises
FRAMES = 20
FRAME_MS = 70
TURNS = 4             # full rotations
BOUNCE_FRAMES = 4
BOUNCE_HEIGHT = 16
WIN_FRAMES = 7
WIN_FRAME_MS = 90

TABLE_Y = FLOOR_Y + COIN_SIZE // 2 + 2
FELT_LIGHT = (24, 112, 78)
FELT_DARK = (10, 66, 48)
EDGE_LIGHT = (214, 156, 44)
EDGE_DARK = (120, 74, 14)


def animation_seconds(won: bool) -> float:
    """How long the GIF takes to reach its result, including the win sparkles."""
    spin = (FRAMES + BOUNCE_FRAMES) * FRAME_MS
    return (spin + (WIN_FRAMES * WIN_FRAME_MS if won else 0)) / 1000


@lru_cache(maxsize=None)
def _background() -> Image.Image:
    frame = _vertical_gradient((WIDTH, HEIGHT), CABINET_TOP, CABINET_BOTTOM)

    # A pool of light from above, falling on a round felt table with a gold rim
    light = Image.new("L", (WIDTH * 2, HEIGHT * 2), 0)
    ImageDraw.Draw(light).polygon(
        [(WIDTH - 90, 130), (WIDTH + 90, 130), (WIDTH + 330, TABLE_Y * 2), (WIDTH - 330, TABLE_Y * 2)], fill=46)
    light = light.filter(ImageFilter.GaussianBlur(36)).resize((WIDTH, HEIGHT), Image.LANCZOS)
    frame.paste(Image.new("RGB", (WIDTH, HEIGHT), (255, 226, 170)), (0, 0), light)

    scale = 3
    table = Image.new("RGBA", (WIDTH * scale, HEIGHT * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(table)
    left, right = 34 * scale, (WIDTH - 34) * scale
    top, bottom = (TABLE_Y - 34) * scale, (TABLE_Y + 36) * scale
    draw.ellipse((left, top + 10 * scale, right, bottom + 10 * scale), fill=(60, 34, 14, 255))
    draw.ellipse((left, top, right, bottom), fill=GOLD_DARK + (255,))
    draw.ellipse((left + 3 * scale, top + 2 * scale, right - 3 * scale, bottom - 2 * scale), fill=GOLD_LIGHT + (255,))
    draw.ellipse((left + 8 * scale, top + 5 * scale, right - 8 * scale, bottom - 5 * scale), fill=FELT_DARK + (255,))
    draw.ellipse((left + 40 * scale, top + 9 * scale, right - 40 * scale, bottom - 12 * scale), fill=FELT_LIGHT + (255,))
    table = table.resize((WIDTH, HEIGHT), Image.LANCZOS)
    frame.paste(table, (0, 0), table)

    gold = _vertical_gradient((WIDTH, HEIGHT), GOLD_LIGHT, GOLD_DARK)
    ring = Image.new("L", (WIDTH * 2, HEIGHT * 2), 0)
    draw = ImageDraw.Draw(ring)
    draw.rounded_rectangle((8, 8, WIDTH * 2 - 9, HEIGHT * 2 - 9), radius=44, fill=255)
    draw.rounded_rectangle((28, 28, WIDTH * 2 - 29, HEIGHT * 2 - 29), radius=30, fill=0)
    frame.paste(gold, (0, 0), ring.resize((WIDTH, HEIGHT), Image.LANCZOS))

    _paste_gold_plate(frame, (70, 24, WIDTH - 70, 68), radius=12)
    sign = Image.new("L", (WIDTH, HEIGHT), 0)
    ImageDraw.Draw(sign).text((WIDTH / 2, 46), "COIN FLIP", font=_font(24), fill=255, anchor="mm")
    frame.paste(Image.new("RGB", (WIDTH, HEIGHT), GOLD_LIGHT), (0, 0), sign)
    _paste_gold_plate(frame, (32, HEIGHT - 72, WIDTH - 32, HEIGHT - 22), radius=14)
    return frame


@lru_cache(maxsize=None)
def _coin_face(face: str) -> Image.Image:
    """The coin seen head-on, with a reeded rim, a metallic face and a raised letter."""
    size = COIN_SIZE * 3
    center = size / 2

    # Metal: light from the upper left, darker to the lower right
    diagonal = Image.linear_gradient("L").resize((size, size)).rotate(45, resample=Image.BILINEAR, expand=False)
    metal = Image.merge("RGB", [diagonal.point(lambda v, a=a, b=b: a + (b - a) * v // 255)
                                for a, b in zip((255, 236, 150), (190, 128, 24))])
    coin = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    coin.paste(metal, (0, 0), mask)
    draw = ImageDraw.Draw(coin)

    # Reeded rim
    for tick in range(72):
        angle = tick * 2 * math.pi / 72
        inner, outer = center - 22, center - 2
        draw.line((center + inner * math.cos(angle), center + inner * math.sin(angle),
                   center + outer * math.cos(angle), center + outer * math.sin(angle)),
                  fill=(150, 98, 18, 255), width=4)

    # The recessed middle, in the opposite light direction, which makes it look sunken
    inset = 30
    inner_size = size - 2 * inset
    recess = metal.rotate(180).resize((inner_size, inner_size))
    recess = ImageEnhance.Brightness(recess).enhance(0.93)
    recess_mask = Image.new("L", (inner_size, inner_size), 0)
    ImageDraw.Draw(recess_mask).ellipse((0, 0, inner_size - 1, inner_size - 1), fill=255)
    coin.paste(recess, (inset, inset), recess_mask)
    draw.ellipse((inset, inset, size - inset - 1, size - inset - 1), outline=(136, 88, 14, 255), width=5)
    draw.ellipse((inset + 8, inset + 8, size - inset - 9, size - inset - 9), outline=(255, 234, 150, 255), width=3)

    # A raised letter: a light edge above, a dark edge below
    letter = "H" if face == "heads" else "T"
    font = _font(200)
    draw.text((center + 5, center + 5), letter, font=font, fill=(112, 68, 8, 255), anchor="mm")
    draw.text((center - 4, center - 4), letter, font=font, fill=(255, 240, 170, 255), anchor="mm")
    draw.text((center, center), letter, font=font, fill=(216, 150, 30, 255), anchor="mm")

    # Gloss in the upper left
    gloss = Image.new("L", (size, size), 0)
    ImageDraw.Draw(gloss).ellipse((60, 42, size * 0.62, size * 0.42), fill=70)
    gloss = gloss.filter(ImageFilter.GaussianBlur(22))
    coin.paste(Image.new("RGB", (size, size), (255, 255, 255)), (0, 0), Image.composite(gloss, Image.new("L", (size, size), 0), mask))

    return coin.resize((COIN_SIZE, COIN_SIZE), Image.LANCZOS)


@lru_cache(maxsize=None)
def _coin_edge(height: int) -> Image.Image:
    """One slice of the coin's edge, for stacking into the side of the coin."""
    slice_img = Image.new("L", (COIN_SIZE * 2, height * 2), 0)
    ImageDraw.Draw(slice_img).ellipse((0, 0, COIN_SIZE * 2 - 1, height * 2 - 1), fill=255)
    mask = slice_img.resize((COIN_SIZE, height), Image.LANCZOS)
    gradient = _vertical_gradient((COIN_SIZE, height), EDGE_LIGHT, EDGE_DARK).convert("RGBA")
    gradient.putalpha(mask)
    return gradient


def _draw_coin(frame: Image.Image, face: str, angle: float, center_y: float):
    """Draw the coin rotated around its horizontal axis."""
    tilt = abs(math.cos(angle))
    height = max(6, int(COIN_SIZE * tilt))
    left = (WIDTH - COIN_SIZE) // 2
    depth = int(EDGE_DEPTH * abs(math.sin(angle)))
    top = int(center_y - height / 2 - depth / 2)

    edge = _coin_edge(height)
    for offset in range(depth, 0, -1):
        frame.alpha_composite(edge, (left, top + offset))

    picture = _coin_face(face).resize((COIN_SIZE, height), Image.BILINEAR)
    # The metal catches the light at some angles and goes darker at others.
    brightness = 0.84 + 0.3 * abs(math.cos(angle - 0.6))
    rgb = ImageEnhance.Brightness(picture.convert("RGB")).enhance(brightness)
    rgb.putalpha(picture.getchannel("A"))
    frame.alpha_composite(rgb, (left, top))


@lru_cache(maxsize=None)
def _shadow(width: int) -> Image.Image:
    height = 44
    canvas = Image.new("L", (COIN_SIZE + 60, height), 0)
    left = (canvas.width - width) // 2
    ImageDraw.Draw(canvas).ellipse((left, 12, left + width, height - 12), fill=150)
    canvas = canvas.filter(ImageFilter.GaussianBlur(6))
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 255))
    shadow.putalpha(canvas)
    return shadow


def _scene(face: str, angle: float, lift: float) -> Image.Image:
    frame = _background().convert("RGBA")
    # The higher the coin, the smaller the shadow. Rounded to a few sizes so the shadows can be cached.
    shadow_width = int(COIN_SIZE * (1 - min(1.0, lift / FLIP_HEIGHT) * 0.5)) // 6 * 6
    frame.alpha_composite(_shadow(shadow_width), ((WIDTH - (COIN_SIZE + 60)) // 2, TABLE_Y - 22))
    _draw_coin(frame, face, angle, FLOOR_Y - lift)
    return frame


def _caption(frame: Image.Image, text: str, color: tuple[int, int, int], size: int = 26):
    draw = ImageDraw.Draw(frame)
    center = (WIDTH / 2, HEIGHT - 47)
    draw.text((center[0], center[1] + 2), text, font=_font(size), fill=(0, 0, 0), anchor="mm")
    draw.text(center, text, font=_font(size), fill=color, anchor="mm")


def render_flip_gif(outcome: str, guess: str, bet: int, seed: int | None = None) -> bytes:
    """Draw a flip that lands on outcome ('heads' or 'tails'). Winning pays double the bet."""
    rng = random.Random(seed)
    other = "tails" if outcome == "heads" else "heads"
    won = guess == outcome
    chosen = f"YOU CHOSE {guess.upper()}"
    result = f"YOU WON +{bet:,}" if won else f"YOU LOST {bet:,}"
    result_color = GREEN if won else RED
    frames, durations = [], []

    # The flip: whole turns, so it lands showing the outcome
    for number in range(FRAMES):
        t = number / FRAMES
        angle = TURNS * 2 * math.pi * (1 - (1 - t) ** 2)
        frame = _scene(outcome if math.cos(angle) >= 0 else other, angle, FLIP_HEIGHT * math.sin(math.pi * t))
        _caption(frame, chosen, MUTED, 19)
        frames.append(frame)
        durations.append(FRAME_MS)

    # A small bounce on landing
    for number in range(BOUNCE_FRAMES):
        t = (number + 1) / (BOUNCE_FRAMES + 1)
        frame = _scene(outcome, 0.0, BOUNCE_HEIGHT * math.sin(math.pi * t))
        _caption(frame, chosen, MUTED, 19)
        frames.append(frame)
        durations.append(FRAME_MS)

    if won:
        sparkles = [(WIDTH / 2 + rng.randint(-105, 105), FLOOR_Y + rng.randint(-95, 70), rng.randrange(WIN_FRAMES))
                    for _ in range(10)]
        for number in range(WIN_FRAMES):
            frame = _scene(outcome, 0.0, 0)
            draw = ImageDraw.Draw(frame)
            for x, y, start in sparkles:
                age = (number - start) % WIN_FRAMES
                if age < 4:
                    _draw_sparkle(draw, x, y, [5, 12, 8, 3][age])
            _caption(frame, result, result_color)
            frames.append(frame)
            durations.append(WIN_FRAME_MS)

    last = _scene(outcome, 0.0, 0)
    _caption(last, result, result_color)
    frames.append(last)
    durations.append(LAST_FRAME_MS)

    samples = [frames[0], frames[FRAMES // 3], frames[FRAMES // 2], last]
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
