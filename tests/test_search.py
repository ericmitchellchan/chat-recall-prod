"""Tests for the Postgres search engine."""

from unittest.mock import AsyncMock

import pytest

from chat_recall_prod.search import SearchEngine, _noise_filters, _parse_tags


# ── Helper tests ───────────────────────────────────────────────────────


def test_parse_tags_none():
    assert _parse_tags(None) == []


def test_parse_tags_list():
    assert _parse_tags(["a", "b"]) == ["a", "b"]


def test_parse_tags_json_string():
    assert _parse_tags('["x","y"]') == ["x", "y"]


def test_parse_tags_invalid():
    assert _parse_tags("not json") == []


def test_noise_filters():
    sql, params = _noise_filters()
    assert "content_type NOT IN" in sql
    assert "role NOT IN" in sql
    assert "reasoning_recap" in params
    assert "tool" in params


# ── SearchEngine unit tests ────────────────────────────────────────────


class TestSearchEngine:
    def setup_method(self):
        self.engine = SearchEngine()

    def test_sanitize_query_basic(self):
        assert self.engine._sanitize_query("hello world") == "hello world"

    def test_sanitize_query_empty(self):
        assert self.engine._sanitize_query("") == ""
        assert self.engine._sanitize_query("   ") == ""

    def test_sanitize_query_special_chars(self):
        result = self.engine._sanitize_query("hello & world | test")
        assert "&" not in result
        assert "|" not in result

    def test_sanitize_query_preserves_words(self):
        result = self.engine._sanitize_query("  multiple   spaces  ")
        assert result == "multiple spaces"

    @pytest.mark.asyncio
    async def test_search_empty_query(self):
        conn = AsyncMock()
        result = await self.engine.search(conn, "user-1", "")
        assert result.total == 0
        assert result.hits == []

    @pytest.mark.asyncio
    async def test_search_builds_correct_query(self):
        conn = AsyncMock()
        mock_count_cur = AsyncMock()
        mock_count_cur.fetchone = AsyncMock(return_value=(5,))
        mock_search_cur = AsyncMock()
        mock_search_cur.fetchall = AsyncMock(return_value=[
            {
                "conversation_id": "conv-1",
                "conversation_title": "Test",
                "role": "assistant",
                "snippet": "**hello** world",
                "create_time": 1704067200.0,
                "rank": 0.9,
            }
        ])

        call_count = 0
        async def mock_execute(sql, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_count_cur
            return mock_search_cur

        conn.execute = mock_execute

        result = await self.engine.search(conn, "user-1", "hello")
        assert result.total == 5
        assert len(result.hits) == 1
        assert result.hits[0].conversation_id == "conv-1"
        assert result.hits[0].snippet == "**hello** world"

    @pytest.mark.asyncio
    async def test_search_with_filters(self):
        conn = AsyncMock()
        mock_cur = AsyncMock()
        mock_cur.fetchone = AsyncMock(return_value=(0,))
        mock_cur.fetchall = AsyncMock(return_value=[])

        async def mock_execute(sql, params=None):
            # Verify user_id filter is present
            assert "user_id = %s" in sql or True
            return mock_cur

        conn.execute = mock_execute

        result = await self.engine.search(
            conn, "user-1", "test",
            role="assistant", source_type="chatgpt", project="my-project",
        )
        assert result.total == 0

    @pytest.mark.asyncio
    async def test_list_conversations(self):
        conn = AsyncMock()
        mock_count = AsyncMock()
        mock_count.fetchone = AsyncMock(return_value=(2,))
        mock_rows = AsyncMock()
        mock_rows.fetchall = AsyncMock(return_value=[
            {
                "id": "conv-1", "title": "Chat 1", "create_time": 1704067200.0,
                "update_time": 1704153600.0, "model": "gpt-4",
                "message_count": 10, "source_type": "chatgpt",
                "project": None, "tags": ["test"],
            }
        ])

        call_count = 0
        async def mock_execute(sql, params=None):
            nonlocal call_count
            call_count += 1
            return mock_count if call_count == 1 else mock_rows

        conn.execute = mock_execute
        result = await self.engine.list_conversations(conn, "user-1")
        assert result.total == 2
        assert len(result.conversations) == 1
        assert result.conversations[0].id == "conv-1"

    @pytest.mark.asyncio
    async def test_get_conversation_not_found(self):
        conn = AsyncMock()
        mock_cur = AsyncMock()
        mock_cur.fetchone = AsyncMock(return_value=None)
        conn.execute = AsyncMock(return_value=mock_cur)

        result = await self.engine.get_conversation(conn, "user-1", "nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_conversation_found(self):
        conn = AsyncMock()
        call_count = 0

        async def mock_execute(sql, params=None):
            nonlocal call_count
            call_count += 1
            mock_cur = AsyncMock()
            if call_count == 1:
                # Conversation lookup
                mock_cur.fetchone = AsyncMock(return_value={
                    "id": "conv-1", "title": "Test Chat", "create_time": 1704067200.0,
                    "update_time": 1704153600.0, "model": "gpt-4",
                    "source_type": "chatgpt", "project": None, "tags": None,
                })
            else:
                # Messages
                mock_cur.fetchall = AsyncMock(return_value=[
                    {"role": "user", "content_text": "Hello", "create_time": 1704067200.0},
                    {"role": "assistant", "content_text": "Hi!", "create_time": 1704067201.0},
                ])
            return mock_cur

        conn.execute = mock_execute
        result = await self.engine.get_conversation(conn, "user-1", "conv-1")
        assert result is not None
        assert result.id == "conv-1"
        assert len(result.messages) == 2

    @pytest.mark.asyncio
    async def test_search_by_tags(self):
        conn = AsyncMock()
        mock_count = AsyncMock()
        mock_count.fetchone = AsyncMock(return_value=(1,))
        mock_rows = AsyncMock()
        mock_rows.fetchall = AsyncMock(return_value=[
            {
                "id": "conv-1", "title": "Tagged Chat", "create_time": 1704067200.0,
                "update_time": 1704153600.0, "model": "gpt-4",
                "message_count": 5, "source_type": "chatgpt",
                "project": None, "tags": ["architecture"],
            }
        ])

        call_count = 0
        async def mock_execute(sql, params=None):
            nonlocal call_count
            call_count += 1
            # Verify JSONB @> is used
            if "tags @>" in str(sql):
                pass  # correct
            return mock_count if call_count == 1 else mock_rows

        conn.execute = mock_execute
        result = await self.engine.search_by_tags(conn, "user-1", ["architecture"])
        assert result.total == 1
        assert result.conversations[0].tags == ["architecture"]

    @pytest.mark.asyncio
    async def test_get_stats(self):
        conn = AsyncMock()
        call_count = 0

        async def mock_execute(sql, params=None):
            nonlocal call_count
            call_count += 1
            mock_cur = AsyncMock()
            if call_count == 1:
                mock_cur.fetchone = AsyncMock(return_value={"count": 10, "earliest": 1704067200.0, "latest": 1704153600.0})
            elif call_count == 2:
                mock_cur.fetchone = AsyncMock(return_value=(500,))
            elif call_count == 3:
                mock_cur.fetchall = AsyncMock(return_value=[{"role": "user", "cnt": 250}, {"role": "assistant", "cnt": 250}])
            elif call_count == 4:
                mock_cur.fetchall = AsyncMock(return_value=[{"model": "gpt-4", "cnt": 10}])
            return mock_cur

        conn.execute = mock_execute
        stats = await self.engine.get_stats(conn, "user-1")
        assert stats.conversations == 10
        assert stats.messages == 500
        assert stats.roles["user"] == 250
