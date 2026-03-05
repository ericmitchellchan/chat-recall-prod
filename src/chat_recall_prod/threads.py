"""Async thread operations for Postgres — group related conversations.

All operations enforce user_id isolation.
"""

import json
import logging
import re
import time
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")


def _validate_slug(slug: str) -> None:
    """Validate a thread slug."""
    if len(slug) < 2:
        raise ValueError(f"Slug too short (min 2 chars): {slug!r}")
    if not SLUG_PATTERN.match(slug):
        raise ValueError(
            f"Invalid slug: {slug!r}. Must be lowercase alphanumeric with hyphens, "
            "e.g. 'project-alpha'."
        )


def _parse_tags(tags_val: Any) -> list[str]:
    """Parse tags from JSONB value."""
    if tags_val is None:
        return []
    if isinstance(tags_val, list):
        return tags_val
    if isinstance(tags_val, str):
        try:
            tags = json.loads(tags_val)
            return tags if isinstance(tags, list) else []
        except (json.JSONDecodeError, TypeError):
            return []
    return []


async def create_thread(
    conn: AsyncConnection,
    user_id: str,
    slug: str,
    title: str,
    description: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Create a new thread for a user."""
    _validate_slug(slug)
    now = time.time()
    tags_json = json.dumps(tags) if tags else None

    await conn.execute(
        "INSERT INTO threads (id, user_id, title, description, status, tags, create_time, update_time) "
        "VALUES (%s, %s, %s, %s, 'active', %s, %s, %s) "
        "ON CONFLICT (id) DO NOTHING",
        (slug, user_id, title, description, tags_json, now, now),
    )

    # Check if insert happened (thread may already exist)
    conn.row_factory = dict_row
    cur = await conn.execute("SELECT * FROM threads WHERE id = %s AND user_id = %s", (slug, user_id))
    thread = await cur.fetchone()
    if thread and thread["create_time"] == now:
        return {
            "id": slug,
            "title": title,
            "description": description,
            "status": "active",
            "tags": tags or [],
            "create_time": now,
            "update_time": now,
            "conversations": [],
        }
    return {"error": f"Thread already exists: {slug}"}


async def link_conversation(
    conn: AsyncConnection,
    user_id: str,
    thread_slug: str,
    conversation_id: str,
    note: str | None = None,
) -> dict[str, Any]:
    """Link a conversation to a thread. Both must belong to the same user."""
    now = time.time()
    conn.row_factory = dict_row

    # Verify thread belongs to user
    cur = await conn.execute(
        "SELECT 1 FROM threads WHERE id = %s AND user_id = %s", (thread_slug, user_id)
    )
    if await cur.fetchone() is None:
        return {"error": f"Thread not found: {thread_slug}"}

    # Verify conversation belongs to user
    cur = await conn.execute(
        "SELECT 1 FROM conversations WHERE id = %s AND user_id = %s", (conversation_id, user_id)
    )
    if await cur.fetchone() is None:
        return {"error": f"Conversation not found: {conversation_id}"}

    await conn.execute(
        "INSERT INTO thread_conversations (thread_id, conversation_id, note, added_time) "
        "VALUES (%s, %s, %s, %s) ON CONFLICT (thread_id, conversation_id) DO NOTHING",
        (thread_slug, conversation_id, note, now),
    )
    await conn.execute(
        "UPDATE threads SET update_time = %s WHERE id = %s", (now, thread_slug)
    )

    return {
        "thread_id": thread_slug,
        "conversation_id": conversation_id,
        "note": note,
    }


async def get_thread(
    conn: AsyncConnection,
    user_id: str,
    slug: str,
) -> dict[str, Any] | None:
    """Get a thread with its linked conversations. Returns None if wrong user."""
    conn.row_factory = dict_row
    cur = await conn.execute(
        "SELECT * FROM threads WHERE id = %s AND user_id = %s", (slug, user_id)
    )
    thread = await cur.fetchone()
    if thread is None:
        return None

    cur = await conn.execute(
        "SELECT tc.conversation_id, tc.note, tc.added_time, "
        "c.title AS conversation_title "
        "FROM thread_conversations tc "
        "JOIN conversations c ON tc.conversation_id = c.id "
        "WHERE tc.thread_id = %s "
        "ORDER BY tc.added_time ASC",
        (slug,),
    )
    rows = await cur.fetchall()

    conversations = [
        {
            "conversation_id": row["conversation_id"],
            "conversation_title": row["conversation_title"],
            "note": row["note"],
            "added_time": row["added_time"],
        }
        for row in rows
    ]

    return {
        "id": thread["id"],
        "title": thread["title"],
        "description": thread["description"],
        "status": thread["status"],
        "tags": _parse_tags(thread["tags"]),
        "create_time": thread["create_time"],
        "update_time": thread["update_time"],
        "conversations": conversations,
    }


async def list_threads(
    conn: AsyncConnection,
    user_id: str,
    status: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """List threads for a user with optional filtering."""
    conn.row_factory = dict_row
    conditions = ["t.user_id = %s"]
    params: list[Any] = [user_id]

    if status is not None:
        conditions.append("t.status = %s")
        params.append(status)
    if tags:
        conditions.append("t.tags @> %s::jsonb")
        params.append(json.dumps(tags))

    where = " AND ".join(conditions)

    cur = await conn.execute(
        f"SELECT t.*, COALESCE(tc.cnt, 0) AS conversation_count "
        f"FROM threads t "
        f"LEFT JOIN (SELECT thread_id, COUNT(*) AS cnt FROM thread_conversations GROUP BY thread_id) tc "
        f"ON t.id = tc.thread_id "
        f"WHERE {where} ORDER BY t.update_time DESC",
        params,
    )
    rows = await cur.fetchall()

    threads = []
    for row in rows:
        threads.append({
            "id": row["id"],
            "title": row["title"],
            "description": row["description"],
            "status": row["status"],
            "tags": _parse_tags(row["tags"]),
            "conversation_count": row["conversation_count"],
            "create_time": row["create_time"],
            "update_time": row["update_time"],
        })

    return {"threads": threads, "total": len(threads)}
