import io

import pytest
from PIL import Image

from bot.profile_card import BADGE_ICONS, TITLE_ICONS, ASSETS, CardData, clean_name, render_profile_card
from bot.progression import BADGES, TITLES


def card_data(**overrides) -> CardData:
    values = dict(
        name="Alice", title="Gambler", accent=(46, 204, 113), level=3, xp_into_level=250, level_span=300,
        balance=102, rank=11, games=49, win_rate="27%", best_win=400, streak=0, earned_badges={"first_win"},
    )
    return CardData(**{**values, **overrides})


def rendered_image(data: CardData, avatar: bytes | None = None) -> Image.Image:
    return Image.open(io.BytesIO(render_profile_card(data, avatar)))


def avatar_png() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 30, 30)).save(output, format="PNG")
    return output.getvalue()


def test_card_is_a_png_of_the_right_size():
    image = rendered_image(card_data())
    assert image.format == "PNG" and image.size == (1000, 480)


def test_card_draws_the_avatar():
    without, with_avatar = rendered_image(card_data()), rendered_image(card_data(), avatar_png())
    assert with_avatar.convert("RGB").getpixel((90, 112)) != without.convert("RGB").getpixel((90, 112))
    assert with_avatar.convert("RGB").getpixel((90, 112))[0] > 150, "the red avatar is visible"


def test_every_badge_and_title_has_an_icon():
    assert list(BADGE_ICONS) == [badge.id for badge in BADGES], "same badges, same order"
    assert set(TITLE_ICONS) == {title.name for title in TITLES}
    for code in [*BADGE_ICONS.values(), *TITLE_ICONS.values()]:
        assert (ASSETS / "icons" / f"{code}.png").is_file(), code


@pytest.mark.parametrize("name, expected", [
    ("hul1gan", "hul1gan"),
    ("Леонид", "Леонид"),
    ("小熊维尼", "小熊维尼"),
    ("𝓜.", "M."),                # decorative letters become plain ones
    ("Bob 😀", "Bob"),            # emoji have no glyph and are dropped
    ("😀😀", "Player"),           # nothing left to draw
    ("   ", "Player"),
])
def test_clean_name(name, expected):
    assert clean_name(name) == expected


@pytest.mark.parametrize("name", ["小熊维尼 and friends", "A" * 200, "😀", "ع", ""])
def test_any_name_can_be_drawn(name):
    assert rendered_image(card_data(name=name)).size == (1000, 480)


def test_extreme_values_can_be_drawn():
    data = card_data(balance=10**15, games=10**9, best_win=10**12, streak=9999, rank=None, level=999,
                     xp_into_level=0, level_span=99800, earned_badges=set(BADGE_ICONS))
    assert rendered_image(data).size == (1000, 480)
