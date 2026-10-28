"""
Shared test setup.

Environment variables are set before any bot module is imported, so importing main.py
never touches the real bot_data.db and never needs a real Discord token.
Nothing in the test suite connects to Discord.
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

os.environ["DISCORD_BOT_TOKEN"] = "test-token"
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "import.db")
os.environ.pop("ADMIN_GUILD_ID", None)
os.environ.pop("OWNER_IDS", None)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from bot import database  # noqa: E402


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    """Give every test its own empty database."""
    monkeypatch.setattr(database, "DB_FILE", str(tmp_path / "test.db"))
    database.init_db()
    return database


def make_user(user_id: int, name: str = None, global_name: str = None, bot: bool = False):
    user = MagicMock()
    user.id = user_id
    user.name = name or f"user{user_id}"
    user.global_name = global_name
    user.bot = bot
    user.mention = f"<@{user_id}>"
    user.display_avatar.url = "https://example.com/avatar.png"
    return user


def make_interaction(user_id: int = 1, guild_id: int | None = 100, done: bool = True, user=None):
    """A fake discord.Interaction whose responses are recorded instead of sent."""
    interaction = MagicMock()
    interaction.user = user or make_user(user_id)
    interaction.guild_id = guild_id

    # is_done() becomes True once the interaction has been responded to, like in discord.py
    state = {"done": done}

    def respond(*args, **kwargs):
        state["done"] = True

    interaction.response.is_done = lambda: state["done"]
    interaction.response.send_message = AsyncMock(side_effect=respond)
    interaction.response.edit_message = AsyncMock(side_effect=respond)
    interaction.response.defer = AsyncMock(side_effect=respond)
    interaction.edit_original_response = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


def sent_embed(mock: AsyncMock):
    """The embed passed to the last call of a send/edit mock."""
    return mock.call_args.kwargs["embed"]
