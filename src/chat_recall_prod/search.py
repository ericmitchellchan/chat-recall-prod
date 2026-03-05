"""Postgres tsvector search engine for Chat Recall production.

Translates from SQLite FTS5 to Postgres full-text search:
- MATCH → search_vector @@ plainto_tsquery('english', ...)
- bm25() → ts_rank(search_vector, query)
- snippet() → ts_headline('english', content_text, query, ...)
- json_each for tags → JSONB @> operator
"""

import json
import re
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from chat_recall_prod.response_models import (
    ConversationDetail,
    ConversationListResult,
    ConversationSummary,
    MessageResult,
    RecallStats,
    SearchHit,
    SearchResult,
    _ts_to_iso,
)

NOISE_CONTENT_TYPES = {"reasoning_recap", "thoughts", "user_editable_context", "code"}
NOISE_ROLES = {"tool"}


def _parse_tags(tags_val: Any) -> list[str]:
    """Parse tags from a Postgres JSONB value (already deserialized by psycopg)."""
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


def _noise_filters() -> tuple[str, list[Any]]:
    """Return SQL conditions and params to exclude noise messages."""
    ct_placeholders = ",".join("%s" for _ in NOISE_CONTENT_TYPES)
    role_placeholders = ",".join("%s" for _ in NOISE_ROLES)
    conditions = [
        "length(m.content_text) > 0",
        f"m.content_type NOT IN ({ct_placeholders})",
        f"m.role NOT IN ({role_placeholders})",
    ]
    params: list[Any] = list(NOISE_CONTENT_TYPES) + list(NOISE_ROLES)
    return " AND ".join(conditions), params


class SearchEngine:
    """Postgres tsvector-based search over imported conversations."""

    async def search(
        self,
        conn: AsyncConnection,
        user_id: str,
        query: str,
        page: int = 1,
        page_size: int = 20,
        role: str | None = None,
        canonical_only: bool = True,
        date_from: float | None = None,
        date_to: float | None = None,
        source_type: str | None = None,
        project: str | None = None,
        tags: list[str] | None = None,
    ) -> SearchResult:
        """Full-text search with ts_rank ranking and ts_headline snippets."""
        conn.row_factory = dict_row
        noise_sql, noise_params = _noise_filters()
        conditions = ["c.user_id = %s", noise_sql]
        params: list[Any] = [user_id] + noise_params

        if role:
            conditions.append("m.role = %s")
            params.append(role)
        if canonical_only:
            conditions.append("m.is_canonical = true")
        if date_from is not None:
            conditions.append("m.create_time >= %s")
            params.append(date_from)
        if date_to is not None:
            conditions.append("m.create_time <= %s")
            params.append(date_to)
        if source_type is not None:
            conditions.append("c.source_type = %s")
            params.append(source_type)
        if project is not None:
            conditions.append("c.project = %s")
            params.append(project)
        if tags:
            conditions.append("c.tags @> %s::jsonb")
            params.append(json.dumps(tags))

        sanitized = self._sanitize_query(query)
        if not sanitized:
            return SearchResult(query=query, hits=[], total=0, page=page, page_size=page_size)

        conditions.append("m.search_vector @@ plainto_tsquery('english', %s)")
        params.append(sanitized)

        where = " AND ".join(conditions)

        # Count
        count_sql = (
            f"SELECT COUNT(*) FROM messages m "
            f"JOIN conversations c ON m.conversation_id = c.id "
            f"WHERE {where}"
        )
        cur = await conn.execute(count_sql, params)
        total = (await cur.fetchone())[0]

        # Search with ranking and snippets
        offset = (page - 1) * page_size
        search_params = params + [sanitized, sanitized, page_size, offset]
        search_sql = (
            f"SELECT m.conversation_id, m.role, m.create_time, "
            f"c.title AS conversation_title, "
            f"ts_headline('english', m.content_text, plainto_tsquery('english', %s), "
            f"'StartSel=**, StopSel=**, MaxFragments=1, MaxWords=40, MinWords=20') AS snippet, "
            f"ts_rank(m.search_vector, plainto_tsquery('english', %s)) AS rank "
            f"FROM messages m "
            f"JOIN conversations c ON m.conversation_id = c.id "
            f"WHERE {where} "
            f"ORDER BY rank DESC "
            f"LIMIT %s OFFSET %s"
        )
        cur = await conn.execute(search_sql, search_params)
        rows = await cur.fetchall()

        hits = [
            SearchHit(
                conversation_id=row["conversation_id"],
                conversation_title=row["conversation_title"],
                role=row["role"],
                snippet=row["snippet"] or "",
                time=_ts_to_iso(row["create_time"]),
            )
            for row in rows
        ]

        return SearchResult(query=query, hits=hits, total=total, page=page, page_size=page_size)

    async def list_conversations(
        self,
        conn: AsyncConnection,
        user_id: str,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "update_time",
        order: str = "desc",
        source_type: str | None = None,
        project: str | None = None,
    ) -> ConversationListResult:
        """List conversations with pagination, filtered by user_id."""
        conn.row_factory = dict_row
        conditions = ["user_id = %s"]
        params: list[Any] = [user_id]

        if source_type is not None:
            conditions.append("source_type = %s")
            params.append(source_type)
        if project is not None:
            conditions.append("project = %s")
            params.append(project)

        where = " AND ".join(conditions)

        cur = await conn.execute(f"SELECT COUNT(*) FROM conversations WHERE {where}", params)
        total = (await cur.fetchone())[0]

        allowed_sorts = {"create_time", "update_time", "title", "message_count"}
        if sort_by not in allowed_sorts:
            sort_by = "update_time"
        order_dir = "DESC" if order.lower() == "desc" else "ASC"

        offset = (page - 1) * page_size
        cur = await conn.execute(
            f"SELECT id, title, create_time, update_time, model, "
            f"message_count, source_type, project, tags "
            f"FROM conversations WHERE {where} "
            f"ORDER BY {sort_by} {order_dir} NULLS LAST "
            f"LIMIT %s OFFSET %s",
            params + [page_size, offset],
        )
        rows = await cur.fetchall()

        conversations = [
            ConversationSummary(
                id=row["id"],
                title=row["title"],
                created=_ts_to_iso(row["create_time"]),
                updated=_ts_to_iso(row["update_time"]),
                model=row["model"],
                message_count=row["message_count"],
                source_type=row["source_type"],
                project=row["project"],
                tags=_parse_tags(row["tags"]),
            )
            for row in rows
        ]

        return ConversationListResult(
            conversations=conversations, total=total, page=page, page_size=page_size,
        )

    async def get_conversation(
        self,
        conn: AsyncConnection,
        user_id: str,
        conversation_id: str,
        canonical_only: bool = True,
    ) -> ConversationDetail | None:
        """Get a full conversation with messages, filtered by user_id."""
        conn.row_factory = dict_row
        cur = await conn.execute(
            "SELECT * FROM conversations WHERE id = %s AND user_id = %s",
            (conversation_id, user_id),
        )
        conv = await cur.fetchone()
        if not conv:
            return None

        noise_sql, noise_params = _noise_filters()
        conditions = ["m.conversation_id = %s", noise_sql]
        params: list[Any] = [conversation_id] + noise_params
        if canonical_only:
            conditions.append("m.is_canonical = true")

        where = " AND ".join(conditions)
        cur = await conn.execute(
            f"SELECT m.role, m.content_text, m.create_time "
            f"FROM messages m WHERE {where} "
            f"ORDER BY m.create_time ASC NULLS FIRST",
            params,
        )
        rows = await cur.fetchall()

        messages = [
            MessageResult(
                role=row["role"],
                content=row["content_text"],
                time=_ts_to_iso(row["create_time"]),
            )
            for row in rows
        ]

        return ConversationDetail(
            id=conv["id"],
            title=conv["title"],
            created=_ts_to_iso(conv["create_time"]),
            updated=_ts_to_iso(conv["update_time"]),
            model=conv["model"],
            message_count=len(messages),
            source_type=conv["source_type"],
            project=conv["project"],
            tags=_parse_tags(conv["tags"]),
            messages=messages,
        )

    async def search_by_tags(
        self,
        conn: AsyncConnection,
        user_id: str,
        tags: list[str],
        page: int = 1,
        page_size: int = 20,
    ) -> ConversationListResult:
        """Find conversations that have ALL specified tags (JSONB @> operator)."""
        conn.row_factory = dict_row
        conditions = ["user_id = %s"]
        params: list[Any] = [user_id]

        if tags:
            conditions.append("tags @> %s::jsonb")
            params.append(json.dumps(tags))

        where = " AND ".join(conditions)

        cur = await conn.execute(f"SELECT COUNT(*) FROM conversations WHERE {where}", params)
        total = (await cur.fetchone())[0]

        offset = (page - 1) * page_size
        cur = await conn.execute(
            f"SELECT id, title, create_time, update_time, model, "
            f"message_count, source_type, project, tags "
            f"FROM conversations WHERE {where} "
            f"ORDER BY update_time DESC NULLS LAST "
            f"LIMIT %s OFFSET %s",
            params + [page_size, offset],
        )
        rows = await cur.fetchall()

        conversations = [
            ConversationSummary(
                id=row["id"],
                title=row["title"],
                created=_ts_to_iso(row["create_time"]),
                updated=_ts_to_iso(row["update_time"]),
                model=row["model"],
                message_count=row["message_count"],
                source_type=row["source_type"],
                project=row["project"],
                tags=_parse_tags(row["tags"]),
            )
            for row in rows
        ]

        return ConversationListResult(
            conversations=conversations, total=total, page=page, page_size=page_size,
        )

    async def get_stats(
        self,
        conn: AsyncConnection,
        user_id: str,
    ) -> RecallStats:
        """Get per-user database statistics."""
        conn.row_factory = dict_row
        cur = await conn.execute(
            "SELECT COUNT(*) as count, MIN(create_time) as earliest, "
            "MAX(create_time) as latest FROM conversations WHERE user_id = %s",
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

        earliest = _ts_to_iso(row["earliest"])
        latest = _ts_to_iso(row["latest"])
        date_range = f"{earliest} to {latest}" if earliest and latest else None

        return RecallStats(
            conversations=row["count"],
            messages=msg_count,
            date_range=date_range,
            roles=roles,
            models=models,
        )

    @staticmethod
    def _sanitize_query(query: str) -> str:
        """Clean user query for Postgres plainto_tsquery (simpler than FTS5)."""
        query = query.strip()
        if not query:
            return ""
        # Remove any special characters that could break tsquery
        query = re.sub(r'[!&|():*<>]', ' ', query)
        query = " ".join(query.split())
        return query
