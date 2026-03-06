"""Tests for the production MCP server tools."""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from chat_recall_prod import server
from chat_recall_prod.response_models import (
    ConversationDetail,
    ConversationListResult,
    ConversationSummary,
    MessageResult,
    RecallStats,
    SearchHit,
    SearchResult,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def mock_pool():
    """Mock the connection pool."""
    pool = MagicMock()
    conn = AsyncMock()
    ctx_manager = AsyncMock()
    ctx_manager.__aenter__ = AsyncMock(return_value=conn)
    ctx_manager.__aexit__ = AsyncMock(return_value=False)
    pool.connection.return_value = ctx_manager
    return pool, conn


@pytest.fixture(autouse=True)
def reset_server_state():
    """Reset module-level state between tests."""
    server._db = None
    yield
    server._db = None


# ── _get_user_id ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_user_id_from_env():
    with patch.dict(os.environ, {"RECALL_USER_ID": "user-123"}):
        result = await server._get_user_id(None)
        assert result == "user-123"


@pytest.mark.asyncio
async def test_get_user_id_none_when_unset():
    with patch.dict(os.environ, {}, clear=True):
        result = await server._get_user_id(None)
        assert result is None


# ── search_conversations ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_conversations(mock_pool):
    pool, conn = mock_pool
    expected = SearchResult(query="test", hits=[], total=0, page=1, page_size=20)

    with patch.object(server, "_get_user_id", return_value="user-1"), \
         patch("chat_recall_prod.server.get_pool", return_value=pool), \
         patch("chat_recall_prod.server.SearchEngine") as MockEngine:
        engine_instance = MockEngine.return_value
        engine_instance.search = AsyncMock(return_value=expected)

        result = await server.search_conversations.fn(query="test")

    assert result["total"] == 0
    assert result["query"] == "test"


@pytest.mark.asyncio
async def test_search_conversations_error(mock_pool):
    pool, conn = mock_pool

    with patch.object(server, "_get_user_id", return_value="user-1"), \
         patch("chat_recall_prod.server.get_pool", return_value=pool), \
         patch("chat_recall_prod.server.SearchEngine") as MockEngine:
        engine_instance = MockEngine.return_value
        engine_instance.search = AsyncMock(side_effect=Exception("DB error"))

        result = await server.search_conversations.fn(query="test")

    assert "error" in result


# ── list_conversations ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_conversations(mock_pool):
    pool, conn = mock_pool
    expected = ConversationListResult(conversations=[], total=0, page=1, page_size=20)

    with patch.object(server, "_get_user_id", return_value="user-1"), \
         patch("chat_recall_prod.server.get_pool", return_value=pool), \
         patch("chat_recall_prod.server.SearchEngine") as MockEngine:
        engine_instance = MockEngine.return_value
        engine_instance.list_conversations = AsyncMock(return_value=expected)

        result = await server.list_conversations.fn()

    assert result["total"] == 0


# ── get_conversation ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_conversation_found(mock_pool):
    pool, conn = mock_pool
    expected = ConversationDetail(
        id="conv-1", title="Test", messages=[
            MessageResult(role="user", content="Hello"),
        ],
    )

    with patch.object(server, "_get_user_id", return_value="user-1"), \
         patch("chat_recall_prod.server.get_pool", return_value=pool), \
         patch("chat_recall_prod.server.SearchEngine") as MockEngine:
        engine_instance = MockEngine.return_value
        engine_instance.get_conversation = AsyncMock(return_value=expected)

        result = await server.get_conversation.fn(conversation_id="conv-1")

    assert result["id"] == "conv-1"
    assert len(result["messages"]) == 1


@pytest.mark.asyncio
async def test_get_conversation_not_found(mock_pool):
    pool, conn = mock_pool

    with patch.object(server, "_get_user_id", return_value="user-1"), \
         patch("chat_recall_prod.server.get_pool", return_value=pool), \
         patch("chat_recall_prod.server.SearchEngine") as MockEngine:
        engine_instance = MockEngine.return_value
        engine_instance.get_conversation = AsyncMock(return_value=None)

        result = await server.get_conversation.fn(conversation_id="nonexistent")

    assert "error" in result
    assert "not found" in result["error"]


# ── recall_stats ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recall_stats(mock_pool):
    pool, conn = mock_pool
    expected = RecallStats(conversations=10, messages=500)

    with patch.object(server, "_get_user_id", return_value="user-1"), \
         patch("chat_recall_prod.server.get_pool", return_value=pool), \
         patch("chat_recall_prod.server.SearchEngine") as MockEngine:
        engine_instance = MockEngine.return_value
        engine_instance.get_stats = AsyncMock(return_value=expected)

        result = await server.recall_stats.fn()

    assert result["conversations"] == 10
    assert result["messages"] == 500


# ── push_content ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_push_content(mock_pool):
    pool, conn = mock_pool
    mock_db = AsyncMock()

    with patch.object(server, "_get_user_id", return_value="user-1"), \
         patch.object(server, "_get_db", return_value=mock_db), \
         patch("chat_recall_prod.server.get_pool", return_value=pool), \
         patch("chat_recall_prod.server._push_content", new_callable=AsyncMock) as mock_push:
        mock_push.return_value = {
            "conversation_id": "push-123",
            "title": "Test",
            "tags": [],
        }

        result = await server.push_content.fn(content="Hello world")

    assert result["conversation_id"] == "push-123"
    conn.commit.assert_called_once()


# ── sync_now ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_now_no_data():
    with patch.object(server, "_get_user_id", return_value="user-1"):
        result = await server.sync_now.fn()

    assert result["status"] == "ready"


@pytest.mark.asyncio
async def test_sync_now_invalid_json():
    with patch.object(server, "_get_user_id", return_value="user-1"):
        result = await server.sync_now.fn(conversations_json="not json")

    assert "error" in result
    assert "Invalid JSON" in result["error"]


@pytest.mark.asyncio
async def test_sync_now_not_array():
    with patch.object(server, "_get_user_id", return_value="user-1"):
        result = await server.sync_now.fn(conversations_json='{"key": "value"}')

    assert "error" in result
    assert "JSON array" in result["error"]


@pytest.mark.asyncio
async def test_sync_now_imports_data(mock_pool):
    pool, conn = mock_pool
    mock_db = AsyncMock()

    with patch.object(server, "_get_user_id", return_value="user-1"), \
         patch.object(server, "_get_db", return_value=mock_db), \
         patch("chat_recall_prod.server.get_pool", return_value=pool), \
         patch("chat_recall_prod.importers.chatgpt.ChatGPTImporter") as MockImporter:
        importer_instance = MockImporter.return_value
        importer_instance.import_data = AsyncMock(return_value={
            "conversations_imported": 5,
            "messages_imported": 100,
        })

        data = json.dumps([{"id": "conv-1"}, {"id": "conv-2"}])
        result = await server.sync_now.fn(conversations_json=data)

    assert result["conversations_imported"] == 5
    conn.commit.assert_called_once()


# ── tag_conversation ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tag_conversation_not_found(mock_pool):
    pool, conn = mock_pool
    mock_cur = AsyncMock()
    mock_cur.fetchone = AsyncMock(return_value=None)
    conn.execute = AsyncMock(return_value=mock_cur)

    with patch.object(server, "_get_user_id", return_value="user-1"), \
         patch("chat_recall_prod.server.get_pool", return_value=pool):
        result = await server.tag_conversation.fn(
            conversation_id="missing", tags=["test"],
        )

    assert "error" in result


@pytest.mark.asyncio
async def test_tag_conversation_add_mode(mock_pool):
    pool, conn = mock_pool
    call_count = 0

    async def mock_execute(sql, params=None):
        nonlocal call_count
        call_count += 1
        m = AsyncMock()
        if call_count == 1:
            m.fetchone = AsyncMock(return_value={"tags": ["existing"]})
        return m

    conn.execute = mock_execute

    with patch.object(server, "_get_user_id", return_value="user-1"), \
         patch("chat_recall_prod.server.get_pool", return_value=pool):
        result = await server.tag_conversation.fn(
            conversation_id="conv-1", tags=["new-tag"],
        )

    assert "conv-1" == result["conversation_id"]
    assert "existing" in result["tags"]
    assert "new-tag" in result["tags"]


@pytest.mark.asyncio
async def test_tag_conversation_set_mode(mock_pool):
    pool, conn = mock_pool
    call_count = 0

    async def mock_execute(sql, params=None):
        nonlocal call_count
        call_count += 1
        m = AsyncMock()
        if call_count == 1:
            m.fetchone = AsyncMock(return_value={"tags": ["old"]})
        return m

    conn.execute = mock_execute

    with patch.object(server, "_get_user_id", return_value="user-1"), \
         patch("chat_recall_prod.server.get_pool", return_value=pool):
        result = await server.tag_conversation.fn(
            conversation_id="conv-1", tags=["replaced"], mode="set",
        )

    assert result["tags"] == ["replaced"]
    assert "old" not in result["tags"]


# ── search_by_tags ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_by_tags(mock_pool):
    pool, conn = mock_pool
    expected = ConversationListResult(
        conversations=[
            ConversationSummary(id="conv-1", tags=["arch"]),
        ],
        total=1, page=1, page_size=20,
    )

    with patch.object(server, "_get_user_id", return_value="user-1"), \
         patch("chat_recall_prod.server.get_pool", return_value=pool), \
         patch("chat_recall_prod.server.SearchEngine") as MockEngine:
        engine_instance = MockEngine.return_value
        engine_instance.search_by_tags = AsyncMock(return_value=expected)

        result = await server.search_by_tags.fn(tags=["arch"])

    assert result["total"] == 1


# ── create_thread ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_thread(mock_pool):
    pool, conn = mock_pool

    with patch.object(server, "_get_user_id", return_value="user-1"), \
         patch("chat_recall_prod.server.get_pool", return_value=pool), \
         patch("chat_recall_prod.server._create_thread", new_callable=AsyncMock) as mock_ct:
        mock_ct.return_value = {"id": "my-thread", "title": "My Thread"}

        result = await server.create_thread.fn(slug="my-thread", title="My Thread")

    assert result["id"] == "my-thread"
    conn.commit.assert_called_once()


@pytest.mark.asyncio
async def test_create_thread_invalid_slug(mock_pool):
    pool, conn = mock_pool

    with patch.object(server, "_get_user_id", return_value="user-1"), \
         patch("chat_recall_prod.server.get_pool", return_value=pool), \
         patch("chat_recall_prod.server._create_thread", new_callable=AsyncMock) as mock_ct:
        mock_ct.side_effect = ValueError("Invalid slug: 'Bad!'")

        result = await server.create_thread.fn(slug="Bad!", title="Test")

    assert "error" in result
    assert "Invalid slug" in result["error"]


# ── link_to_thread ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_link_to_thread(mock_pool):
    pool, conn = mock_pool

    with patch.object(server, "_get_user_id", return_value="user-1"), \
         patch("chat_recall_prod.server.get_pool", return_value=pool), \
         patch("chat_recall_prod.server._link_conversation", new_callable=AsyncMock) as mock_lc:
        mock_lc.return_value = {
            "thread_id": "my-thread",
            "conversation_id": "conv-1",
            "note": "Related",
        }

        result = await server.link_to_thread.fn(
            thread_slug="my-thread", conversation_id="conv-1", note="Related",
        )

    assert result["thread_id"] == "my-thread"
    conn.commit.assert_called_once()


# ── get_thread ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_thread_found(mock_pool):
    pool, conn = mock_pool

    with patch.object(server, "_get_user_id", return_value="user-1"), \
         patch("chat_recall_prod.server.get_pool", return_value=pool), \
         patch("chat_recall_prod.server._get_thread", new_callable=AsyncMock) as mock_gt:
        mock_gt.return_value = {"id": "arch", "title": "Architecture", "conversations": []}

        result = await server.get_thread.fn(slug="arch")

    assert result["id"] == "arch"


@pytest.mark.asyncio
async def test_get_thread_not_found(mock_pool):
    pool, conn = mock_pool

    with patch.object(server, "_get_user_id", return_value="user-1"), \
         patch("chat_recall_prod.server.get_pool", return_value=pool), \
         patch("chat_recall_prod.server._get_thread", new_callable=AsyncMock) as mock_gt:
        mock_gt.return_value = None

        result = await server.get_thread.fn(slug="nonexistent")

    assert "error" in result
    assert "not found" in result["error"]


# ── list_threads ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_threads(mock_pool):
    pool, conn = mock_pool

    with patch.object(server, "_get_user_id", return_value="user-1"), \
         patch("chat_recall_prod.server.get_pool", return_value=pool), \
         patch("chat_recall_prod.server._list_threads", new_callable=AsyncMock) as mock_lt:
        mock_lt.return_value = {"threads": [], "total": 0}

        result = await server.list_threads.fn()

    assert result["total"] == 0


@pytest.mark.asyncio
async def test_list_threads_with_filters(mock_pool):
    pool, conn = mock_pool

    with patch.object(server, "_get_user_id", return_value="user-1"), \
         patch("chat_recall_prod.server.get_pool", return_value=pool), \
         patch("chat_recall_prod.server._list_threads", new_callable=AsyncMock) as mock_lt:
        mock_lt.return_value = {"threads": [], "total": 0}

        result = await server.list_threads.fn(status="archived", tags=["old"])

    mock_lt.assert_called_once()
    call_kwargs = mock_lt.call_args
    assert call_kwargs[1]["status"] == "archived"
    assert call_kwargs[1]["tags"] == ["old"]
