"""Pydantic response models for MCP tools — production version.

Ported from chat-recall-mcp/src/chat_recall/models.py with adaptations
for Postgres data types (UUIDs, datetime objects alongside timestamps).
"""

from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel


def _ts_to_iso(ts: float | datetime | None) -> str | None:
    """Convert a Unix timestamp or datetime to an ISO 8601 display string."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts.strftime("%Y-%m-%d %H:%M")
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


class MessageResult(BaseModel):
    role: str | None = None
    content: str | None = None
    time: str | None = None


class SearchHit(BaseModel):
    conversation_id: str
    conversation_title: str | None = None
    role: str | None = None
    snippet: str = ""
    time: str | None = None


class SearchResult(BaseModel):
    query: str
    hits: list[SearchHit]
    total: int
    page: int
    page_size: int


class ConversationSummary(BaseModel):
    id: str
    title: str | None = None
    created: str | None = None
    updated: str | None = None
    model: str | None = None
    message_count: int = 0
    source_type: str | None = None
    project: str | None = None
    tags: list[str] = []


class ConversationListResult(BaseModel):
    conversations: list[ConversationSummary]
    total: int
    page: int
    page_size: int


class ConversationDetail(BaseModel):
    id: str
    title: str | None = None
    created: str | None = None
    updated: str | None = None
    model: str | None = None
    message_count: int = 0
    source_type: str | None = None
    project: str | None = None
    tags: list[str] = []
    messages: list[MessageResult]


class PushContentResult(BaseModel):
    conversation_id: str
    title: str
    tags: list[str] = []


class RecallStats(BaseModel):
    conversations: int = 0
    messages: int = 0
    date_range: str | None = None
    roles: dict[str, int] = {}
    models: dict[str, int] = {}


class ThreadSummary(BaseModel):
    id: str
    title: str
    description: str | None = None
    status: str = "active"
    tags: list[str] = []
    conversation_count: int = 0
    created: str | None = None
    updated: str | None = None


class ThreadDetail(BaseModel):
    id: str
    title: str
    description: str | None = None
    status: str = "active"
    tags: list[str] = []
    conversations: list[ConversationSummary] = []
    created: str | None = None
    updated: str | None = None
