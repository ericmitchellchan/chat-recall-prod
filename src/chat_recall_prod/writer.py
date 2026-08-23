"""Async writer for pushing content into the Postgres recall database."""

from __future__ import annotations

import hashlib
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


def conversation_id_for(user_id: str | None, external_id: str) -> str:
    """Stable conversation id for a caller-supplied external key.

    Hashed rather than interpolated: an external id is whatever the caller
    keys on (a Slack channel + thread_ts, a file path, an issue key) and it
    lands in a primary key, so the length and character set have to be ours
    and not theirs.

    The user id goes INSIDE the hash because conversations.id is globally
    unique, not unique per user. Without it, two users pushing the same
    external id would collide on the primary key — and since
    insert_conversation is ON CONFLICT DO NOTHING, the second one's write
    would silently vanish into the first one's row.
    """
    digest = hashlib.sha256(f"{user_id or ''}\x00{external_id}".encode()).hexdigest()
    return f"push-{digest[:32]}"


async def push_content(
    db: Database,
    conn: AsyncConnection,
    user_id: str | None,
    content: str,
    title: str | None = None,
    source_type: str = "push",
    tags: list[str] | None = None,
    project: str | None = None,
    external_id: str | None = None,
) -> dict[str, Any]:
    """Push text content into the database as a searchable conversation.

    With an `external_id`, the push is an UPSERT: the conversation id is
    derived from the key, and pushing the same key again replaces the stored
    content instead of adding a second copy. `create_time` survives from the
    first push while `update_time` moves, so a re-pushed entry keeps both
    "first seen" and "last changed" — a snapshot of something that is still
    evolving (a Slack thread, a doc) stays one row.

    Without an `external_id`, behavior is unchanged: a random id, always a new
    conversation.

    Args:
        db: Database instance.
        conn: Async database connection.
        user_id: Owner user ID (None in stdio mode).
        content: The text content to store.
        title: Optional title (auto-generated from first line if not provided).
        source_type: Source type label (default "push").
        tags: Optional list of tags.
        project: Optional project label.
        external_id: Optional stable key. Re-pushing it replaces the entry.

    Returns:
        Dict with conversation_id, title, tags, and `replaced` (True when this
        overwrote an existing entry rather than creating one).
    """
    now = time.time()

    existing = None
    if external_id:
        conversation_id = conversation_id_for(user_id, external_id)
        existing = await db.get_conversation(conn, user_id, conversation_id)
    else:
        conversation_id = f"push-{uuid.uuid4()}"

    if not title:
        first_line = content.strip().split("\n", 1)[0]
        title = re.sub(r'^#+\s*', '', first_line).strip()[:200] or "Untitled"

    source_id = await _get_or_create_push_source(db, conn, source_type)

    if existing:
        # Replace in place. Both inserts below are ON CONFLICT DO NOTHING, so
        # re-pushing a known id would otherwise keep the OLD content and still
        # report success — the failure mode this whole path exists to avoid.
        # Metadata is overwritten wholesale, empty values included: a replace
        # replaces, so the new push's tags and project win outright.
        await db.delete_messages(conn, user_id, conversation_id)
        await db.update_conversation(
            conn,
            user_id,
            conversation_id,
            source_id=source_id,
            title=title,
            update_time=now,
            message_count=1,
            source_type=source_type,
            project=project,
            tags=tags,
        )
    else:
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

    # search_vector is a GENERATED ALWAYS ... STORED tsvector on messages, so
    # re-inserting the row is all the FTS index refresh a replace needs.
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
        "replaced": existing is not None,
    }
