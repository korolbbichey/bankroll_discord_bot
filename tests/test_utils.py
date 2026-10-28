import pytest

from bot.config import MIN_BET, MAX_BET
from bot.utils import fmt, display_name, validate_bet, parse_bet, InvalidBet

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


@pytest.mark.parametrize("text, balance, expected", [
    ("500", 100, 500),           # numbers are taken as typed; validate_bet checks the balance
    (" 1,000 ", 0, 1000),
    ("2.5k", 0, 2500),
    ("1K", 0, 1000),
    ("all", 1234, 1234),
    ("ALL", 1234, 1234),
    ("half", 1234, 617),
    ("all", 50_000, MAX_BET),    # capped at the maximum bet
    ("half", 50_000, MAX_BET),
    ("all", 0, MIN_BET),         # an empty balance still gives a bet, so the player sees "not enough coins"
    ("half", 1, MIN_BET),
])
def test_parse_bet(text, balance, expected):
    assert parse_bet(text, balance) == expected


@pytest.mark.parametrize("text", ["lots", "", "1.5", "nan", "inf", "1e400", "k"])
def test_parse_bet_rejects_garbage(text):
    with pytest.raises(InvalidBet):
        parse_bet(text, 1000)
