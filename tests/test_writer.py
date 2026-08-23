"""Tests for the async writer module."""

import re
from unittest.mock import AsyncMock

import pytest

from chat_recall_prod.writer import (
    push_content,
    conversation_id_for,
    _get_or_create_push_source,
)


@pytest.mark.asyncio
async def test_get_or_create_push_source_existing():
    db = AsyncMock()
    conn = AsyncMock()
    mock_cur = AsyncMock()
    mock_cur.fetchone = AsyncMock(return_value={"id": 42})
    conn.execute = AsyncMock(return_value=mock_cur)

    result = await _get_or_create_push_source(db, conn, "push")
    assert result == 42
    db.insert_source.assert_not_called()


@pytest.mark.asyncio
async def test_get_or_create_push_source_new():
    db = AsyncMock()
    conn = AsyncMock()
    mock_cur = AsyncMock()
    mock_cur.fetchone = AsyncMock(return_value=None)
    conn.execute = AsyncMock(return_value=mock_cur)
    db.insert_source = AsyncMock(return_value=99)

    result = await _get_or_create_push_source(db, conn, "push")
    assert result == 99
    db.insert_source.assert_called_once()


@pytest.mark.asyncio
async def test_push_content_with_title():
    db = AsyncMock()
    conn = AsyncMock()
    mock_cur = AsyncMock()
    mock_cur.fetchone = AsyncMock(return_value={"id": 1})
    conn.execute = AsyncMock(return_value=mock_cur)
    db.insert_conversation = AsyncMock()
    db.insert_messages_batch = AsyncMock(return_value=1)

    result = await push_content(
        db, conn, "user-1",
        content="Hello world",
        title="My Note",
        tags=["test"],
        project="my-project",
    )

    assert result["title"] == "My Note"
    assert result["tags"] == ["test"]
    assert result["conversation_id"].startswith("push-")
    db.insert_conversation.assert_called_once()
    db.insert_messages_batch.assert_called_once()


@pytest.mark.asyncio
async def test_push_content_auto_title():
    db = AsyncMock()
    conn = AsyncMock()
    mock_cur = AsyncMock()
    mock_cur.fetchone = AsyncMock(return_value={"id": 1})
    conn.execute = AsyncMock(return_value=mock_cur)
    db.insert_conversation = AsyncMock()
    db.insert_messages_batch = AsyncMock(return_value=1)

    result = await push_content(
        db, conn, "user-1",
        content="# My Heading\nSome body text",
    )

    assert result["title"] == "My Heading"


@pytest.mark.asyncio
async def test_push_content_auto_title_untitled():
    db = AsyncMock()
    conn = AsyncMock()
    mock_cur = AsyncMock()
    mock_cur.fetchone = AsyncMock(return_value={"id": 1})
    conn.execute = AsyncMock(return_value=mock_cur)
    db.insert_conversation = AsyncMock()
    db.insert_messages_batch = AsyncMock(return_value=1)

    result = await push_content(
        db, conn, "user-1",
        content="   ",
    )

    assert result["title"] == "Untitled"


@pytest.mark.asyncio
async def test_push_content_none_user_id():
    """Stdio mode — user_id is None."""
    db = AsyncMock()
    conn = AsyncMock()
    mock_cur = AsyncMock()
    mock_cur.fetchone = AsyncMock(return_value={"id": 1})
    conn.execute = AsyncMock(return_value=mock_cur)
    db.insert_conversation = AsyncMock()
    db.insert_messages_batch = AsyncMock(return_value=1)

    result = await push_content(
        db, conn, None,
        content="Test content",
        title="Test",
    )

    assert result["conversation_id"].startswith("push-")
    # user_id=None passed to insert_conversation
    call_args = db.insert_conversation.call_args
    assert call_args[0][1] is None  # user_id positional arg


# ── SWIT-22: upsert by external_id ──────────────────────────────────────────
# push_content could only ever create: the conversation id was a fresh uuid4
# every call. Anything re-captured as it changed (a Slack thread still getting
# replies, a doc being revised) piled up duplicates, which is why the meetings
# corpus has to be deduped by (title, create_time) at read time.


def _mock_db(existing=None):
    """A db double whose get_conversation answers with `existing`.

    Spelled out because a bare AsyncMock returns a truthy MagicMock from every
    await — which would make the replace branch look taken in every test.
    """
    db = AsyncMock()
    db.get_conversation = AsyncMock(return_value=existing)
    db.insert_conversation = AsyncMock()
    db.update_conversation = AsyncMock()
    db.delete_messages = AsyncMock(return_value=1)
    db.insert_messages_batch = AsyncMock(return_value=1)
    return db


def _mock_conn():
    conn = AsyncMock()
    cur = AsyncMock()
    cur.fetchone = AsyncMock(return_value={"id": 1})
    conn.execute = AsyncMock(return_value=cur)
    return conn


@pytest.mark.asyncio
async def test_external_id_creates_when_nothing_is_stored():
    db = _mock_db(existing=None)

    result = await push_content(
        db, _mock_conn(), "user-1",
        content="thread body",
        external_id="C123:1700000000.1",
    )

    assert result["replaced"] is False
    db.insert_conversation.assert_called_once()
    db.update_conversation.assert_not_called()
    db.delete_messages.assert_not_called()


@pytest.mark.asyncio
async def test_external_id_replaces_what_is_already_stored():
    db = _mock_db(existing={"id": "push-abc", "create_time": 100.0})

    result = await push_content(
        db, _mock_conn(), "user-1",
        content="thread body, now with more replies",
        external_id="C123:1700000000.1",
    )

    assert result["replaced"] is True
    # Not a second row: the old messages go, the conversation is updated in
    # place, and insert_conversation (ON CONFLICT DO NOTHING) is never reached.
    db.delete_messages.assert_called_once()
    db.update_conversation.assert_called_once()
    db.insert_conversation.assert_not_called()
    db.insert_messages_batch.assert_called_once()


@pytest.mark.asyncio
async def test_replace_moves_update_time_but_keeps_create_time():
    """First-seen has to survive a re-push, or a refreshed thread looks new.

    CC-575 leans on exactly this: create_time is when the Slack thread started,
    update_time is its last reply, and they can be weeks apart.
    """
    db = _mock_db(existing={"id": "push-abc", "create_time": 100.0})

    await push_content(
        db, _mock_conn(), "user-1",
        content="more",
        external_id="C123:1700000000.1",
    )

    kwargs = db.update_conversation.call_args.kwargs
    assert "update_time" in kwargs
    assert "create_time" not in kwargs


@pytest.mark.asyncio
async def test_same_external_id_maps_to_the_same_entry():
    db = _mock_db(existing=None)
    conn = _mock_conn()

    first = await push_content(
        db, conn, "user-1", content="v1", external_id="thread-7"
    )
    second = await push_content(
        db, conn, "user-1", content="v2", external_id="thread-7"
    )

    assert first["conversation_id"] == second["conversation_id"]


@pytest.mark.asyncio
async def test_external_id_is_scoped_per_user():
    """conversations.id is globally unique, not unique per user.

    If two users' identical external ids produced one id, the second writer
    would hit insert_conversation's ON CONFLICT DO NOTHING and its content
    would silently vanish into the first user's row.
    """
    db = _mock_db(existing=None)
    conn = _mock_conn()

    mine = await push_content(db, conn, "user-1", content="x", external_id="k")
    theirs = await push_content(db, conn, "user-2", content="x", external_id="k")

    assert mine["conversation_id"] != theirs["conversation_id"]


@pytest.mark.asyncio
async def test_without_external_id_every_push_is_a_new_entry():
    """The pre-existing contract. No caller changes behavior by upgrading."""
    db = _mock_db(existing={"id": "push-abc"})  # would be a replace if consulted
    conn = _mock_conn()

    first = await push_content(db, conn, "user-1", content="a")
    second = await push_content(db, conn, "user-1", content="a")

    assert first["conversation_id"] != second["conversation_id"]
    assert first["replaced"] is False
    assert second["replaced"] is False
    db.get_conversation.assert_not_called()


def test_conversation_id_survives_a_hostile_external_id():
    """External ids are caller-supplied and land in a primary key.

    Hashing means the length and character set are ours, not theirs — a path,
    a URL, or emoji all come out the same shape.
    """
    for raw in ["C123:170.1", "a/b/c d", "emoji-\U0001f600", "x" * 5000, ""]:
        conv_id = conversation_id_for("user-1", raw)
        assert re.fullmatch(r"push-[0-9a-f]{32}", conv_id), conv_id


def test_conversation_id_differs_for_stdio_and_authenticated_users():
    assert conversation_id_for(None, "k") != conversation_id_for("user-1", "k")
