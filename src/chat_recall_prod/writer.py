"""Async writer for pushing content into the Postgres recall database."""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from chat_recall_prod.db.queries import Database


async def _get_or_create_push_source(
    db: Database, conn: AsyncConnection, source_type: str
) -> int:
    """Reuse a single source record for push content instead of creating one per push."""
    conn.row_factory = dict_row
    cur = await conn.execute(
        "SELECT id FROM sources WHERE source_type = %s AND file_path = 'push'",
        (source_type,),
    )
    row = await cur.fetchone()
    if row:
        return row["id"]
    return await db.insert_source(conn, source_type, "push", metadata={"push": True})


async def push_content(
    db: Database,
    conn: AsyncConnection,
    user_id: str | None,
    content: str,
    title: str | None = None,
    source_type: str = "push",
    tags: list[str] | None = None,
    project: str | None = None,
) -> dict[str, Any]:
    """Push text content into the database as a new searchable conversation.

    Args:
        db: Database instance.
        conn: Async database connection.
        user_id: Owner user ID (None in stdio mode).
        content: The text content to store.
        title: Optional title (auto-generated from first line if not provided).
        source_type: Source type label (default "push").
        tags: Optional list of tags.
        project: Optional project label.

    Returns:
        Dict with conversation_id, title, and tags.
    """
    conversation_id = f"push-{uuid.uuid4()}"
    now = time.time()

    if not title:
        first_line = content.strip().split("\n", 1)[0]
        title = re.sub(r'^#+\s*', '', first_line).strip()[:200] or "Untitled"

    source_id = await _get_or_create_push_source(db, conn, source_type)

    await db.insert_conversation(
        conn,
        user_id,
        id=conversation_id,
        source_id=source_id,
        title=title,
        create_time=now,
        update_time=now,
        message_count=1,
        source_type=source_type,
        project=project,
        tags=tags,
    )

    await db.insert_messages_batch(conn, [{
        "id": f"{conversation_id}-msg-1",
        "conversation_id": conversation_id,
        "role": "user",
        "content_type": "text",
        "content_text": content,
        "is_canonical": True,
        "create_time": now,
    }])

    return {
        "conversation_id": conversation_id,
        "title": title,
        "tags": tags or [],
    }
