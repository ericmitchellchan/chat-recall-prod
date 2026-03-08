"""Production MCP server — async, Postgres-backed, multi-user.

All 12 tools from chat-recall-mcp, ported to async with user_id isolation.
Supports both stdio (local dev) and HTTP (production) transport.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from fastmcp import FastMCP, Context
from psycopg.rows import dict_row
from starlette.requests import Request
from starlette.responses import JSONResponse

from chat_recall_prod.db import Database, get_pool, init_pool, close_pool
from chat_recall_prod.search import SearchEngine, _parse_tags
from chat_recall_prod.threads import (
    create_thread as _create_thread,
    get_thread as _get_thread,
    link_conversation as _link_conversation,
    list_threads as _list_threads,
)
from chat_recall_prod.writer import push_content as _push_content

logger = logging.getLogger(__name__)

mcp = FastMCP("chat-recall-prod")


def _error(msg: str) -> dict:
    """Standardized error response."""
    return {"error": msg}


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    return JSONResponse({"status": "healthy", "service": "chat-recall-prod"})


# ── Module-level state ────────────────────────────────────────────────────

_db: Database | None = None


async def _get_db() -> Database:
    """Get or lazily create the Database singleton."""
    global _db
    if _db is None:
        pool = await init_pool()
        _db = Database(pool)
    return _db


async def _get_user_id(ctx: Context) -> str | None:
    """Extract user_id from auth context. Returns env fallback in stdio mode.

    Phase 1 (current): Returns RECALL_USER_ID env var.
    Phase 2 (multi-user): Will extract GitHub identity from OAuth context
    and resolve to Postgres user UUID via resolve_user_id().
    """
    return os.environ.get("RECALL_USER_ID")


# ── Search tools ──────────────────────────────────────────────────────────


@mcp.tool()
async def search_conversations(
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
    ctx: Context | None = None,
) -> dict:
    """Search your conversation history using full-text search.

    Args:
        query: Search terms (supports natural language queries)
        page: Page number (1-indexed)
        page_size: Results per page (default 20)
        role: Filter by message role (user, assistant, system, tool)
        canonical_only: Only search the main conversation path, not branches
        date_from: Unix timestamp lower bound
        date_to: Unix timestamp upper bound
        source_type: Filter by source ("chatgpt" or "claude-code")
        project: Filter by project name (e.g. "my-app", "orbit")
        tags: Filter by tags (conversations must have ALL specified tags)

    Returns:
        Search results with conversation titles, message snippets, and relevance ranking.
    """
    try:
        user_id = await _get_user_id(ctx)
        engine = SearchEngine()
        async with get_pool().connection() as conn:
            result = await engine.search(
                conn, user_id, query,
                page=page, page_size=page_size, role=role,
                canonical_only=canonical_only, date_from=date_from,
                date_to=date_to, source_type=source_type,
                project=project, tags=tags,
            )
        return result.model_dump()
    except Exception as e:
        logger.error("search_conversations failed: %s", e, exc_info=True)
        return _error(f"search_conversations failed: {e}")


@mcp.tool()
async def list_conversations(
    page: int = 1,
    page_size: int = 20,
    sort_by: str = "update_time",
    order: str = "desc",
    source_type: str | None = None,
    project: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """Browse and paginate all imported conversations.

    Args:
        page: Page number (1-indexed)
        page_size: Results per page (default 20)
        sort_by: Sort field (create_time, update_time, title, message_count)
        order: Sort order (asc or desc)
        source_type: Filter by source ("chatgpt" or "claude-code")
        project: Filter by project name (e.g. "my-app", "orbit")

    Returns:
        Paginated list of conversations with titles, dates, and message counts.
    """
    try:
        user_id = await _get_user_id(ctx)
        engine = SearchEngine()
        async with get_pool().connection() as conn:
            result = await engine.list_conversations(
                conn, user_id,
                page=page, page_size=page_size, sort_by=sort_by,
                order=order, source_type=source_type, project=project,
            )
        return result.model_dump()
    except Exception as e:
        logger.error("list_conversations failed: %s", e, exc_info=True)
        return _error(f"list_conversations failed: {e}")


@mcp.tool()
async def get_conversation(
    conversation_id: str,
    canonical_only: bool = True,
    ctx: Context | None = None,
) -> dict:
    """Get a full conversation thread with all messages.

    Args:
        conversation_id: The conversation ID to retrieve
        canonical_only: Only return messages on the main path (not branches)

    Returns:
        Full conversation with metadata and ordered messages.
    """
    try:
        user_id = await _get_user_id(ctx)
        engine = SearchEngine()
        async with get_pool().connection() as conn:
            result = await engine.get_conversation(
                conn, user_id, conversation_id,
                canonical_only=canonical_only,
            )
        if result is None:
            return _error(f"Conversation not found: {conversation_id}")
        return result.model_dump()
    except Exception as e:
        logger.error("get_conversation failed: %s", e, exc_info=True)
        return _error(f"get_conversation failed: {e}")


@mcp.tool()
async def recall_stats(ctx: Context | None = None) -> dict:
    """Get database statistics and overview.

    Returns:
        Counts of conversations and messages, date ranges, model distribution.
    """
    try:
        user_id = await _get_user_id(ctx)
        engine = SearchEngine()
        async with get_pool().connection() as conn:
            result = await engine.get_stats(conn, user_id)
        return result.model_dump()
    except Exception as e:
        logger.error("recall_stats failed: %s", e, exc_info=True)
        return _error(f"recall_stats failed: {e}")


# ── Push content ──────────────────────────────────────────────────────────


@mcp.tool()
async def push_content(
    content: str,
    title: str | None = None,
    source_type: str = "push",
    tags: list[str] | None = None,
    project: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """Push text content into the recall database as a new searchable conversation.

    Args:
        content: The text content to store.
        title: Optional title (auto-generated from first line if not provided).
        source_type: Source type label (default "push").
        tags: Optional list of tags for categorization.
        project: Optional project label.

    Returns:
        Dict with conversation_id, title, and tags.
    """
    try:
        user_id = await _get_user_id(ctx)
        db = await _get_db()
        async with get_pool().connection() as conn:
            result = await _push_content(
                db, conn, user_id,
                content=content, title=title,
                source_type=source_type, tags=tags, project=project,
            )
            # Update analytics counters: push creates 1 conversation with 1 message
            if user_id:
                await db.increment_user_analytics(
                    conn, user_id,
                    conversations=1,
                    messages=1,
                    uploads=1,
                )
            await conn.commit()
        return result
    except Exception as e:
        logger.error("push_content failed: %s", e, exc_info=True)
        return _error(f"push_content failed: {e}")


# ── Sync ──────────────────────────────────────────────────────────────────


@mcp.tool()
async def sync_now(
    conversations_json: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """Trigger an import of ChatGPT conversation data.

    Args:
        conversations_json: JSON string of ChatGPT conversations array to import.
            If not provided, returns current status.

    Returns:
        Import results or status message.
    """
    try:
        user_id = await _get_user_id(ctx)
        if not conversations_json:
            return {
                "status": "ready",
                "message": "Provide conversations_json to import ChatGPT data.",
            }

        data = json.loads(conversations_json)
        if not isinstance(data, list):
            return _error("conversations_json must be a JSON array")

        from chat_recall_prod.importers.chatgpt import ChatGPTImporter

        db = await _get_db()
        importer = ChatGPTImporter(db)
        async with get_pool().connection() as conn:
            result = await importer.import_data(conn, user_id, data)
            # Update analytics counters on the user row
            new_convos = result.get("conversations_imported", 0)
            new_msgs = result.get("messages_imported", 0)
            if user_id and (new_convos or new_msgs):
                await db.increment_user_analytics(
                    conn, user_id,
                    conversations=new_convos,
                    messages=new_msgs,
                    uploads=1,
                )
            await conn.commit()
        return result
    except json.JSONDecodeError as e:
        return _error(f"Invalid JSON: {e}")
    except Exception as e:
        logger.error("sync_now failed: %s", e, exc_info=True)
        return _error(f"sync_now failed: {e}")


# ── Tagging ───────────────────────────────────────────────────────────────


@mcp.tool()
async def tag_conversation(
    conversation_id: str,
    tags: list[str],
    mode: str = "add",
    ctx: Context | None = None,
) -> dict:
    """Add or set tags on a conversation.

    Args:
        conversation_id: The conversation to tag.
        tags: Tags to add or set.
        mode: "add" to append tags, "set" to replace all tags.

    Returns:
        Updated conversation_id and final tags list.
    """
    try:
        user_id = await _get_user_id(ctx)
        async with get_pool().connection() as conn:
            conn.row_factory = dict_row
            cur = await conn.execute(
                "SELECT tags FROM conversations WHERE id = %s AND user_id = %s",
                (conversation_id, user_id),
            )
            row = await cur.fetchone()
            if row is None:
                return _error(f"Conversation not found: {conversation_id}")

            if mode == "set":
                final_tags = list(set(tags))
            else:
                existing = _parse_tags(row["tags"])
                final_tags = list(set(existing + tags))

            await conn.execute(
                "UPDATE conversations SET tags = %s::jsonb WHERE id = %s AND user_id = %s",
                (json.dumps(final_tags), conversation_id, user_id),
            )
            await conn.commit()
        return {"conversation_id": conversation_id, "tags": final_tags}
    except Exception as e:
        logger.error("tag_conversation failed: %s", e, exc_info=True)
        return _error(f"tag_conversation failed: {e}")


@mcp.tool()
async def search_by_tags(
    tags: list[str],
    page: int = 1,
    page_size: int = 20,
    ctx: Context | None = None,
) -> dict:
    """Find conversations by tags.

    Args:
        tags: Tags to search for (conversations must have ALL specified tags).
        page: Page number (1-indexed).
        page_size: Results per page.

    Returns:
        Paginated list of matching conversations.
    """
    try:
        user_id = await _get_user_id(ctx)
        engine = SearchEngine()
        async with get_pool().connection() as conn:
            result = await engine.search_by_tags(
                conn, user_id, tags,
                page=page, page_size=page_size,
            )
        return result.model_dump()
    except Exception as e:
        logger.error("search_by_tags failed: %s", e, exc_info=True)
        return _error(f"search_by_tags failed: {e}")


# ── Threading ─────────────────────────────────────────────────────────────


@mcp.tool()
async def create_thread(
    slug: str,
    title: str,
    description: str | None = None,
    tags: list[str] | None = None,
    ctx: Context | None = None,
) -> dict:
    """Create a new thread to group related conversations.

    Args:
        slug: URL-friendly identifier (lowercase, hyphens, e.g. "project-alpha").
        title: Human-readable title.
        description: Optional description.
        tags: Optional tags for the thread.

    Returns:
        The created thread details.
    """
    try:
        user_id = await _get_user_id(ctx)
        async with get_pool().connection() as conn:
            result = await _create_thread(
                conn, user_id, slug, title,
                description=description, tags=tags,
            )
            await conn.commit()
        return result
    except ValueError as e:
        return _error(str(e))
    except Exception as e:
        logger.error("create_thread failed: %s", e, exc_info=True)
        return _error(f"create_thread failed: {e}")


@mcp.tool()
async def link_to_thread(
    thread_slug: str,
    conversation_id: str,
    note: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """Link a conversation to an existing thread.

    Args:
        thread_slug: The thread slug to link to.
        conversation_id: The conversation to link.
        note: Optional note about why this conversation is linked.

    Returns:
        Confirmation with thread and conversation IDs.
    """
    try:
        user_id = await _get_user_id(ctx)
        async with get_pool().connection() as conn:
            result = await _link_conversation(
                conn, user_id, thread_slug, conversation_id, note=note,
            )
            await conn.commit()
        return result
    except Exception as e:
        logger.error("link_to_thread failed: %s", e, exc_info=True)
        return _error(f"link_to_thread failed: {e}")


@mcp.tool()
async def get_thread(slug: str, ctx: Context | None = None) -> dict:
    """Get a thread with all its linked conversations.

    Args:
        slug: The thread slug.

    Returns:
        Thread details including linked conversations.
    """
    try:
        user_id = await _get_user_id(ctx)
        async with get_pool().connection() as conn:
            result = await _get_thread(conn, user_id, slug)
        if result is None:
            return _error(f"Thread not found: {slug}")
        return result
    except Exception as e:
        logger.error("get_thread failed: %s", e, exc_info=True)
        return _error(f"get_thread failed: {e}")


@mcp.tool()
async def list_threads(
    status: str | None = None,
    tags: list[str] | None = None,
    ctx: Context | None = None,
) -> dict:
    """List all threads, optionally filtered by status or tags.

    Args:
        status: Filter by status (e.g. "active", "archived").
        tags: Filter by tags.

    Returns:
        List of threads with conversation counts.
    """
    try:
        user_id = await _get_user_id(ctx)
        async with get_pool().connection() as conn:
            result = await _list_threads(conn, user_id, status=status, tags=tags)
        return result
    except Exception as e:
        logger.error("list_threads failed: %s", e, exc_info=True)
        return _error(f"list_threads failed: {e}")


# ── Server entry point ────────────────────────────────────────────────────


def main(
    transport: str = "stdio",
    host: str = "0.0.0.0",
    port: int = 8080,
) -> None:
    """Run the MCP server.

    Args:
        transport: "stdio" for local dev, "http" for production.
        host: Bind host for HTTP mode.
        port: Bind port for HTTP mode.
    """
    if transport == "http":
        from chat_recall_prod.auth import get_auth_provider

        auth = get_auth_provider()
        if auth:
            server = FastMCP("chat-recall-prod", auth=auth)
            for name, tool in mcp._tool_manager._tools.items():
                server._tool_manager._tools[name] = tool
            server._additional_http_routes = list(mcp._additional_http_routes)
            server.run(transport="streamable-http", host=host, port=port)
        else:
            mcp.run(transport="streamable-http", host=host, port=port)
    else:
        mcp.run()
