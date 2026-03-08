"""Async database queries for Chat Recall production.

All queries accept user_id for multi-tenant isolation.
Uses psycopg async connections from the pool.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)


class Database:
    """Async Postgres database access layer with multi-tenant isolation."""

    def __init__(self, pool: AsyncConnectionPool):
        self.pool = pool

    # ── Source operations ──────────────────────────────────────────────

    async def insert_source(
        self,
        conn: AsyncConnection,
        source_type: str,
        file_path: str,
        record_count: int = 0,
        metadata: dict | None = None,
    ) -> int:
        cur = await conn.execute(
            "INSERT INTO sources (source_type, file_path, record_count, metadata) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (source_type, file_path, record_count, json.dumps(metadata) if metadata else None),
        )
        row = await cur.fetchone()
        return row[0]

    # ── Conversation operations ────────────────────────────────────────

    async def insert_conversation(
        self,
        conn: AsyncConnection,
        user_id: str,
        *,
        id: str,
        source_id: int,
        title: str | None = None,
        create_time: float | None = None,
        update_time: float | None = None,
        model: str | None = None,
        gizmo_id: str | None = None,
        message_count: int = 0,
        has_branches: bool = False,
        metadata: dict | None = None,
        source_type: str | None = None,
        project: str | None = None,
        tags: list[str] | None = None,
    ) -> None:
        await conn.execute(
            "INSERT INTO conversations "
            "(id, user_id, source_id, title, create_time, update_time, model, gizmo_id, "
            "message_count, has_branches, metadata, source_type, project, tags) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (id) DO NOTHING",
            (
                id, user_id, source_id, title, create_time, update_time, model,
                gizmo_id, message_count, has_branches,
                json.dumps(metadata) if metadata else None,
                source_type, project,
                json.dumps(tags) if tags else None,
            ),
        )

    async def update_conversation(
        self,
        conn: AsyncConnection,
        user_id: str,
        conv_id: str,
        **kwargs: Any,
    ) -> None:
        if not kwargs:
            return
        # Build SET clause with positional params
        set_parts = []
        values = []
        for i, (k, v) in enumerate(kwargs.items(), start=1):
            if k in ("metadata", "tags") and isinstance(v, (dict, list)):
                v = json.dumps(v)
            set_parts.append(f"{k} = %s")
            values.append(v)
        values.extend([conv_id, user_id])
        set_clause = ", ".join(set_parts)
        await conn.execute(
            f"UPDATE conversations SET {set_clause} WHERE id = %s AND user_id = %s",
            values,
        )

    async def get_conversation(
        self,
        conn: AsyncConnection,
        user_id: str,
        conv_id: str,
    ) -> dict[str, Any] | None:
        conn.row_factory = dict_row
        cur = await conn.execute(
            "SELECT * FROM conversations WHERE id = %s AND user_id = %s",
            (conv_id, user_id),
        )
        return await cur.fetchone()

    async def list_conversations(
        self,
        conn: AsyncConnection,
        user_id: str,
        *,
        page: int = 1,
        page_size: int = 20,
        source_type: str | None = None,
        project: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        conn.row_factory = dict_row

        where = ["user_id = %s"]
        params: list[Any] = [user_id]
        if source_type:
            where.append("source_type = %s")
            params.append(source_type)
        if project:
            where.append("project = %s")
            params.append(project)

        where_clause = " AND ".join(where)

        # Count
        cur = await conn.execute(f"SELECT COUNT(*) FROM conversations WHERE {where_clause}", params)
        total = (await cur.fetchone())[0]

        # Fetch page
        offset = (page - 1) * page_size
        params_page = params + [page_size, offset]
        cur = await conn.execute(
            f"SELECT * FROM conversations WHERE {where_clause} "
            f"ORDER BY create_time DESC LIMIT %s OFFSET %s",
            params_page,
        )
        rows = await cur.fetchall()
        return rows, total

    # ── Message operations ─────────────────────────────────────────────

    async def insert_messages_batch(
        self,
        conn: AsyncConnection,
        messages: list[dict[str, Any]],
    ) -> int:
        if not messages:
            return 0
        for msg in messages:
            await conn.execute(
                "INSERT INTO messages "
                "(id, conversation_id, parent_id, role, content_type, content_text, "
                "raw_content, is_canonical, create_time, attachments, metadata) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (id, conversation_id) DO NOTHING",
                (
                    msg["id"], msg["conversation_id"], msg.get("parent_id"),
                    msg.get("role"), msg.get("content_type"), msg.get("content_text"),
                    msg.get("raw_content"), msg.get("is_canonical", True),
                    msg.get("create_time"),
                    json.dumps(msg["attachments"]) if msg.get("attachments") else None,
                    json.dumps(msg["metadata"]) if msg.get("metadata") else None,
                ),
            )
        return len(messages)

    async def delete_messages(
        self,
        conn: AsyncConnection,
        user_id: str,
        conversation_id: str,
    ) -> int:
        cur = await conn.execute(
            "DELETE FROM messages WHERE conversation_id = %s "
            "AND conversation_id IN (SELECT id FROM conversations WHERE user_id = %s)",
            (conversation_id, user_id),
        )
        return cur.rowcount

    async def get_messages(
        self,
        conn: AsyncConnection,
        user_id: str,
        conversation_id: str,
    ) -> list[dict[str, Any]]:
        conn.row_factory = dict_row
        cur = await conn.execute(
            "SELECT m.* FROM messages m "
            "JOIN conversations c ON m.conversation_id = c.id "
            "WHERE m.conversation_id = %s AND c.user_id = %s "
            "ORDER BY m.create_time ASC NULLS FIRST",
            (conversation_id, user_id),
        )
        return await cur.fetchall()

    # ── Stats ──────────────────────────────────────────────────────────

    async def get_stats(
        self,
        conn: AsyncConnection,
        user_id: str,
    ) -> dict[str, Any]:
        conn.row_factory = dict_row

        cur = await conn.execute(
            "SELECT COUNT(*) as count, MIN(create_time) as earliest, MAX(create_time) as latest "
            "FROM conversations WHERE user_id = %s",
            (user_id,),
        )
        row = await cur.fetchone()

        cur = await conn.execute(
            "SELECT COUNT(*) FROM messages m "
            "JOIN conversations c ON m.conversation_id = c.id "
            "WHERE c.user_id = %s",
            (user_id,),
        )
        msg_count = (await cur.fetchone())[0]

        roles: dict[str, int] = {}
        cur = await conn.execute(
            "SELECT m.role, COUNT(*) as cnt FROM messages m "
            "JOIN conversations c ON m.conversation_id = c.id "
            "WHERE c.user_id = %s GROUP BY m.role ORDER BY cnt DESC",
            (user_id,),
        )
        for r in await cur.fetchall():
            roles[r["role"]] = r["cnt"]

        models: dict[str, int] = {}
        cur = await conn.execute(
            "SELECT model, COUNT(*) as cnt FROM conversations "
            "WHERE user_id = %s AND model IS NOT NULL GROUP BY model ORDER BY cnt DESC",
            (user_id,),
        )
        for r in await cur.fetchall():
            models[r["model"]] = r["cnt"]

        return {
            "conversations": row["count"],
            "messages": msg_count,
            "earliest_timestamp": row["earliest"],
            "latest_timestamp": row["latest"],
            "roles": roles,
            "models": models,
        }

    # ── User operations ────────────────────────────────────────────────

    async def create_user(
        self,
        conn: AsyncConnection,
        *,
        email: str,
        name: str | None = None,
        github_id: str | None = None,
        google_id: str | None = None,
        avatar_url: str | None = None,
        password_hash: str | None = None,
    ) -> dict[str, Any]:
        conn.row_factory = dict_row
        user_id = str(uuid.uuid4())
        cur = await conn.execute(
            "INSERT INTO users (id, email, name, github_id, google_id, avatar_url, password_hash) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *",
            (user_id, email, name, github_id, google_id, avatar_url, password_hash),
        )
        return await cur.fetchone()

    async def get_user_by_email(
        self, conn: AsyncConnection, email: str
    ) -> dict[str, Any] | None:
        conn.row_factory = dict_row
        cur = await conn.execute("SELECT * FROM users WHERE email = %s", (email,))
        return await cur.fetchone()

    async def get_user_by_github_id(
        self, conn: AsyncConnection, github_id: str
    ) -> dict[str, Any] | None:
        conn.row_factory = dict_row
        cur = await conn.execute("SELECT * FROM users WHERE github_id = %s", (github_id,))
        return await cur.fetchone()

    async def get_user_by_google_id(
        self, conn: AsyncConnection, google_id: str
    ) -> dict[str, Any] | None:
        conn.row_factory = dict_row
        cur = await conn.execute("SELECT * FROM users WHERE google_id = %s", (google_id,))
        return await cur.fetchone()

    async def get_user_by_id(
        self, conn: AsyncConnection, user_id: str
    ) -> dict[str, Any] | None:
        conn.row_factory = dict_row
        cur = await conn.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        return await cur.fetchone()

    async def update_user(
        self, conn: AsyncConnection, user_id: str, **kwargs: Any
    ) -> None:
        if not kwargs:
            return
        set_parts = []
        values = []
        for k, v in kwargs.items():
            set_parts.append(f"{k} = %s")
            values.append(v)
        values.append(user_id)
        await conn.execute(
            f"UPDATE users SET {', '.join(set_parts)}, updated_at = NOW() WHERE id = %s",
            values,
        )

    async def increment_user_analytics(
        self,
        conn: AsyncConnection,
        user_id: str,
        *,
        conversations: int = 0,
        messages: int = 0,
        uploads: int = 0,
    ) -> None:
        """Atomically increment analytics counters on the users table.

        Args:
            conn: Async Postgres connection.
            user_id: User whose counters to update.
            conversations: Number of new conversations to add.
            messages: Number of new messages to add.
            uploads: Number of new uploads to add (typically 1).
        """
        await conn.execute(
            "UPDATE users SET "
            "total_conversations = total_conversations + %s, "
            "total_messages = total_messages + %s, "
            "total_uploads = total_uploads + %s, "
            "last_upload_at = NOW(), "
            "updated_at = NOW() "
            "WHERE id = %s",
            (conversations, messages, uploads, user_id),
        )

    async def delete_user_data(
        self, conn: AsyncConnection, user_id: str
    ) -> dict[str, int]:
        """Cascade-delete all user data. Returns counts of deleted rows."""
        counts: dict[str, int] = {}

        # Delete messages for user's conversations
        cur = await conn.execute(
            "DELETE FROM messages WHERE conversation_id IN "
            "(SELECT id FROM conversations WHERE user_id = %s)",
            (user_id,),
        )
        counts["messages"] = cur.rowcount

        # Delete thread_conversations for user's threads
        cur = await conn.execute(
            "DELETE FROM thread_conversations WHERE thread_id IN "
            "(SELECT id FROM threads WHERE user_id = %s)",
            (user_id,),
        )
        counts["thread_conversations"] = cur.rowcount

        # Delete threads
        cur = await conn.execute("DELETE FROM threads WHERE user_id = %s", (user_id,))
        counts["threads"] = cur.rowcount

        # Delete conversations
        cur = await conn.execute("DELETE FROM conversations WHERE user_id = %s", (user_id,))
        counts["conversations"] = cur.rowcount

        # Delete uploads
        cur = await conn.execute("DELETE FROM uploads WHERE user_id = %s", (user_id,))
        counts["uploads"] = cur.rowcount

        # Delete subscription
        cur = await conn.execute("DELETE FROM subscriptions WHERE user_id = %s", (user_id,))
        counts["subscriptions"] = cur.rowcount

        # Delete user
        cur = await conn.execute("DELETE FROM users WHERE id = %s", (user_id,))
        counts["users"] = cur.rowcount

        return counts
