import asyncio

import main
from bot.commands import economy

from conftest import make_interaction, make_user


def paystats(db, user_id, target=None):
    async def go():
        client = main.BankRollBot()
        economy.setup(client)
        interaction = make_interaction(user_id, done=False)
        await client.tree.get_command("paystats").callback(interaction, target)
        return interaction.response.send_message.call_args.kwargs["embed"]
    return asyncio.run(go())


def test_transfers_are_added_up(db):
    db.set_balance(1, 10_000)
    db.set_balance(2, 10_000)
    db.save_username(1, "Jack")
    db.save_username(2, "Taru")
    db.transfer(2, 1, 3000)
    db.transfer(2, 1, 500)
    db.transfer(1, 2, 1000)
    assert db.get_pay_stats(1) == {"got": [(2, "Taru", 3500, 2)], "sent": [(2, "Taru", 1000, 1)]}


def test_failed_transfers_dont_count(db):
    db.set_balance(1, 10)
    assert not db.transfer(1, 2, 500)
    assert db.get_pay_stats(1) == {"got": [], "sent": []}


def test_paystats_shows_who_owes_whom(db):
    for user_id, name in ((1, "Jack"), (2, "Taru"), (3, "Spar")):
        db.set_balance(user_id, 10_000)
        db.save_username(user_id, name)
    db.transfer(2, 1, 5000)
    db.transfer(3, 1, 2000)
    db.transfer(1, 3, 2500)

    mine = paystats(db, 1)
    fields = {f.name: f.value for f in mine.fields}
    assert mine.title == "💸 Your transfers"
    assert "Got **7,000**" in mine.description and "Sent **2,500**" in mine.description
    assert fields["📥 Got from"] == "Taru **5,000** (1×)\nSpar **2,000** (1×)"
    assert fields["⚖️ Who owes whom"] == "You owe Taru **5,000**\nSpar owes you **500**"

    theirs = paystats(db, 2, make_user(1))
    assert theirs.title.endswith("'s transfers")
    assert "owes Taru **5,000**" in {f.name: f.value for f in theirs.fields}["⚖️ Who owes whom"]


def test_paystats_without_transfers(db):
    assert "haven't sent or got any coins" in paystats(db, 1).description


def test_old_big_transfers_are_copied_once(db):
    db.record_coin_event(1, "pay", 2000, "from 2")
    db.record_coin_event(1, "slots", 5000)
    with db.get_connection() as conn:
        conn.execute("DROP TABLE pay_totals")  # as before this update
    db.init_db()
    db.init_db()
    assert db.get_pay_stats(1)["got"] == [(2, None, 2000, 1)]
