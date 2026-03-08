"""Tests for the database access layer.

Unit tests verify the Database class interface and pool management.
Integration tests (marked with pytest.mark.postgres) require a running Postgres.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from chat_recall_prod.db.pool import close_pool, get_pool, init_pool
from chat_recall_prod.db.queries import Database


# ── Pool tests ─────────────────────────────────────────────────────────


def test_get_pool_not_initialized():
    """get_pool raises RuntimeError before init_pool is called."""
    # Reset global state
    import chat_recall_prod.db.pool as pool_mod
    pool_mod._pool = None
    with pytest.raises(RuntimeError, match="not initialized"):
        get_pool()


@pytest.mark.asyncio
async def test_init_pool_no_url():
    """init_pool raises ValueError when no DATABASE_URL is provided."""
    import chat_recall_prod.db.pool as pool_mod
    pool_mod._pool = None
    with patch.dict(os.environ, {}, clear=True):
        # Remove DATABASE_URL from env if present
        os.environ.pop("DATABASE_URL", None)
        with pytest.raises(ValueError, match="DATABASE_URL is required"):
            await init_pool()


@pytest.mark.asyncio
async def test_close_pool_when_none():
    """close_pool is safe to call when pool is None."""
    import chat_recall_prod.db.pool as pool_mod
    pool_mod._pool = None
    await close_pool()  # Should not raise


# ── Database class unit tests ──────────────────────────────────────────


class TestDatabaseInterface:
    """Test that Database methods have the correct signatures and call patterns."""

    def setup_method(self):
        self.mock_pool = MagicMock()
        self.db = Database(self.mock_pool)

    @pytest.mark.asyncio
    async def test_insert_source(self):
        conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(42,))
        conn.execute = AsyncMock(return_value=mock_cursor)

        result = await self.db.insert_source(
            conn, source_type="chatgpt", file_path="/tmp/export.zip", record_count=100
        )
        assert result == 42
        conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_insert_conversation(self):
        conn = AsyncMock()
        conn.execute = AsyncMock()

        await self.db.insert_conversation(
            conn,
            user_id="user-123",
            id="conv-1",
            source_id=1,
            title="Test Chat",
            create_time=1704067200.0,
            message_count=5,
            source_type="chatgpt",
        )
        conn.execute.assert_called_once()
        call_args = conn.execute.call_args
        assert "INSERT INTO conversations" in call_args[0][0]
        assert "user-123" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_update_conversation(self):
        conn = AsyncMock()
        conn.execute = AsyncMock()

        await self.db.update_conversation(
            conn, user_id="user-123", conv_id="conv-1", title="Updated Title"
        )
        conn.execute.assert_called_once()
        call_args = conn.execute.call_args
        assert "UPDATE conversations" in call_args[0][0]
        assert "user_id = %s" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_update_conversation_noop(self):
        conn = AsyncMock()
        conn.execute = AsyncMock()

        await self.db.update_conversation(conn, user_id="user-123", conv_id="conv-1")
        conn.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_insert_messages_batch(self):
        conn = AsyncMock()
        conn.execute = AsyncMock()

        messages = [
            {"id": "msg-1", "conversation_id": "conv-1", "role": "user", "content_text": "Hi"},
            {"id": "msg-2", "conversation_id": "conv-1", "role": "assistant", "content_text": "Hello"},
        ]
        count = await self.db.insert_messages_batch(conn, messages)
        assert count == 2
        assert conn.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_insert_messages_batch_empty(self):
        conn = AsyncMock()
        count = await self.db.insert_messages_batch(conn, [])
        assert count == 0

    @pytest.mark.asyncio
    async def test_delete_messages(self):
        conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.rowcount = 5
        conn.execute = AsyncMock(return_value=mock_cursor)

        count = await self.db.delete_messages(conn, user_id="user-123", conversation_id="conv-1")
        assert count == 5

    @pytest.mark.asyncio
    async def test_create_user(self):
        conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value={
            "id": "uuid-1", "email": "test@example.com", "name": "Test"
        })
        conn.execute = AsyncMock(return_value=mock_cursor)

        user = await self.db.create_user(conn, email="test@example.com", name="Test")
        assert user["email"] == "test@example.com"

    @pytest.mark.asyncio
    async def test_get_user_by_email(self):
        conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value={"id": "uuid-1", "email": "test@example.com"})
        conn.execute = AsyncMock(return_value=mock_cursor)

        user = await self.db.get_user_by_email(conn, "test@example.com")
        assert user["email"] == "test@example.com"

    @pytest.mark.asyncio
    async def test_get_user_by_github_id(self):
        conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value={"github_id": "gh-123"})
        conn.execute = AsyncMock(return_value=mock_cursor)

        user = await self.db.get_user_by_github_id(conn, "gh-123")
        assert user["github_id"] == "gh-123"

    @pytest.mark.asyncio
    async def test_get_user_by_google_id(self):
        conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value={"google_id": "goog-456"})
        conn.execute = AsyncMock(return_value=mock_cursor)

        user = await self.db.get_user_by_google_id(conn, "goog-456")
        assert user["google_id"] == "goog-456"

    @pytest.mark.asyncio
    async def test_update_user(self):
        conn = AsyncMock()
        conn.execute = AsyncMock()

        await self.db.update_user(conn, user_id="uuid-1", name="New Name")
        conn.execute.assert_called_once()
        call_args = conn.execute.call_args
        assert "UPDATE users" in call_args[0][0]
        assert "updated_at = NOW()" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_update_user_noop(self):
        conn = AsyncMock()
        conn.execute = AsyncMock()

        await self.db.update_user(conn, user_id="uuid-1")
        conn.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_user_data(self):
        conn = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.rowcount = 1
        conn.execute = AsyncMock(return_value=mock_cursor)

        counts = await self.db.delete_user_data(conn, user_id="uuid-1")
        assert "messages" in counts
        assert "conversations" in counts
        assert "threads" in counts
        assert "uploads" in counts
        assert "subscriptions" in counts
        assert "users" in counts
        # 7 DELETE statements total
        assert conn.execute.call_count == 7

    @pytest.mark.asyncio
    async def test_increment_user_analytics(self):
        conn = AsyncMock()
        conn.execute = AsyncMock()

        await self.db.increment_user_analytics(
            conn, user_id="uuid-1",
            conversations=5, messages=100, uploads=1,
        )
        conn.execute.assert_called_once()
        call_args = conn.execute.call_args
        sql = call_args[0][0]
        params = call_args[0][1]
        assert "total_conversations = total_conversations + %s" in sql
        assert "total_messages = total_messages + %s" in sql
        assert "total_uploads = total_uploads + %s" in sql
        assert "last_upload_at = NOW()" in sql
        assert params == (5, 100, 1, "uuid-1")

    @pytest.mark.asyncio
    async def test_increment_user_analytics_defaults(self):
        conn = AsyncMock()
        conn.execute = AsyncMock()

        await self.db.increment_user_analytics(conn, user_id="uuid-1")
        call_args = conn.execute.call_args
        params = call_args[0][1]
        # Default increments are 0
        assert params == (0, 0, 0, "uuid-1")

    @pytest.mark.asyncio
    async def test_get_stats(self):
        conn = AsyncMock()
        call_count = 0

        async def mock_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            mock_cur = AsyncMock()
            if call_count == 1:
                # Conversations count
                mock_cur.fetchone = AsyncMock(return_value={"count": 10, "earliest": 1704067200.0, "latest": 1704153600.0})
            elif call_count == 2:
                # Message count
                mock_cur.fetchone = AsyncMock(return_value=(100,))
            elif call_count == 3:
                # Roles
                mock_cur.fetchall = AsyncMock(return_value=[{"role": "user", "cnt": 50}, {"role": "assistant", "cnt": 50}])
            elif call_count == 4:
                # Models
                mock_cur.fetchall = AsyncMock(return_value=[{"model": "gpt-4", "cnt": 10}])
            return mock_cur

        conn.execute = mock_execute

        stats = await self.db.get_stats(conn, user_id="user-123")
        assert stats["conversations"] == 10
        assert stats["messages"] == 100
        assert stats["roles"]["user"] == 50
        assert stats["models"]["gpt-4"] == 10
