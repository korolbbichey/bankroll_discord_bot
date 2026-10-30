"""
Draws the /leaderboard card as a PNG with Pillow, in the same style as the profile card.
Knows nothing about Discord or the database.
"""

from dataclasses import dataclass

from PIL import Image, ImageDraw

from .profile_card import (
    MARGIN, MUTED, PANEL, SCALE, TEXT, WIDTH,
    _avatar_circle, _background, _finish, _fit, _fit_name, _font, _icon, _runs_width, clean_name,
)

GOLD = (241, 196, 15)
SILVER = (192, 199, 208)
BRONZE = (205, 127, 50)
HIGHLIGHT = (88, 101, 242)

HEADER_HEIGHT = 96
PODIUM_HEIGHT = 322
ROW_HEIGHT = 56
ROW_GAP = 8
AVATAR_IN_ROW = 40
ICON_COIN = "1fa99"
ICON_CROWN = "1f451"
ICON_TROPHY = "1f3c6"

# rank: (center x, how far below the top it starts, avatar size, color)
PODIUM_COLUMN = (WIDTH - 2 * MARGIN) / 3
PODIUM_LAYOUT = {
    2: (MARGIN + PODIUM_COLUMN * 0.5, 44, 104, SILVER),
    1: (MARGIN + PODIUM_COLUMN * 1.5, 0, 136, GOLD),
    3: (MARGIN + PODIUM_COLUMN * 2.5, 64, 104, BRONZE),
}


@dataclass
class LeaderboardEntry:
    rank: int
    name: str
    balance: int
    level: int
    avatar: bytes | None = None
    is_viewer: bool = False


def _draw_name_centered(draw, name: str, center_x: float, baseline: int, size: int, max_width: int):
    runs = _fit_name(clean_name(name), size, "ExtraBold", max_width)
    x = center_x * SCALE - _runs_width(runs) / 2
    for text, font in runs:
        draw.text((x, baseline * SCALE), text, font=font, fill=TEXT, anchor="ls")
        x += font.getlength(text)


def _draw_podium(card: Image.Image, draw, entries: list[LeaderboardEntry], top: int):
    """Places 1-3: the winner in the middle and higher, with a bigger avatar."""
    s = SCALE
    column = PODIUM_COLUMN
    bottom = top + PODIUM_HEIGHT - 12
    for entry in entries:
        center, drop, avatar_size, color = PODIUM_LAYOUT[entry.rank]
        panel_top = top + drop + avatar_size // 2
        draw.rounded_rectangle(((center - column / 2 + 8) * s, panel_top * s, (center + column / 2 - 8) * s, bottom * s),
                               radius=18 * s, fill=color + (20,), outline=color + (90,), width=2 * s)

        text_top = panel_top + avatar_size // 2 + 12
        _draw_name_centered(draw, entry.name, center, text_top + 28, 26, int(column) - 44)
        draw.text((center * s, (text_top + 58) * s), f"LEVEL {entry.level}", font=_font(15, "SemiBold"), fill=MUTED, anchor="ms")
        balance_font = _font(30, "ExtraBold")
        draw.text((center * s, (text_top + 98) * s), _fit(f"{entry.balance:,}", balance_font, int(column) - 44),
                  font=balance_font, fill=color, anchor="ms")


def _paste_podium_images(card: Image.Image, entries: list[LeaderboardEntry], top: int):
    s = SCALE
    column = PODIUM_COLUMN
    for entry in entries:
        center, drop, avatar_size, color = PODIUM_LAYOUT[entry.rank]
        x, y = int(center - avatar_size / 2), top + drop
        ring = 5
        ring_layer = Image.new("RGBA", ((avatar_size + 2 * ring) * s, (avatar_size + 2 * ring) * s), (0, 0, 0, 0))
        ImageDraw.Draw(ring_layer).ellipse((0, 0, ring_layer.width - 1, ring_layer.height - 1), fill=color + (255,))
        card.alpha_composite(ring_layer, ((x - ring) * s, (y - ring) * s))
        card.alpha_composite(_avatar_circle(entry.avatar, clean_name(entry.name), avatar_size, color), (x * s, y * s))
        if entry.rank == 1:
            card.alpha_composite(_icon(ICON_CROWN, 48), (int(center - 24) * s, (y - 34) * s))


def _draw_row(card: Image.Image, draw, entry: LeaderboardEntry, top: int):
    s = SCALE
    left, right = MARGIN, WIDTH - MARGIN
    if entry.is_viewer:
        draw.rounded_rectangle((left * s, top * s, right * s, (top + ROW_HEIGHT) * s), radius=14 * s,
                               fill=HIGHLIGHT + (60,), outline=HIGHLIGHT + (230,), width=2 * s)
    else:
        draw.rounded_rectangle((left * s, top * s, right * s, (top + ROW_HEIGHT) * s), radius=14 * s, fill=PANEL)

    middle = top + ROW_HEIGHT // 2
    draw.text(((left + 42) * s, middle * s), f"{entry.rank:,}", font=_font(20, "ExtraBold"),
              fill=TEXT if entry.is_viewer else MUTED, anchor="rm")

    name_x = (left + 118) * s
    for text, font in _fit_name(clean_name(entry.name), 22, "Bold", 440):
        draw.text((name_x, (middle + 8) * s), text, font=font, fill=TEXT, anchor="ls")
        name_x += font.getlength(text)

    balance_font = _font(22, "ExtraBold")
    balance = f"{entry.balance:,}"
    draw.text(((right - 54) * s, middle * s), balance, font=balance_font, fill=TEXT, anchor="rm")
    level_right = right - 54 - balance_font.getlength(balance) / s - 28
    draw.text((level_right * s, middle * s), f"LV {entry.level}", font=_font(14, "SemiBold"), fill=MUTED, anchor="rm")


def _paste_row_images(card: Image.Image, entry: LeaderboardEntry, top: int):
    s = SCALE
    avatar_y = top + (ROW_HEIGHT - AVATAR_IN_ROW) // 2
    accent = HIGHLIGHT if entry.is_viewer else (90, 86, 110)
    card.alpha_composite(_avatar_circle(entry.avatar, clean_name(entry.name), AVATAR_IN_ROW, accent),
                         ((MARGIN + 62) * s, avatar_y * s))
    card.alpha_composite(_icon(ICON_COIN, 26), ((WIDTH - MARGIN - 42) * s, (top + (ROW_HEIGHT - 26) // 2) * s))


def render_leaderboard_card(entries: list[LeaderboardEntry], total_players: int,
                            viewer: LeaderboardEntry | None = None) -> bytes:
    """
    Draw the leaderboard. entries are ordered from rank 1 and should hold at most 10 players.
    viewer is an extra row at the bottom, for a player outside the list.
    """
    s = SCALE
    podium = [entry for entry in entries if entry.rank <= 3]
    rows = [entry for entry in entries if entry.rank > 3]
    rows_top = HEADER_HEIGHT + PODIUM_HEIGHT
    rows_height = len(rows) * (ROW_HEIGHT + ROW_GAP)
    viewer_height = (ROW_HEIGHT + 22) if viewer else 0
    height = rows_top + rows_height + viewer_height + MARGIN - (ROW_GAP if rows and not viewer else 0)

    card = _background(height)
    overlay = Image.new("RGBA", card.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    draw.text(((MARGIN + 52) * s, 56 * s), "LEADERBOARD", font=_font(34, "ExtraBold"), fill=TEXT, anchor="lm")
    players = f"{total_players:,} PLAYER{'S' if total_players != 1 else ''}"
    draw.text(((WIDTH - MARGIN) * s, 56 * s), players, font=_font(18), fill=MUTED, anchor="rm")

    _draw_podium(card, draw, podium, HEADER_HEIGHT)
    row_tops = [rows_top + index * (ROW_HEIGHT + ROW_GAP) for index in range(len(rows))]
    for entry, top in zip(rows, row_tops):
        _draw_row(card, draw, entry, top)
    viewer_top = rows_top + rows_height + 14
    if viewer:
        _draw_row(card, draw, viewer, viewer_top)

    card.alpha_composite(overlay)
    card.alpha_composite(_icon(ICON_TROPHY, 42), (MARGIN * s, 35 * s))
    _paste_podium_images(card, podium, HEADER_HEIGHT)
    for entry, top in zip(rows, row_tops):
        _paste_row_images(card, entry, top)
    if viewer:
        _paste_row_images(card, viewer, viewer_top)

    return _finish(card, height)
