from bot.config import MIN_BET, MAX_BET
from bot.utils import fmt, display_name, validate_bet

from conftest import make_user


def test_fmt_adds_thousands_separators():
    assert fmt(0) == "0"
    assert fmt(999) == "999"
    assert fmt(1000) == "1,000"
    assert fmt(110710099) == "110,710,099"


def test_display_name_prefers_global_name():
    assert display_name(make_user(1, name="raw_name", global_name="Pretty Name")) == "Pretty Name"
    assert display_name(make_user(1, name="raw_name", global_name=None)) == "raw_name"


def test_validate_bet():
    assert validate_bet(MIN_BET, 100) == (True, "")
    assert not validate_bet(MIN_BET - 1, 100)[0]
    assert not validate_bet(MAX_BET + 1, 10**9)[0]
    ok, message = validate_bet(500, 100)
    assert not ok and "100" in message
