"""Tests for Pydantic response models."""

from datetime import datetime, timezone
from uuid import uuid4

from chat_recall_prod.response_models import (
    ConversationDetail,
    ConversationListResult,
    ConversationSummary,
    MessageResult,
    PushContentResult,
    RecallStats,
    SearchHit,
    SearchResult,
    ThreadDetail,
    ThreadSummary,
    _ts_to_iso,
)


def test_ts_to_iso_none():
    assert _ts_to_iso(None) is None


def test_ts_to_iso_float():
    # 2024-01-01 00:00 UTC
    result = _ts_to_iso(1704067200.0)
    assert result == "2024-01-01 00:00"


def test_ts_to_iso_datetime():
    dt = datetime(2024, 6, 15, 12, 30, tzinfo=timezone.utc)
    result = _ts_to_iso(dt)
    assert result == "2024-06-15 12:30"


def test_message_result_defaults():
    msg = MessageResult()
    assert msg.role is None
    assert msg.content is None
    assert msg.time is None


def test_message_result_with_values():
    msg = MessageResult(role="user", content="Hello", time="2024-01-01 12:00")
    dumped = msg.model_dump()
    assert dumped["role"] == "user"
    assert dumped["content"] == "Hello"


def test_search_hit():
    hit = SearchHit(
        conversation_id="conv-123",
        conversation_title="Test Chat",
        role="assistant",
        snippet="This is a <b>match</b>",
        time="2024-01-01 12:00",
    )
    assert hit.conversation_id == "conv-123"
    assert hit.snippet == "This is a <b>match</b>"


def test_search_result():
    result = SearchResult(
        query="hello",
        hits=[
            SearchHit(conversation_id="c1", snippet="hi there"),
            SearchHit(conversation_id="c2", snippet="hello world"),
        ],
        total=2,
        page=1,
        page_size=20,
    )
    dumped = result.model_dump()
    assert dumped["total"] == 2
    assert len(dumped["hits"]) == 2


def test_conversation_summary_defaults():
    summary = ConversationSummary(id="conv-1")
    assert summary.tags == []
    assert summary.message_count == 0
    assert summary.source_type is None


def test_conversation_summary_full():
    summary = ConversationSummary(
        id="conv-1",
        title="Architecture Discussion",
        created="2024-01-01 12:00",
        updated="2024-01-02 15:30",
        model="gpt-4",
        message_count=42,
        source_type="chatgpt",
        project="chat-recall",
        tags=["architecture", "planning"],
    )
    dumped = summary.model_dump()
    assert dumped["id"] == "conv-1"
    assert dumped["tags"] == ["architecture", "planning"]


def test_conversation_list_result():
    result = ConversationListResult(
        conversations=[ConversationSummary(id="c1"), ConversationSummary(id="c2")],
        total=50,
        page=1,
        page_size=20,
    )
    assert result.total == 50
    assert len(result.conversations) == 2


def test_conversation_detail():
    detail = ConversationDetail(
        id="conv-1",
        title="Test",
        messages=[
            MessageResult(role="user", content="Hi"),
            MessageResult(role="assistant", content="Hello!"),
        ],
    )
    dumped = detail.model_dump()
    assert len(dumped["messages"]) == 2
    assert dumped["messages"][0]["role"] == "user"


def test_push_content_result():
    result = PushContentResult(
        conversation_id="conv-new",
        title="New Conversation",
        tags=["important", "meeting"],
    )
    dumped = result.model_dump()
    assert dumped["conversation_id"] == "conv-new"
    assert dumped["tags"] == ["important", "meeting"]


def test_recall_stats_defaults():
    stats = RecallStats()
    assert stats.conversations == 0
    assert stats.messages == 0
    assert stats.roles == {}
    assert stats.models == {}


def test_recall_stats_with_data():
    stats = RecallStats(
        conversations=150,
        messages=5000,
        date_range="2023-01-01 to 2024-06-15",
        roles={"user": 2500, "assistant": 2500},
        models={"gpt-4": 100, "gpt-3.5": 50},
    )
    dumped = stats.model_dump()
    assert dumped["conversations"] == 150
    assert dumped["roles"]["user"] == 2500


def test_thread_summary():
    summary = ThreadSummary(
        id="thread-1",
        title="Architecture Decisions",
        description="Key arch decisions for the project",
        status="active",
        tags=["architecture"],
        conversation_count=5,
        created="2024-01-01 12:00",
    )
    dumped = summary.model_dump()
    assert dumped["id"] == "thread-1"
    assert dumped["conversation_count"] == 5


def test_thread_detail():
    detail = ThreadDetail(
        id="thread-1",
        title="Architecture Decisions",
        conversations=[
            ConversationSummary(id="c1", title="DB choice"),
            ConversationSummary(id="c2", title="Auth design"),
        ],
    )
    dumped = detail.model_dump()
    assert len(dumped["conversations"]) == 2
    assert dumped["conversations"][0]["title"] == "DB choice"


def test_uuid_serialization():
    """UUIDs should serialize as strings in JSON output."""
    uid = uuid4()
    result = PushContentResult(
        conversation_id=str(uid),
        title="Test",
    )
    dumped = result.model_dump()
    assert isinstance(dumped["conversation_id"], str)
    assert dumped["conversation_id"] == str(uid)
