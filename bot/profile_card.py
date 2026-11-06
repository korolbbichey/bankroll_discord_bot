"""
Draws the /profile card as a PNG with Pillow. Knows nothing about Discord or the database.

Everything is drawn at SCALE times the final size and shrunk at the end, which gives smooth edges.
Icons are Twemoji (CC-BY 4.0), the font is Montserrat (SIL OFL).
"""

import io
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from .config import BADGE_RARITY

ASSETS = Path(__file__).parent / "assets"
FONT_FILE = ASSETS / "fonts" / "Montserrat.ttf"
FALLBACK_FONT_FILE = ASSETS / "fonts" / "NotoSansSC.ttf"  # Chinese and Japanese names
MISSING_GLYPH = "\U0010FFFF"  # never assigned, so every font draws its "missing" box for it
DEFAULT_NAME = "Player"

SCALE = 2
WIDTH, HEIGHT = 1000, 580
MARGIN = 40

BACKGROUND_TOP = (24, 22, 38)
BACKGROUND_BOTTOM = (14, 13, 23)
PANEL = (255, 255, 255, 14)
TEXT = (240, 238, 248)
MUTED = (150, 146, 170)
BAR_EMPTY = (255, 255, 255, 28)

# Same order as progression.BADGES
BADGE_ICONS = {
    "first_win": "1f340", "explorer": "1f9ed", "spins_100": "1f3b0", "multi_line": "1f308",
    "diamond_line": "1f48e", "natural": "1f0cf", "double_win": "270c", "coin_10": "1fa99",
    "max_bet": "1f4b8", "week_streak": "1f525", "generous": "1f91d", "rich": "1f911", "podium": "1f3c6",
    "duelist": "2694", "duel_5": "1f947", "bullseye": "1f3af", "zero": "1f7e2", "jackpot": "1f4b0",
    "grand_tour": "1f5fa", "veteran": "1f396", "month_streak": "26a1",
}
BADGES_PER_ROW = 11
RARITY_METALS = {  # (light, dark) of the medal's rim
    "common": ((236, 168, 110), (128, 72, 34)),     # bronze
    "rare": ((244, 246, 252), (126, 134, 152)),     # silver
    "epic": ((255, 228, 130), (168, 108, 18)),      # gold
    "legendary": ((140, 230, 255), (176, 96, 255)),  # diamond
}
SUIT_ICONS = ["2660", "2665", "2666", "2663"]
LOCK_ICON = "1f512"
MEDAL_PAD = 18  # transparent room around a medal for its glow
TITLE_ICONS = {
    "Rookie": "1fa99", "Gambler": "1f3b2", "High Roller": "1f4bc",
    "Card Shark": "1f3a9", "Casino King": "1f451", "Legend": "1f48e",
}


@dataclass
class CardData:
    name: str
    title: str
    accent: tuple[int, int, int]
    level: int
    xp_into_level: int
    level_span: int
    balance: int
    rank: int | None
    games: int
    win_rate: str
    best_win: int
    streak: int
    earned_badges: set[str] = field(default_factory=set)


@lru_cache(maxsize=None)
def _font(size: int, weight: str = "Bold", file: Path = FONT_FILE) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(file), size * SCALE)
    font.set_variation_by_name(weight)
    return font


def _icon(code: str, size: int) -> Image.Image:
    with Image.open(ASSETS / "icons" / f"{code}.png") as icon:
        return icon.convert("RGBA").resize((size * SCALE, size * SCALE), Image.LANCZOS)


def _dimmed(icon: Image.Image) -> Image.Image:
    """A grey, faded version of an icon for a badge that isn't earned yet."""
    grey = ImageOps.grayscale(icon.convert("RGB")).convert("RGBA")
    grey.putalpha(icon.getchannel("A").point(lambda alpha: alpha * 45 // 255))
    return grey


def _fit(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
    """Shorten text with an ellipsis so it fits max_width (in final pixels)."""
    if font.getlength(text) <= max_width * SCALE:
        return text
    while text and font.getlength(text + "…") > max_width * SCALE:
        text = text[:-1]
    return text.rstrip() + "…"


# ---------- player names: any Unicode can appear in them, and no font covers it all ----------

def _has_glyph(font: ImageFont.FreeTypeFont, char: str) -> bool:
    if char.isspace():
        return True
    return bytes(font.getmask(char)) != bytes(font.getmask(MISSING_GLYPH))


def clean_name(name: str) -> str:
    """Make a name drawable: decorative letters become plain ones (𝓜 -> M), anything without a glyph is dropped."""
    latin, fallback = _font(20), _font(20, file=FALLBACK_FONT_FILE)
    text = unicodedata.normalize("NFKC", name)
    kept = "".join(c for c in text if c.isprintable() and (_has_glyph(latin, c) or _has_glyph(fallback, c)))
    return " ".join(kept.split()) or DEFAULT_NAME


def _name_runs(text: str, size: int, weight: str) -> list[tuple[str, ImageFont.FreeTypeFont]]:
    """Split text into pieces, each drawn with the font that has its glyphs."""
    latin, fallback = _font(size, weight), _font(size, weight, file=FALLBACK_FONT_FILE)
    runs = []
    for char in text:
        font = latin if _has_glyph(latin, char) else fallback
        if runs and runs[-1][1] is font:
            runs[-1] = (runs[-1][0] + char, font)
        else:
            runs.append((char, font))
    return runs


def _runs_width(runs: list[tuple[str, ImageFont.FreeTypeFont]]) -> float:
    return sum(font.getlength(text) for text, font in runs)


def _fit_name(name: str, size: int, weight: str, max_width: int) -> list[tuple[str, ImageFont.FreeTypeFont]]:
    text = name
    runs = _name_runs(text, size, weight)
    while text and _runs_width(runs) > max_width * SCALE:
        text = text[:-1]
        runs = _name_runs(text.rstrip() + "…", size, weight)
    return runs


def _background(height_px: int = HEIGHT) -> Image.Image:
    width, height = WIDTH * SCALE, height_px * SCALE
    gradient = Image.linear_gradient("L").resize((width, height))
    return Image.composite(
        Image.new("RGBA", (width, height), BACKGROUND_BOTTOM + (255,)),
        Image.new("RGBA", (width, height), BACKGROUND_TOP + (255,)),
        gradient,
    )


def _accent_glow(accent: tuple[int, int, int]) -> Image.Image:
    """A soft spot of the title's color behind the avatar."""
    width, height = WIDTH * SCALE, HEIGHT * SCALE
    size = 620 * SCALE
    # The gradient reaches about 128 at the middle of each edge: fade out before that to avoid a visible border.
    glow = Image.radial_gradient("L").resize((size, size)).point(lambda v: max(0, 120 - v) * 70 // 120)
    layer = Image.new("RGBA", (width, height), accent + (0,))
    mask = Image.new("L", (width, height), 0)
    mask.paste(glow, (-190 * SCALE, -230 * SCALE))
    layer.putalpha(mask)
    return layer


def _avatar_circle(avatar_bytes: bytes | None, name: str, size: int, accent: tuple[int, int, int]) -> Image.Image:
    pixels = size * SCALE
    if avatar_bytes:
        with Image.open(io.BytesIO(avatar_bytes)) as source:
            picture = ImageOps.fit(source.convert("RGBA"), (pixels, pixels), Image.LANCZOS)
    else:
        picture = Image.new("RGBA", (pixels, pixels), tuple(c // 2 for c in accent) + (255,))
        draw = ImageDraw.Draw(picture)
        (letter, font), *_ = _name_runs(name[:1].upper(), size // 2, "Bold")
        draw.text((pixels / 2, pixels / 2), letter, font=font, fill=TEXT, anchor="mm")
    mask = Image.new("L", (pixels, pixels), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, pixels - 1, pixels - 1), fill=255)
    picture.putalpha(mask)
    return picture


# ---------- decorations ----------

@lru_cache(maxsize=None)
def _suit_pattern(accent: tuple[int, int, int]) -> Image.Image:
    """Card suits scattered faintly over the right side of the card, in the title's color."""
    width, height = WIDTH * SCALE, HEIGHT * SCALE
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    step = 92
    for row, y in enumerate(range(-20, HEIGHT, step)):
        for col, x in enumerate(range(400 + (row % 2) * step // 2, WIDTH + step, step)):
            code = SUIT_ICONS[(row + col) % 4]
            icon = ImageOps.grayscale(_icon(code, 34).convert("RGB"))
            tinted = Image.new("RGBA", icon.size, accent + (0,))
            fade = max(0.0, min(1.0, (x - 400) / 360))  # stronger towards the right edge
            tinted.putalpha(_icon(code, 34).getchannel("A").point(lambda a, f=fade: int(a * 0.07 * f)))
            tinted = tinted.rotate(18, expand=True, resample=Image.BICUBIC)
            layer.alpha_composite(tinted, (x * SCALE, y * SCALE))
    return layer


@lru_cache(maxsize=None)
def _medal(badge_id: str, earned: bool, size: int) -> Image.Image:
    """A round medal: a metal rim in the badge's rarity, a dark face and the icon. Locked medals are dark with a lock."""
    pixels = size * SCALE
    pad = MEDAL_PAD * SCALE  # room for the glow
    medal = Image.new("RGBA", (pixels + 2 * pad, pixels + 2 * pad), (0, 0, 0, 0))
    box = (pad, pad, pad + pixels - 1, pad + pixels - 1)

    def disc(inset: int) -> Image.Image:
        mask = Image.new("L", medal.size, 0)
        ImageDraw.Draw(mask).ellipse((box[0] + inset, box[1] + inset, box[2] - inset, box[3] - inset), fill=255)
        return mask

    if earned:
        light, dark = RARITY_METALS[BADGE_RARITY[badge_id]]
        if BADGE_RARITY[badge_id] in ("epic", "legendary"):
            glow = Image.new("RGBA", medal.size, light + (0,))
            glow.putalpha(disc(-4 * SCALE).filter(ImageFilter.GaussianBlur(7 * SCALE)).point(lambda a: a * 150 // 255))
            medal.alpha_composite(glow)
        rim = Image.linear_gradient("L").rotate(-35, resample=Image.BICUBIC).resize(medal.size)
        metal = Image.composite(Image.new("RGB", medal.size, dark), Image.new("RGB", medal.size, light), rim)
        medal.paste(metal, (0, 0), disc(0))
        face = Image.composite(Image.new("RGB", medal.size, (22, 20, 34)), Image.new("RGB", medal.size, (46, 42, 64)),
                               Image.linear_gradient("L").resize(medal.size))
        medal.paste(face, (0, 0), disc(5 * SCALE))
        icon = _icon(BADGE_ICONS[badge_id], int(size * 0.56))
    else:
        medal.paste((44, 42, 58), (0, 0), disc(0))
        medal.paste((24, 23, 34), (0, 0), disc(4 * SCALE))
        icon = _dimmed(_icon(BADGE_ICONS[badge_id], int(size * 0.5)))
    medal.alpha_composite(icon, ((medal.width - icon.width) // 2, (medal.height - icon.height) // 2))
    if not earned:
        lock = _icon(LOCK_ICON, 18)
        medal.alpha_composite(lock, (box[2] - lock.width + 2 * SCALE, box[3] - lock.height + 2 * SCALE))
    return medal


def _xp_ring(card: Image.Image, center: tuple[int, int], radius: int, width: int, fraction: float,
             accent: tuple[int, int, int]):
    """The level progress as a ring around the avatar."""
    s = SCALE
    layer = Image.new("RGBA", card.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    box = ((center[0] - radius) * s, (center[1] - radius) * s, (center[0] + radius) * s, (center[1] + radius) * s)
    draw.ellipse(box, outline=(255, 255, 255, 30), width=width * s)
    if fraction > 0:
        draw.arc(box, -90, -90 + 360 * min(1.0, fraction), fill=accent + (255,), width=width * s)
    card.alpha_composite(layer)


def _pill(draw: ImageDraw.ImageDraw, center_x: float, center_y: float, text: str, font, fill, outline, text_fill):
    s = SCALE
    width = font.getlength(text) / s + 30
    draw.rounded_rectangle(((center_x - width / 2) * s, (center_y - 17) * s, (center_x + width / 2) * s,
                            (center_y + 17) * s), radius=17 * s, fill=fill, outline=outline, width=2 * s)
    draw.text((center_x * s, center_y * s), text, font=font, fill=text_fill, anchor="mm")
    return width


def render_profile_card(data: CardData, avatar_bytes: bytes | None = None) -> bytes:
    """Draw the card and return it as PNG bytes."""
    card = _background()
    card.alpha_composite(_accent_glow(data.accent))
    card.alpha_composite(_suit_pattern(data.accent))
    overlay = Image.new("RGBA", card.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    s = SCALE
    right = WIDTH - MARGIN

    # ---------- avatar with the level ring ----------
    avatar_size, avatar_x, avatar_y = 136, MARGIN + 8, MARGIN + 8
    avatar_center = (avatar_x + avatar_size // 2, avatar_y + avatar_size // 2)
    fraction = data.xp_into_level / data.level_span if data.level_span else 1.0

    # ---------- name, title, rank ----------
    left = avatar_x + avatar_size + 44
    rank_text = f"RANK #{data.rank}" if data.rank else "UNRANKED"
    rank_font = _font(19)
    rank_width = int(rank_font.getlength(rank_text) / s) + 32
    _pill(draw, right - rank_width / 2, MARGIN + 26, rank_text, rank_font, data.accent + (45,), data.accent + (200,), TEXT)

    name = clean_name(data.name)
    name_x = left * s
    for text, font in _fit_name(name, 46, "ExtraBold", right - rank_width - left - 20):
        draw.text((name_x, (MARGIN + 50) * s), text, font=font, fill=TEXT, anchor="ls")
        name_x += font.getlength(text)
    title_x = left + 38
    draw.text((title_x * s, (MARGIN + 66) * s), data.title.upper(), font=_font(22, "ExtraBold"), fill=data.accent)
    to_next = max(0, data.level_span - data.xp_into_level)
    draw.text((left * s, (MARGIN + 112) * s),
              f"{data.xp_into_level:,} / {data.level_span:,} XP  ·  {to_next:,} to level {data.level + 1}",
              font=_font(17, "SemiBold"), fill=MUTED)
    # A thin XP bar under the text, matching the ring
    bar_top = MARGIN + 140
    draw.rounded_rectangle((left * s, bar_top * s, right * s, (bar_top + 8) * s), radius=4 * s, fill=BAR_EMPTY)
    draw.rounded_rectangle((left * s, bar_top * s, (left + max(8, int((right - left) * min(1.0, fraction)))) * s,
                            (bar_top + 8) * s), radius=4 * s, fill=data.accent + (255,))

    # ---------- stat tiles ----------
    tiles = [
        ("1fa99", f"{data.balance:,}", "COINS"),
        ("1f3b2", f"{data.games:,}", "GAMES"),
        ("1f3af", data.win_rate, "WIN RATE"),
        ("1f4b0", f"+{data.best_win:,}", "BEST WIN"),
        ("1f525", str(data.streak), "DAY STREAK"),
    ]
    tile_top, tile_height, gap = 226, 108, 14
    tile_width = (WIDTH - 2 * MARGIN - gap * (len(tiles) - 1)) / len(tiles)
    value_font, label_font = _font(28, "ExtraBold"), _font(13, "SemiBold")
    for index, (_, value, label) in enumerate(tiles):
        x = MARGIN + index * (tile_width + gap)
        draw.rounded_rectangle((x * s, tile_top * s, (x + tile_width) * s, (tile_top + tile_height) * s),
                               radius=16 * s, fill=PANEL, outline=(255, 255, 255, 18), width=s)
        center = (x + tile_width / 2) * s
        draw.text((center, (tile_top + 62) * s), _fit(value, value_font, int(tile_width) - 16),
                  font=value_font, fill=TEXT, anchor="mm")
        draw.text((center, (tile_top + 90) * s), label, font=label_font, fill=MUTED, anchor="mm")

    # ---------- badges ----------
    earned_count = len(data.earned_badges & BADGE_ICONS.keys())
    badges_top = 362
    draw.text((MARGIN * s, badges_top * s), "BADGES", font=_font(17, "ExtraBold"), fill=TEXT)
    count_text = f"{earned_count} / {len(BADGE_ICONS)}"
    draw.text(((MARGIN + 86) * s, badges_top * s), count_text, font=_font(17), fill=data.accent)
    bar_left = MARGIN + 86 + _font(17).getlength(count_text) / s + 18
    bar_y = badges_top + 9
    draw.rounded_rectangle((bar_left * s, bar_y * s, right * s, (bar_y + 6) * s), radius=3 * s, fill=BAR_EMPTY)
    share = earned_count / len(BADGE_ICONS)
    if share:
        draw.rounded_rectangle((bar_left * s, bar_y * s, (bar_left + (right - bar_left) * share) * s, (bar_y + 6) * s),
                               radius=3 * s, fill=data.accent + (255,))

    card.alpha_composite(overlay)
    _xp_ring(card, avatar_center, avatar_size // 2 + 10, 7, fraction, data.accent)
    card.alpha_composite(_avatar_circle(avatar_bytes, name, avatar_size, data.accent), (avatar_x * s, avatar_y * s))
    level_layer = Image.new("RGBA", card.size, (0, 0, 0, 0))
    _pill(ImageDraw.Draw(level_layer), avatar_center[0], avatar_y + avatar_size + 10, f"LV {data.level}",
          _font(17, "ExtraBold"), data.accent + (255,), (255, 255, 255, 220), (255, 255, 255))
    card.alpha_composite(level_layer)
    card.alpha_composite(_icon(TITLE_ICONS.get(data.title, "1fa99"), 30), (left * s, (MARGIN + 64) * s))
    for index, (_, (code, _, _)) in enumerate(zip(range(len(tiles)), tiles)):
        x = MARGIN + index * (tile_width + gap) + tile_width / 2 - 14
        card.alpha_composite(_icon(code, 28), (int(x * s), (tile_top + 12) * s))

    medal_size, row_height = 62, 80
    medal_gap = (WIDTH - 2 * MARGIN - medal_size * BADGES_PER_ROW) / (BADGES_PER_ROW - 1)
    for index, badge_id in enumerate(BADGE_ICONS):
        row, column = divmod(index, BADGES_PER_ROW)
        medal = _medal(badge_id, badge_id in data.earned_badges, medal_size)
        x = MARGIN + column * (medal_size + medal_gap) - MEDAL_PAD
        y = badges_top + 36 + row * row_height - MEDAL_PAD
        card.alpha_composite(medal, (int(x * s), int(y * s)))

    return _finish(card, HEIGHT)


def _finish(card: Image.Image, height: int) -> bytes:
    """Shrink for smooth edges, round the corners and encode as PNG."""
    final = card.resize((WIDTH, height), Image.LANCZOS)
    corners = Image.new("L", (WIDTH * 4, height * 4), 0)
    ImageDraw.Draw(corners).rounded_rectangle((0, 0, WIDTH * 4 - 1, height * 4 - 1), radius=28 * 4, fill=255)
    final.putalpha(corners.resize((WIDTH, height), Image.LANCZOS))

    output = io.BytesIO()
    final.save(output, format="PNG", optimize=True)
    return output.getvalue()
