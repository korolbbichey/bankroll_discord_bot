import asyncio

import pytest

import main
from bot.commands import vote

from conftest import make_interaction

VOTE = {"created_at": "2026-11-22T12:00:00.000Z", "expires_at": "2026-11-23T00:00:00.000Z", "weight": 1}


@pytest.fixture
def topgg(monkeypatch):
    """Top.gg's answer for the next /vote: a vote dict, None (no vote) or an exception."""
    monkeypatch.setenv("TOPGG_TOKEN", "test-token")
    answer = {"vote": VOTE}

    async def latest_vote(user_id, token):
        assert token == "test-token"
        if isinstance(answer["vote"], Exception):
            raise answer["vote"]
        return answer["vote"]
    monkeypatch.setattr(vote, "latest_vote", latest_vote)
    return answer


def use_vote(user_id=1):
    async def go():
        client = main.BankRollBot()
        vote.setup(client)
        interaction = make_interaction(user_id, done=False)
        await client.tree.get_command("vote").callback(interaction)
        return interaction
    return asyncio.run(go())


def sent(interaction):
    call = interaction.followup.send.call_args
    embed = call.kwargs.get("embed")
    return (embed.title + " " + (embed.description or "")) if embed else call.args[0]


def test_a_vote_pays_once(db, topgg):
    assert "+500 coins" in sent(use_vote())
    assert db.get_balance(1) == 600
    assert "already got the reward" in sent(use_vote())
    assert db.get_balance(1) == 600


def test_the_next_vote_pays_again(db, topgg):
    use_vote()
    topgg["vote"] = {**VOTE, "created_at": "2026-11-23T01:00:00.000Z"}
    assert "+500 coins" in sent(use_vote())
    assert db.get_balance(1) == 1100


def test_weekend_votes_pay_double(db, topgg):
    topgg["vote"] = {**VOTE, "weight": 2}
    text = sent(use_vote())
    assert "+1,000 coins" in text and "double" in text


def test_no_vote_shows_the_link(db, topgg):
    topgg["vote"] = None
    interaction = use_vote()
    assert "use `/vote` again" in sent(interaction)
    assert interaction.followup.send.call_args.kwargs["view"] is not None
    assert db.get_balance(1) == 100


def test_topgg_down(db, topgg):
    topgg["vote"] = vote.TopggError("status 502")
    assert "Couldn't reach top.gg" in sent(use_vote())
    assert db.get_balance(1) == 100


def test_without_a_token_only_the_link(db, monkeypatch):
    monkeypatch.delenv("TOPGG_TOKEN", raising=False)
    interaction = use_vote()
    assert interaction.response.send_message.call_args.kwargs["view"] is not None
    assert db.get_balance(1) == 100


def test_claim_is_per_player(db):
    assert db.claim_vote_reward(1, "a", 100) == 200
    assert db.claim_vote_reward(2, "a", 100) == 200
    assert db.claim_vote_reward(1, "a", 100) is None
