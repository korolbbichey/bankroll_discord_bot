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

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

from .slots_gif import (
    CABINET_BOTTOM, CABINET_TOP, GOLD_DARK, GOLD_LIGHT, GREEN, LAST_FRAME_MS, MUTED, RED,
    _draw_sparkle, _font, _paste_gold_plate, _vertical_gradient,
)

WIDTH, HEIGHT = 400, 440
COIN_SIZE = 140
EDGE_DEPTH = 26       # how thick the coin looks when seen from the side
REST_TILT = 0.38      # radians: the coin leans back a little, so its edge shows even when it faces you
EDGE_RIDGES = 28      # reeding lines across the visible half of the edge
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


# A king's head in profile for heads, in a 0..1 box, facing left
PROFILE = [(0.62, 1.0), (0.60, 0.84), (0.68, 0.74), (0.73, 0.58), (0.72, 0.42), (0.66, 0.30), (0.56, 0.24),
           (0.44, 0.23), (0.35, 0.27), (0.30, 0.35), (0.285, 0.43), (0.26, 0.47), (0.19, 0.555), (0.20, 0.58),
           (0.255, 0.595), (0.245, 0.625), (0.225, 0.645), (0.245, 0.665), (0.235, 0.695), (0.24, 0.735),
           (0.29, 0.775), (0.37, 0.79), (0.40, 0.88), (0.38, 1.0)]
CROWN = [(0.33, 0.29), (0.66, 0.31), (0.66, 0.22), (0.60, 0.07), (0.55, 0.19), (0.495, 0.03),
         (0.44, 0.18), (0.38, 0.08), (0.33, 0.21)]


def _emblem(face: str, size: int) -> tuple[Image.Image, list]:
    """
    The picture struck on a coin face: a crowned king for heads, a star in a laurel wreath for tails.
    Returns the raised shapes as a mask and the carved lines as (points, width).
    """
    box_left, box_top, box = size * 0.17, size * 0.15, size * 0.66
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)

    def at(x, y):
        return box_left + x * box, box_top + y * box

    if face == "heads":
        draw.polygon([at(x, y) for x, y in PROFILE], fill=255)
        draw.polygon([at(x, y) for x, y in CROWN], fill=255)
        ball = box * 0.028
        for x, y in [(0.60, 0.07), (0.495, 0.03), (0.38, 0.08)]:
            cx, cy = at(x, y)
            draw.ellipse((cx - ball, cy - ball, cx + ball, cy + ball), fill=255)
        carved = [
            ([at(0.33, 0.255), at(0.66, 0.275)], 4),                              # crown band
            ([at(0.30, 0.445), at(0.345, 0.45)], 5),                              # eye
            ([at(0.58, 0.44), at(0.61, 0.49), at(0.60, 0.55), at(0.57, 0.57)], 5),  # ear
            ([at(0.34, 0.80), at(0.66, 0.80)], 3),                                # where the bust ends
        ]
        return mask, carved

    cx, cy = at(0.5, 0.47)
    outer, inner = box * 0.2, box * 0.085
    draw.polygon([(cx + (outer if i % 2 == 0 else inner) * math.cos(-math.pi / 2 + i * math.pi / 5),
                   cy + (outer if i % 2 == 0 else inner) * math.sin(-math.pi / 2 + i * math.pi / 5))
                  for i in range(10)], fill=255)
    # Two laurel branches: a stem along a circle with a pair of leaves at each step
    ring = box * 0.40
    leaf = Image.new("L", (int(box * 0.16), int(box * 0.07)), 0)
    ImageDraw.Draw(leaf).ellipse((0, 0, leaf.width - 1, leaf.height - 1), fill=255)
    for side in (-1, 1):
        stem = []
        for step in range(9):
            angle = math.radians(115 + step * 15)
            x = cx - side * ring * math.cos(angle)
            y = cy - ring * math.sin(angle) + box * 0.03
            stem.append((x, y))
            tangent = math.degrees(angle) + (90 if side == 1 else -90)
            for pair in (-1, 1):
                rotated = leaf.rotate(-side * (tangent + pair * 35) + 180, expand=True, resample=Image.BICUBIC)
                shift = pair * box * 0.035
                mask.paste(255, (int(x - rotated.width / 2 - shift * math.cos(angle) * side),
                                 int(y - rotated.height / 2 - shift * math.sin(angle))), rotated)
        draw.line(stem, fill=255, width=6)
    return mask, []


@lru_cache(maxsize=None)
def _coin_face(face: str) -> Image.Image:
    """The coin seen head-on, with a reeded rim, a metallic face and a raised picture."""
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

    # Light and shade: the raised rim is lit on the upper left, and casts a shadow into the recess there
    shading = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shade = ImageDraw.Draw(shading)
    rim = (12, 12, size - 13, size - 13)
    shade.arc(rim, 150, 300, fill=(255, 250, 210, 170), width=16)
    shade.arc(rim, 330, 120, fill=(90, 50, 0, 150), width=16)
    edge = (inset + 2, inset + 2, size - inset - 3, size - inset - 3)
    shade.arc(edge, 150, 300, fill=(80, 44, 0, 190), width=14)
    shade.arc(edge, 330, 120, fill=(255, 244, 190, 170), width=10)
    coin.alpha_composite(shading.filter(ImageFilter.GaussianBlur(5)))
    draw.ellipse((inset, inset, size - inset - 1, size - inset - 1), outline=(136, 88, 14, 255), width=4)

    # The raised picture: a soft shadow below right, a lit edge above left and a gold gradient on top
    picture, carved = _emblem(face, size)
    shadow = Image.new("L", (size, size), 0)
    shadow.paste(picture, (8, 9))
    coin.paste((70, 40, 4), (0, 0), shadow.filter(ImageFilter.GaussianBlur(4)).point(lambda v: v * 3 // 4))
    lit = Image.new("L", (size, size), 0)
    lit.paste(picture, (-3, -3))
    coin.paste((255, 244, 186), (0, 0), lit)
    coin.paste(_vertical_gradient((size, size), (255, 222, 120), (196, 132, 24)), (0, 0), picture)
    # A bevel just inside the outline: bright along the top left, dark along the bottom right
    for shift, color in (((4, 4), (255, 240, 170)), ((-4, -4), (140, 88, 12))):
        moved = Image.new("L", (size, size), 0)
        moved.paste(picture, shift)
        coin.paste(color, (0, 0), ImageChops.subtract(picture, moved))
    for points, width in carved:
        draw.line(points, fill=(130, 82, 12, 255), width=width, joint="curve")

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
    # A cylinder: brightest facing you, darker towards the sides, with reeding lines that bunch up at the sides
    row = Image.new("RGB", (COIN_SIZE, 1))
    radius = COIN_SIZE / 2
    for x in range(COIN_SIZE):
        theta = math.acos(max(-1.0, min(1.0, (x + 0.5 - radius) / radius)))
        light = 0.3 + 0.7 * math.sin(theta) ** 1.5
        ridge = 0.8 if int(theta / math.pi * EDGE_RIDGES * 2) % 2 else 1.0
        row.putpixel((x, 0), tuple(int((d + (l - d) * light) * ridge) for l, d in zip(EDGE_LIGHT, EDGE_DARK)))
    edge = row.resize((COIN_SIZE, height)).convert("RGBA")
    edge.putalpha(mask)
    return edge


def _draw_coin(frame: Image.Image, face: str, angle: float, center_y: float):
    """Draw the coin rotated around its horizontal axis (angle 0 = facing you, apart from REST_TILT)."""
    seen = angle + REST_TILT
    height = max(6, int(COIN_SIZE * abs(math.cos(seen))))
    left = (WIDTH - COIN_SIZE) // 2
    depth = int(EDGE_DEPTH * abs(math.sin(seen)))
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


def render_flip_gif(outcome: str, guess: str, bet: int, seed: int | None = None, caption: str | None = None,
                    result_text: str | None = None, result_text_color: tuple[int, int, int] | None = None) -> bytes:
    """
    Draw a flip that lands on outcome ('heads' or 'tails'). Winning pays double the bet.
    caption and result_text replace the default texts (used by duels, which have no single player's guess).
    """
    rng = random.Random(seed)
    other = "tails" if outcome == "heads" else "heads"
    custom = result_text is not None
    won = guess == outcome and not custom
    chosen = caption or f"YOU CHOSE {guess.upper()}"
    result = result_text or (f"YOU WON +{bet:,}" if won else f"YOU LOST {bet:,}")
    result_color = result_text_color or (GREEN if won else RED)
    frames, durations = [], []

    # The flip: whole turns, so it lands showing the outcome
    for number in range(FRAMES):
        t = number / FRAMES
        angle = TURNS * 2 * math.pi * (1 - (1 - t) ** 2)
        frame = _scene(outcome if math.cos(angle + REST_TILT) >= 0 else other, angle, FLIP_HEIGHT * math.sin(math.pi * t))
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
