"""Tests for multi-user data isolation (CR-39).

Core requirement: User A must NEVER see, modify, or delete User B's data.
Each test verifies that the user_id passed to the database layer matches
the authenticated user, and that different users get different results.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from chat_recall_prod import server
from chat_recall_prod.response_models import (
    ConversationDetail,
    ConversationListResult,
    ConversationSummary,
    MessageResult,
    SearchResult,
)


# ── Constants ────────────────────────────────────────────────────────────

USER_A = "user-aaa-1111"
USER_B = "user-bbb-2222"


# ── Fixtures ─────────────────────────────────────────────────────────────


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


# ── list_conversations — isolation ───────────────────────────────────────


@pytest.mark.asyncio
async def test_list_conversations_user_a_only_sees_own(mock_pool):
    """User A's list_conversations passes User A's ID to the search engine."""
    pool, conn = mock_pool

    user_a_convos = ConversationListResult(
        conversations=[
            ConversationSummary(id="conv-a1", title="Alice's Chat"),
        ],
        total=1, page=1, page_size=20,
    )

    with patch.object(server, "_get_user_id", return_value=USER_A), \
         patch("chat_recall_prod.server.get_pool", return_value=pool), \
         patch("chat_recall_prod.server.SearchEngine") as MockEngine:
        engine = MockEngine.return_value
        engine.list_conversations = AsyncMock(return_value=user_a_convos)

        result = await server.list_conversations.fn()

    assert result["total"] == 1
    assert result["conversations"][0]["id"] == "conv-a1"
    # Verify user_id was passed correctly
    engine.list_conversations.assert_called_once()
    call_args = engine.list_conversations.call_args
    assert call_args[0][1] == USER_A  # second positional arg is user_id


@pytest.mark.asyncio
async def test_list_conversations_user_b_only_sees_own(mock_pool):
    """User B's list_conversations passes User B's ID to the search engine."""
    pool, conn = mock_pool

    user_b_convos = ConversationListResult(
        conversations=[
            ConversationSummary(id="conv-b1", title="Bob's Chat"),
            ConversationSummary(id="conv-b2", title="Bob's Other Chat"),
        ],
        total=2, page=1, page_size=20,
    )

    with patch.object(server, "_get_user_id", return_value=USER_B), \
         patch("chat_recall_prod.server.get_pool", return_value=pool), \
         patch("chat_recall_prod.server.SearchEngine") as MockEngine:
        engine = MockEngine.return_value
        engine.list_conversations = AsyncMock(return_value=user_b_convos)

        result = await server.list_conversations.fn()

    assert result["total"] == 2
    assert result["conversations"][0]["id"] == "conv-b1"
    call_args = engine.list_conversations.call_args
    assert call_args[0][1] == USER_B


@pytest.mark.asyncio
async def test_list_conversations_different_users_different_results(mock_pool):
    """Two calls with different user_ids pass different user_ids to the engine."""
    pool, conn = mock_pool

    captured_user_ids = []

    async def mock_list(conn, user_id, **kwargs):
        captured_user_ids.append(user_id)
        return ConversationListResult(conversations=[], total=0, page=1, page_size=20)

    with patch("chat_recall_prod.server.get_pool", return_value=pool), \
         patch("chat_recall_prod.server.SearchEngine") as MockEngine:
        engine = MockEngine.return_value
        engine.list_conversations = mock_list

        with patch.object(server, "_get_user_id", return_value=USER_A):
            await server.list_conversations.fn()

        with patch.object(server, "_get_user_id", return_value=USER_B):
            await server.list_conversations.fn()

    assert captured_user_ids == [USER_A, USER_B]


# ── get_conversation — isolation ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_conversation_user_a_can_access_own(mock_pool):
    """User A can access their own conversation."""
    pool, conn = mock_pool

    conv_a = ConversationDetail(
        id="conv-a1", title="Alice's Chat",
        messages=[MessageResult(role="user", content="Hello from Alice")],
    )

    with patch.object(server, "_get_user_id", return_value=USER_A), \
         patch("chat_recall_prod.server.get_pool", return_value=pool), \
         patch("chat_recall_prod.server.SearchEngine") as MockEngine:
        engine = MockEngine.return_value
        engine.get_conversation = AsyncMock(return_value=conv_a)

        result = await server.get_conversation.fn(conversation_id="conv-a1")

    assert result["id"] == "conv-a1"
    call_args = engine.get_conversation.call_args
    assert call_args[0][1] == USER_A  # user_id


@pytest.mark.asyncio
async def test_get_conversation_user_b_cannot_access_user_a(mock_pool):
    """User B cannot access User A's conversation (engine returns None for wrong user)."""
    pool, conn = mock_pool

    with patch.object(server, "_get_user_id", return_value=USER_B), \
         patch("chat_recall_prod.server.get_pool", return_value=pool), \
         patch("chat_recall_prod.server.SearchEngine") as MockEngine:
        engine = MockEngine.return_value
        # The engine returns None because conv-a1 doesn't belong to USER_B
        engine.get_conversation = AsyncMock(return_value=None)

        result = await server.get_conversation.fn(conversation_id="conv-a1")

    assert "error" in result
    assert "not found" in result["error"]
    # Verify the engine was queried with USER_B's ID (not USER_A)
    call_args = engine.get_conversation.call_args
    assert call_args[0][1] == USER_B


@pytest.mark.asyncio
async def test_get_conversation_passes_correct_user_id(mock_pool):
    """get_conversation always passes the authenticated user's ID to the engine."""
    pool, conn = mock_pool
    captured_user_ids = []

    async def mock_get(conn, user_id, conv_id, **kwargs):
        captured_user_ids.append(user_id)
        return None

    with patch("chat_recall_prod.server.get_pool", return_value=pool), \
         patch("chat_recall_prod.server.SearchEngine") as MockEngine:
        engine = MockEngine.return_value
        engine.get_conversation = mock_get

        with patch.object(server, "_get_user_id", return_value=USER_A):
            await server.get_conversation.fn(conversation_id="conv-1")

        with patch.object(server, "_get_user_id", return_value=USER_B):
            await server.get_conversation.fn(conversation_id="conv-1")

    assert captured_user_ids == [USER_A, USER_B]


# ── search_conversations — isolation ─────────────────────────────────────


@pytest.mark.asyncio
async def test_search_conversations_user_a_scoped(mock_pool):
    """Search results are scoped to User A when User A is authenticated."""
    pool, conn = mock_pool

    user_a_results = SearchResult(
        query="project", hits=[], total=3, page=1, page_size=20,
    )

    with patch.object(server, "_get_user_id", return_value=USER_A), \
         patch("chat_recall_prod.server.get_pool", return_value=pool), \
         patch("chat_recall_prod.server.SearchEngine") as MockEngine:
        engine = MockEngine.return_value
        engine.search = AsyncMock(return_value=user_a_results)

        result = await server.search_conversations.fn(query="project")

    assert result["total"] == 3
    call_args = engine.search.call_args
    assert call_args[0][1] == USER_A  # user_id is second positional arg


@pytest.mark.asyncio
async def test_search_conversations_user_b_scoped(mock_pool):
    """Search results are scoped to User B when User B is authenticated."""
    pool, conn = mock_pool

    user_b_results = SearchResult(
        query="project", hits=[], total=7, page=1, page_size=20,
    )

    with patch.object(server, "_get_user_id", return_value=USER_B), \
         patch("chat_recall_prod.server.get_pool", return_value=pool), \
         patch("chat_recall_prod.server.SearchEngine") as MockEngine:
        engine = MockEngine.return_value
        engine.search = AsyncMock(return_value=user_b_results)

        result = await server.search_conversations.fn(query="project")

    assert result["total"] == 7
    call_args = engine.search.call_args
    assert call_args[0][1] == USER_B


@pytest.mark.asyncio
async def test_search_conversations_different_users_different_scopes(mock_pool):
    """Same query with different users passes different user_ids to engine."""
    pool, conn = mock_pool
    captured_user_ids = []

    async def mock_search(conn, user_id, query, **kwargs):
        captured_user_ids.append(user_id)
        return SearchResult(query=query, hits=[], total=0, page=1, page_size=20)

    with patch("chat_recall_prod.server.get_pool", return_value=pool), \
         patch("chat_recall_prod.server.SearchEngine") as MockEngine:
        engine = MockEngine.return_value
        engine.search = mock_search

        with patch.object(server, "_get_user_id", return_value=USER_A):
            await server.search_conversations.fn(query="test")

        with patch.object(server, "_get_user_id", return_value=USER_B):
            await server.search_conversations.fn(query="test")

    assert captured_user_ids == [USER_A, USER_B]


# ── list_threads — isolation ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_threads_user_a_only_sees_own(mock_pool):
    """User A's list_threads passes User A's ID."""
    pool, conn = mock_pool

    with patch.object(server, "_get_user_id", return_value=USER_A), \
         patch("chat_recall_prod.server.get_pool", return_value=pool), \
         patch("chat_recall_prod.server._list_threads", new_callable=AsyncMock) as mock_lt:
        mock_lt.return_value = {
            "threads": [{"id": "thread-a1", "title": "Alice's Thread"}],
            "total": 1,
        }

        result = await server.list_threads.fn()

    assert result["total"] == 1
    assert result["threads"][0]["id"] == "thread-a1"
    mock_lt.assert_called_once()
    call_args = mock_lt.call_args
    assert call_args[0][1] == USER_A  # user_id is second positional arg


@pytest.mark.asyncio
async def test_list_threads_user_b_only_sees_own(mock_pool):
    """User B's list_threads passes User B's ID."""
    pool, conn = mock_pool

    with patch.object(server, "_get_user_id", return_value=USER_B), \
         patch("chat_recall_prod.server.get_pool", return_value=pool), \
         patch("chat_recall_prod.server._list_threads", new_callable=AsyncMock) as mock_lt:
        mock_lt.return_value = {
            "threads": [
                {"id": "thread-b1", "title": "Bob Thread 1"},
                {"id": "thread-b2", "title": "Bob Thread 2"},
            ],
            "total": 2,
        }

        result = await server.list_threads.fn()

    assert result["total"] == 2
    call_args = mock_lt.call_args
    assert call_args[0][1] == USER_B


@pytest.mark.asyncio
async def test_list_threads_different_users_isolated(mock_pool):
    """Sequential list_threads calls pass different user_ids."""
    pool, conn = mock_pool
    captured_user_ids = []

    async def mock_list(conn, user_id, **kwargs):
        captured_user_ids.append(user_id)
        return {"threads": [], "total": 0}

    with patch("chat_recall_prod.server.get_pool", return_value=pool), \
         patch("chat_recall_prod.server._list_threads", side_effect=mock_list):

        with patch.object(server, "_get_user_id", return_value=USER_A):
            await server.list_threads.fn()

        with patch.object(server, "_get_user_id", return_value=USER_B):
            await server.list_threads.fn()

    assert captured_user_ids == [USER_A, USER_B]


# ── get_thread — isolation ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_thread_user_a_can_access_own(mock_pool):
    """User A can access their own thread."""
    pool, conn = mock_pool

    with patch.object(server, "_get_user_id", return_value=USER_A), \
         patch("chat_recall_prod.server.get_pool", return_value=pool), \
         patch("chat_recall_prod.server._get_thread", new_callable=AsyncMock) as mock_gt:
        mock_gt.return_value = {
            "id": "alice-thread", "title": "Alice's Thread", "conversations": [],
        }

        result = await server.get_thread.fn(slug="alice-thread")

    assert result["id"] == "alice-thread"
    call_args = mock_gt.call_args
    assert call_args[0][1] == USER_A


@pytest.mark.asyncio
async def test_get_thread_user_b_cannot_access_user_a_thread(mock_pool):
    """User B cannot access User A's thread (returns not found)."""
    pool, conn = mock_pool

    with patch.object(server, "_get_user_id", return_value=USER_B), \
         patch("chat_recall_prod.server.get_pool", return_value=pool), \
         patch("chat_recall_prod.server._get_thread", new_callable=AsyncMock) as mock_gt:
        # Thread doesn't exist for USER_B
        mock_gt.return_value = None

        result = await server.get_thread.fn(slug="alice-thread")

    assert "error" in result
    assert "not found" in result["error"]
    # Verify the query used USER_B's ID
    call_args = mock_gt.call_args
    assert call_args[0][1] == USER_B


@pytest.mark.asyncio
async def test_get_thread_passes_correct_user_id(mock_pool):
    """get_thread always passes the authenticated user's ID."""
    pool, conn = mock_pool
    captured_user_ids = []

    async def mock_get(conn, user_id, slug):
        captured_user_ids.append(user_id)
        return None

    with patch("chat_recall_prod.server.get_pool", return_value=pool), \
         patch("chat_recall_prod.server._get_thread", side_effect=mock_get):

        with patch.object(server, "_get_user_id", return_value=USER_A):
            await server.get_thread.fn(slug="some-thread")

        with patch.object(server, "_get_user_id", return_value=USER_B):
            await server.get_thread.fn(slug="some-thread")

    assert captured_user_ids == [USER_A, USER_B]
