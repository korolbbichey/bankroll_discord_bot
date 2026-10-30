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

from PIL import Image, ImageDraw, ImageFont, ImageOps

ASSETS = Path(__file__).parent / "assets"
FONT_FILE = ASSETS / "fonts" / "Montserrat.ttf"
FALLBACK_FONT_FILE = ASSETS / "fonts" / "NotoSansSC.ttf"  # Chinese and Japanese names
MISSING_GLYPH = "\U0010FFFF"  # never assigned, so every font draws its "missing" box for it
DEFAULT_NAME = "Player"

SCALE = 2
WIDTH, HEIGHT = 1000, 480
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
}
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


def render_profile_card(data: CardData, avatar_bytes: bytes | None = None) -> bytes:
    """Draw the card and return it as PNG bytes."""
    card = _background()
    card.alpha_composite(_accent_glow(data.accent))
    overlay = Image.new("RGBA", card.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    s = SCALE

    # ---------- avatar ----------
    avatar_size, avatar_x, avatar_y = 136, MARGIN + 4, MARGIN + 4
    ring = 5
    draw.ellipse(((avatar_x - ring) * s, (avatar_y - ring) * s,
                  (avatar_x + avatar_size + ring) * s, (avatar_y + avatar_size + ring) * s), fill=data.accent + (255,))

    # ---------- name, title, rank ----------
    left = avatar_x + avatar_size + 32
    right = WIDTH - MARGIN
    rank_text = f"RANK #{data.rank}" if data.rank else "UNRANKED"
    rank_font = _font(19)
    rank_width = int(rank_font.getlength(rank_text) / s) + 32
    draw.rounded_rectangle(((right - rank_width) * s, (MARGIN + 6) * s, right * s, (MARGIN + 44) * s),
                           radius=19 * s, fill=data.accent + (45,), outline=data.accent + (200,), width=2 * s)
    draw.text(((right - rank_width / 2) * s, (MARGIN + 25) * s), rank_text, font=rank_font, fill=TEXT, anchor="mm")

    name = clean_name(data.name)
    name_x = left * s
    for text, font in _fit_name(name, 44, "ExtraBold", right - rank_width - left - 20):
        draw.text((name_x, (MARGIN + 46) * s), text, font=font, fill=TEXT, anchor="ls")
        name_x += font.getlength(text)
    draw.text((left * s, (MARGIN + 62) * s), f"{data.title.upper()}  ·  LEVEL {data.level}",
              font=_font(21), fill=data.accent)

    # ---------- XP bar ----------
    bar_top, bar_height = MARGIN + 112, 24
    draw.rounded_rectangle((left * s, bar_top * s, right * s, (bar_top + bar_height) * s),
                           radius=bar_height // 2 * s, fill=BAR_EMPTY)
    fraction = min(1.0, data.xp_into_level / data.level_span) if data.level_span else 1.0
    fill_width = max(bar_height, int((right - left) * fraction))
    draw.rounded_rectangle((left * s, bar_top * s, (left + fill_width) * s, (bar_top + bar_height) * s),
                           radius=bar_height // 2 * s, fill=data.accent + (255,))
    draw.text((right * s, (bar_top - 9) * s), f"{data.xp_into_level:,} / {data.level_span:,} XP",
              font=_font(16, "SemiBold"), fill=MUTED, anchor="rs")

    # ---------- stat tiles ----------
    tiles = [
        (f"{data.balance:,}", "COINS"),
        (f"{data.games:,}", "GAMES"),
        (data.win_rate, "WIN RATE"),
        (f"+{data.best_win:,}", "BEST WIN"),
        (str(data.streak), "DAY STREAK"),
    ]
    tile_top, tile_height, gap = 212, 96, 14
    tile_width = (WIDTH - 2 * MARGIN - gap * (len(tiles) - 1)) / len(tiles)
    value_font, label_font = _font(30, "ExtraBold"), _font(14, "SemiBold")
    for index, (value, label) in enumerate(tiles):
        x = MARGIN + index * (tile_width + gap)
        draw.rounded_rectangle((x * s, tile_top * s, (x + tile_width) * s, (tile_top + tile_height) * s),
                               radius=14 * s, fill=PANEL)
        center = (x + tile_width / 2) * s
        draw.text((center, (tile_top + 40) * s), _fit(value, value_font, int(tile_width) - 16),
                  font=value_font, fill=TEXT, anchor="mm")
        draw.text((center, (tile_top + 72) * s), label, font=label_font, fill=MUTED, anchor="mm")

    # ---------- badges ----------
    earned_count = len(data.earned_badges & BADGE_ICONS.keys())
    badges_top = 330
    draw.text((MARGIN * s, badges_top * s), f"BADGES  {earned_count} / {len(BADGE_ICONS)}",
              font=_font(16), fill=MUTED)
    draw.text((right * s, (badges_top + 17) * s), "BANKROLL", font=_font(16, "ExtraBold"), fill=MUTED, anchor="rs")

    card.alpha_composite(overlay)
    card.alpha_composite(_avatar_circle(avatar_bytes, name, avatar_size, data.accent), (avatar_x * s, avatar_y * s))

    # A small title icon on the avatar's edge
    title_icon = _icon(TITLE_ICONS.get(data.title, "1fa99"), 44)
    card.alpha_composite(title_icon, ((avatar_x + avatar_size - 40) * s, (avatar_y + avatar_size - 40) * s))

    icon_size, count = 54, len(BADGE_ICONS)
    icon_gap = (WIDTH - 2 * MARGIN - icon_size * count) / (count - 1)
    for index, (badge_id, code) in enumerate(BADGE_ICONS.items()):
        icon = _icon(code, icon_size)
        if badge_id not in data.earned_badges:
            icon = _dimmed(icon)
        card.alpha_composite(icon, (int((MARGIN + index * (icon_size + icon_gap)) * s), (badges_top + 42) * s))

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
