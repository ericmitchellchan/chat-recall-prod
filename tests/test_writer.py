"""Tests for the async writer module."""

from unittest.mock import AsyncMock

import pytest

from chat_recall_prod.writer import push_content, _get_or_create_push_source


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
