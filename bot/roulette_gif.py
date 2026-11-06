"""
Draws a roulette spin as an animated GIF with Pillow, in the same style as the slot machine.
Knows nothing about Discord or the database. The result is part of the animation; the GIF plays once.

A European wheel (one zero) turns one way while the ball runs the other way around the rim,
then drops into the winning pocket, which stops under the gold marker at the top.
"""

import io
import math
import random
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter

from .slots_gif import (
    CABINET_BOTTOM, CABINET_TOP, GOLD, GOLD_DARK, GOLD_LIGHT, GREEN, LAST_FRAME_MS, MUTED, RED,
    _draw_sparkle, _font, _paste_gold_plate, _vertical_gradient,
)

WIDTH, HEIGHT = 440, 500
CENTER = (WIDTH // 2, 252)
RADIUS = 162          # outer edge of the wooden rim
POCKET_OUTER = 132    # the ring of numbered pockets
POCKET_INNER = 100
BALL_TRACK = 146      # where the ball runs before it drops
BALL_REST = 108       # the ball inside a pocket, inside the numbers
BALL_SIZE = 13        # diameter
SCALE = 3             # the wheel is drawn this much bigger and scaled down, so edges stay smooth

SPIN_FRAMES = 28
FRAME_MS = 70
WHEEL_TURNS = 2       # where the wheel stops, in whole turns (only the remainder shows)
# Each spin picks its own values from these ranges:
WHEEL_TRAVEL = (420, 780)   # degrees the wheel turns counterclockwise
BALL_LAPS = (2.2, 3.2)      # clockwise laps of the ball as seen from above
DROP_AT = (0.48, 0.62)      # share of the spin after which the ball leaves the rim
SETTLE_AT = (0.8, 0.9)      # by then the ball sits in its pocket
WIN_FRAMES = 7
WIN_FRAME_MS = 90

# Pocket order around a European wheel, clockwise from zero
WHEEL_ORDER = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33, 1,
               20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26]
RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
STEP = 360 / len(WHEEL_ORDER)

POCKET_RED = (196, 32, 44)
POCKET_BLACK = (26, 24, 30)
POCKET_GREEN = (18, 140, 74)
WOOD_LIGHT = (122, 66, 30)
WOOD_DARK = (58, 28, 12)
CONE_LIGHT = (92, 50, 24)
CONE_DARK = (40, 20, 10)


def color_of(number: int) -> str:
    """'green', 'red' or 'black'."""
    if number == 0:
        return "green"
    return "red" if number in RED_NUMBERS else "black"


def _pocket_rgb(number: int) -> tuple[int, int, int]:
    return {"green": POCKET_GREEN, "red": POCKET_RED, "black": POCKET_BLACK}[color_of(number)]


def animation_seconds(won: bool) -> float:
    """How long the GIF takes to reach its result, including the win sparkles."""
    return (SPIN_FRAMES * FRAME_MS + (WIN_FRAMES * WIN_FRAME_MS if won else 0)) / 1000


@lru_cache(maxsize=None)
def _background() -> Image.Image:
    frame = _vertical_gradient((WIDTH, HEIGHT), CABINET_TOP, CABINET_BOTTOM)

    # A pool of light on the wheel
    light = Image.new("L", (WIDTH, HEIGHT), 0)
    cx, cy = CENTER
    ImageDraw.Draw(light).ellipse((cx - RADIUS - 40, cy - RADIUS - 40, cx + RADIUS + 40, cy + RADIUS + 40), fill=60)
    frame.paste(Image.new("RGB", (WIDTH, HEIGHT), (255, 210, 150)), (0, 0), light.filter(ImageFilter.GaussianBlur(30)))

    gold = _vertical_gradient((WIDTH, HEIGHT), GOLD_LIGHT, GOLD_DARK)
    ring = Image.new("L", (WIDTH * 2, HEIGHT * 2), 0)
    draw = ImageDraw.Draw(ring)
    draw.rounded_rectangle((8, 8, WIDTH * 2 - 9, HEIGHT * 2 - 9), radius=44, fill=255)
    draw.rounded_rectangle((28, 28, WIDTH * 2 - 29, HEIGHT * 2 - 29), radius=30, fill=0)
    frame.paste(gold, (0, 0), ring.resize((WIDTH, HEIGHT), Image.LANCZOS))

    _paste_gold_plate(frame, (100, 24, WIDTH - 100, 66), radius=12)
    sign = Image.new("L", (WIDTH, HEIGHT), 0)
    ImageDraw.Draw(sign).text((WIDTH / 2, 45), "ROULETTE", font=_font(24), fill=255, anchor="mm")
    frame.paste(Image.new("RGB", (WIDTH, HEIGHT), GOLD_LIGHT), (0, 0), sign)
    _paste_gold_plate(frame, (32, HEIGHT - 70, WIDTH - 32, HEIGHT - 22), radius=14)

    # The wheel's shadow on the table
    shadow = Image.new("L", (WIDTH, HEIGHT), 0)
    ImageDraw.Draw(shadow).ellipse((cx - RADIUS + 4, cy - RADIUS + 14, cx + RADIUS + 4, cy + RADIUS + 14), fill=170)
    frame.paste((8, 2, 12), (0, 0), shadow.filter(ImageFilter.GaussianBlur(10)))
    return frame


@lru_cache(maxsize=None)
def _wheel() -> Image.Image:
    """The turning part of the wheel, upright (zero at the top), drawn at SCALE."""
    size = 2 * RADIUS * SCALE
    c = size / 2
    wheel = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(wheel)

    def circle(radius, fill):
        r = radius * SCALE
        draw.ellipse((c - r, c - r, c + r, c + r), fill=fill)

    # Wooden rim with a gold edge
    circle(RADIUS, GOLD_DARK)
    circle(RADIUS - 2, GOLD_LIGHT)
    circle(RADIUS - 5, WOOD_DARK)
    circle(RADIUS - 9, WOOD_LIGHT)
    circle(POCKET_OUTER + 6, WOOD_DARK)
    circle(POCKET_OUTER + 2, GOLD)

    # Numbered pockets
    outer, inner = POCKET_OUTER * SCALE, POCKET_INNER * SCALE
    for index, number in enumerate(WHEEL_ORDER):
        start = -90 + (index - 0.5) * STEP
        draw.pieslice((c - outer, c - outer, c + outer, c + outer), start, start + STEP, fill=_pocket_rgb(number))
    for index in range(len(WHEEL_ORDER)):
        angle = math.radians(-90 + (index - 0.5) * STEP)
        draw.line((c + inner * math.cos(angle), c + inner * math.sin(angle),
                   c + outer * math.cos(angle), c + outer * math.sin(angle)), fill=GOLD_LIGHT, width=SCALE * 2)

    font = _font(12 * SCALE)
    for index, number in enumerate(WHEEL_ORDER):
        label = Image.new("L", (30 * SCALE, 20 * SCALE), 0)
        ImageDraw.Draw(label).text((label.width / 2, label.height / 2), str(number), font=font, fill=255, anchor="mm")
        label = label.rotate(-index * STEP, expand=True, resample=Image.BICUBIC)
        angle = math.radians(-90 + index * STEP)
        radius = (POCKET_OUTER - 11) * SCALE
        x, y = c + radius * math.cos(angle), c + radius * math.sin(angle)
        wheel.paste((255, 255, 255), (int(x - label.width / 2), int(y - label.height / 2)), label)

    # Separators between the pockets and the cone, then the cone with gold spokes and a turret
    circle(POCKET_INNER, GOLD_LIGHT)
    circle(POCKET_INNER - 3, CONE_DARK)
    cone = _vertical_gradient((size, size), CONE_LIGHT, CONE_DARK).convert("RGBA")
    mask = Image.new("L", (size, size), 0)
    r = (POCKET_INNER - 6) * SCALE
    ImageDraw.Draw(mask).ellipse((c - r, c - r, c + r, c + r), fill=255)
    wheel.paste(cone, (0, 0), mask)
    for spoke in range(4):
        angle = math.radians(spoke * 90 + 45)
        draw.line((c - 70 * SCALE * math.cos(angle), c - 70 * SCALE * math.sin(angle),
                   c + 70 * SCALE * math.cos(angle), c + 70 * SCALE * math.sin(angle)), fill=GOLD, width=5 * SCALE)
    circle(26, GOLD_DARK)
    circle(23, GOLD_LIGHT)
    circle(15, GOLD)
    return wheel


@lru_cache(maxsize=None)
def _wheel_2x() -> Image.Image:
    """Turning the full-size drawing for every frame is slow; twice the final size is enough."""
    return _wheel().resize((4 * RADIUS, 4 * RADIUS), Image.LANCZOS)


@lru_cache(maxsize=8)
def _wheel_at(angle: float) -> Image.Image:
    """The wheel turned counterclockwise by angle degrees, at the final size."""
    turned = _wheel_2x().rotate(angle, resample=Image.BICUBIC)
    return turned.resize((2 * RADIUS, 2 * RADIUS), Image.LANCZOS)


def _ball(frame: Image.Image, angle: float, radius: float):
    """The ball at angle (degrees, clockwise from the right) and distance radius from the center."""
    x = CENTER[0] + radius * math.cos(math.radians(angle))
    y = CENTER[1] + radius * math.sin(math.radians(angle))
    big = BALL_SIZE * 4
    ball = Image.new("RGBA", (big + 12, big + 16), (0, 0, 0, 0))
    draw = ImageDraw.Draw(ball)
    draw.ellipse((8, 12, big + 8, big + 12), fill=(0, 0, 0, 110))
    draw.ellipse((0, 0, big, big), fill=(200, 200, 210, 255))
    draw.ellipse((5, 4, big - 12, big - 13), fill=(255, 255, 255, 255))
    ball = ball.resize((ball.width // 4, ball.height // 4), Image.LANCZOS)
    frame.alpha_composite(ball, (int(x - BALL_SIZE / 2), int(y - BALL_SIZE / 2)))


def _marker(frame: Image.Image):
    """The gold pointer above the wheel that shows the winning pocket."""
    cx, top = CENTER[0], CENTER[1] - RADIUS - 6
    draw = ImageDraw.Draw(frame)
    draw.polygon([(cx - 12, top - 4), (cx + 12, top - 4), (cx, top + 16)], fill=GOLD_DARK)
    draw.polygon([(cx - 9, top - 2), (cx + 9, top - 2), (cx, top + 12)], fill=GOLD_LIGHT)


def _result_badge(frame: Image.Image, number: int):
    """The winning number on the wheel's turret."""
    size = 60
    badge = Image.new("RGBA", (size * 4, size * 4), (0, 0, 0, 0))
    draw = ImageDraw.Draw(badge)
    draw.ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=GOLD_LIGHT + (255,))
    draw.ellipse((10, 10, size * 4 - 11, size * 4 - 11), fill=_pocket_rgb(number) + (255,))
    draw.text((size * 2, size * 2 + 4), str(number), font=_font(108), fill=(255, 255, 255), anchor="mm")
    badge = badge.resize((size, size), Image.LANCZOS)
    frame.alpha_composite(badge, (CENTER[0] - size // 2, CENTER[1] - size // 2))


def _caption(frame: Image.Image, text: str, color: tuple[int, int, int], size: int = 24):
    draw = ImageDraw.Draw(frame)
    center = (WIDTH / 2, HEIGHT - 46)
    draw.text((center[0], center[1] + 2), text, font=_font(size), fill=(0, 0, 0), anchor="mm")
    draw.text(center, text, font=_font(size), fill=color, anchor="mm")


def _scene(wheel_angle: float, ball_angle: float, ball_radius: float, number: int | None = None) -> Image.Image:
    frame = _background().convert("RGBA")
    # A small set of angles is enough: rounding to a tenth of a degree is invisible
    frame.alpha_composite(_wheel_at(round(wheel_angle % 360, 1)), (CENTER[0] - RADIUS, CENTER[1] - RADIUS))
    if number is not None:
        _result_badge(frame, number)
    _ball(frame, ball_angle, ball_radius)
    _marker(frame)
    return frame


def _ease_out(t: float) -> float:
    return 1 - (1 - t) ** 3


def render_spin_gif(number: int, bet_label: str, bet: int, payout: int, seed: int | None = None) -> bytes:
    """
    Draw a spin that lands on number. bet_label names what was bet on ('RED', '17', ...).
    payout is the total returned to the player (0 on a loss).
    """
    rng = random.Random(seed)
    won = payout > 0
    final_wheel = WHEEL_ORDER.index(number) * STEP + 360 * WHEEL_TURNS
    chosen = f"YOU BET ON {bet_label}"
    result = f"{number} {color_of(number).upper()} · " + (f"WON +{payout - bet:,}" if won else f"LOST {bet:,}")
    result_color = GREEN if won else RED
    frames, durations = [], []

    # Every spin is different: how far the wheel turns, how many laps the ball runs,
    # when it drops and how it bounces over the pockets before it settles.
    wheel_travel = rng.uniform(*WHEEL_TRAVEL)
    ball_laps = rng.uniform(*BALL_LAPS)
    drop_at = rng.uniform(*DROP_AT)
    settle_at = rng.uniform(*SETTLE_AT)
    hop_size = rng.uniform(1.0, 2.5) * STEP * rng.choice([-1, 1])
    hops = rng.randint(2, 4)
    # Laps of the ball relative to the wheel, so that it runs ball_laps clockwise as seen from above
    relative_laps = ball_laps + wheel_travel * _ease_out(settle_at) / 360

    for index in range(SPIN_FRAMES):
        t = index / (SPIN_FRAMES - 1)
        wheel = final_wheel - wheel_travel * (1 - _ease_out(t))
        pocket = -90 + (final_wheel - wheel)       # where the winning pocket is now
        settle = min(1.0, t / settle_at)
        ball = pocket - 360 * relative_laps * (1 - settle) ** 2
        if t < drop_at:
            radius = BALL_TRACK
        elif t < settle_at:
            drop = (t - drop_at) / (settle_at - drop_at)
            # Falls inward, hopping over a few pockets off the separators
            bounce = math.sin(drop * math.pi * hops) * (1 - drop)
            ball += hop_size * bounce
            radius = BALL_TRACK - (BALL_TRACK - BALL_REST) * drop + 7 * abs(bounce)
        else:
            radius = BALL_REST
        frame = _scene(wheel, ball, radius)
        _caption(frame, chosen, MUTED, 19)
        frames.append(frame)
        durations.append(FRAME_MS)

    final_ball = (-90, BALL_REST)
    if won:
        cx, cy = CENTER
        sparkles = [(cx + rng.randint(-150, 150), cy + rng.randint(-150, 150), rng.randrange(WIN_FRAMES))
                    for _ in range(12)]
        for index in range(WIN_FRAMES):
            frame = _scene(final_wheel, *final_ball, number)
            draw = ImageDraw.Draw(frame)
            for x, y, start in sparkles:
                age = (index - start) % WIN_FRAMES
                if age < 4:
                    _draw_sparkle(draw, x, y, [5, 12, 8, 3][age])
            _caption(frame, result, result_color)
            frames.append(frame)
            durations.append(WIN_FRAME_MS)

    last = _scene(final_wheel, *final_ball, number)
    _caption(last, result, result_color)
    frames.append(last)
    durations.append(LAST_FRAME_MS)

    samples = [frames[0], frames[SPIN_FRAMES // 2], last]
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
