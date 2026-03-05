"""Tests for the ChatGPT importer."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from chat_recall_prod.content import extract_text
from chat_recall_prod.importers.chatgpt import ChatGPTImporter


# ── Content extraction tests ───────────────────────────────────────────


def test_extract_text_none():
    assert extract_text(None) == ""


def test_extract_text_empty():
    assert extract_text({}) == ""


def test_extract_text_plain():
    content = {"content_type": "text", "parts": ["Hello world"]}
    assert extract_text(content) == "Hello world"


def test_extract_text_multipart():
    content = {"content_type": "text", "parts": ["Hello", "World"]}
    assert extract_text(content) == "Hello\nWorld"


def test_extract_text_skips_dicts():
    content = {"content_type": "text", "parts": ["Hello", {"type": "image"}]}
    assert extract_text(content) == "Hello"


def test_extract_code():
    content = {"content_type": "code", "text": "print('hi')", "language": "python"}
    assert extract_text(content) == "```python\nprint('hi')\n```"


def test_extract_code_no_lang():
    content = {"content_type": "code", "text": "print('hi')"}
    assert extract_text(content) == "print('hi')"


def test_extract_multimodal_text():
    content = {
        "content_type": "multimodal_text",
        "parts": ["Check this image", {"content_type": "image_asset_pointer"}],
    }
    assert extract_text(content) == "Check this image"


def test_extract_reasoning_recap():
    content = {"content_type": "reasoning_recap", "content": "Thought for 6s"}
    assert extract_text(content) == "Thought for 6s"


def test_extract_thoughts():
    content = {
        "content_type": "thoughts",
        "thoughts": [{"content": "thinking step 1"}, {"content": "step 2"}],
    }
    assert extract_text(content) == "thinking step 1\nstep 2"


def test_extract_tether_quote():
    content = {
        "content_type": "tether_quote",
        "title": "Article",
        "text": "Some quoted text",
        "url": "https://example.com",
    }
    result = extract_text(content)
    assert "[Article]" in result
    assert "Some quoted text" in result


def test_extract_unknown_fallback():
    content = {"content_type": "new_type_2025", "text": "fallback text"}
    assert extract_text(content) == "fallback text"


# ── Importer parsing tests ────────────────────────────────────────────


def _make_conversation(
    conv_id: str = "conv-1",
    title: str = "Test Chat",
    messages: list[dict] | None = None,
) -> dict:
    """Build a minimal ChatGPT conversation dict."""
    if messages is None:
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]

    mapping = {}
    parent_id = None
    node_ids = []
    for i, msg in enumerate(messages):
        node_id = f"node-{i}"
        node_ids.append(node_id)
        mapping[node_id] = {
            "id": node_id,
            "parent": parent_id,
            "children": [],
            "message": {
                "id": f"msg-{i}",
                "author": {"role": msg["role"]},
                "content": {"content_type": "text", "parts": [msg["content"]]},
                "create_time": 1704067200.0 + i,
                "metadata": {},
            },
        }
        if parent_id and parent_id in mapping:
            mapping[parent_id]["children"].append(node_id)
        parent_id = node_id

    return {
        "id": conv_id,
        "title": title,
        "create_time": 1704067200.0,
        "update_time": 1704153600.0,
        "mapping": mapping,
        "current_node": node_ids[-1] if node_ids else None,
    }


class TestImporterParsing:
    def setup_method(self):
        mock_pool = MagicMock()
        from chat_recall_prod.db.queries import Database
        self.db = Database(mock_pool)
        self.importer = ChatGPTImporter(self.db)

    def test_parse_conversation_basic(self):
        conv = _make_conversation()
        messages, has_branches = self.importer._parse_conversation(conv, "conv-1")
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"
        assert not has_branches

    def test_parse_conversation_empty_mapping(self):
        conv = {"id": "conv-1", "mapping": {}}
        messages, has_branches = self.importer._parse_conversation(conv, "conv-1")
        assert messages == []
        assert not has_branches

    def test_canonical_path_tracing(self):
        conv = _make_conversation()
        mapping = conv["mapping"]
        canonical = self.importer._trace_canonical_path(mapping, conv["current_node"])
        assert len(canonical) == 2
        assert "node-0" in canonical
        assert "node-1" in canonical

    def test_canonical_path_none_current(self):
        mapping = {"node-1": {"parent": None}}
        canonical = self.importer._trace_canonical_path(mapping, None)
        assert canonical == set()

    def test_detect_branches(self):
        mapping = {
            "root": {"children": ["a", "b"]},
            "a": {"children": []},
            "b": {"children": []},
        }
        assert self.importer._detect_branches(mapping) is True

    def test_no_branches(self):
        mapping = {
            "root": {"children": ["a"]},
            "a": {"children": []},
        }
        assert self.importer._detect_branches(mapping) is False

    def test_detect_model_from_default(self):
        conv = {"default_model_slug": "gpt-4"}
        model = self.importer._detect_model(conv, [])
        assert model == "gpt-4"

    def test_detect_model_from_message_metadata(self):
        conv = {}
        messages = [
            {"role": "user", "metadata": None},
            {"role": "assistant", "metadata": {"model_slug": "gpt-4o"}},
        ]
        model = self.importer._detect_model(conv, messages)
        assert model == "gpt-4o"

    def test_detect_model_none(self):
        conv = {}
        messages = [{"role": "user", "metadata": None}]
        model = self.importer._detect_model(conv, messages)
        assert model is None

    def test_skips_empty_system_messages(self):
        conv = _make_conversation(messages=[
            {"role": "system", "content": ""},
            {"role": "user", "content": "Hello"},
        ])
        messages, _ = self.importer._parse_conversation(conv, "conv-1")
        roles = [m["role"] for m in messages]
        assert "system" not in roles


# ── Importer async integration tests (mocked DB) ──────────────────────


class TestImporterImport:
    def setup_method(self):
        mock_pool = MagicMock()
        from chat_recall_prod.db.queries import Database
        self.db = Database(mock_pool)
        self.importer = ChatGPTImporter(self.db)

    @pytest.mark.asyncio
    async def test_import_basic(self):
        conn = AsyncMock()

        # Mock insert_source
        self.db.insert_source = AsyncMock(return_value=1)
        # Mock get_conversation (not found)
        self.db.get_conversation = AsyncMock(return_value=None)
        # Mock insert_conversation
        self.db.insert_conversation = AsyncMock()
        # Mock insert_messages_batch
        self.db.insert_messages_batch = AsyncMock(return_value=2)

        conversations = [_make_conversation()]
        result = await self.importer.import_data(conn, "user-123", conversations)

        assert result["conversations_imported"] == 1
        assert result["messages_imported"] == 2
        assert result["conversations_skipped"] == 0
        assert result["source_id"] == 1

    @pytest.mark.asyncio
    async def test_import_skips_missing_id(self):
        conn = AsyncMock()
        self.db.insert_source = AsyncMock(return_value=1)

        conversations = [{"title": "No ID conversation"}]
        result = await self.importer.import_data(conn, "user-123", conversations)

        assert result["conversations_imported"] == 0
        assert result["conversations_skipped"] == 1
        assert result["skip_reasons"]["missing_id"] == 1

    @pytest.mark.asyncio
    async def test_import_skips_already_exists(self):
        conn = AsyncMock()
        self.db.insert_source = AsyncMock(return_value=1)
        self.db.get_conversation = AsyncMock(return_value={"message_count": 100})

        conversations = [_make_conversation()]
        result = await self.importer.import_data(conn, "user-123", conversations)

        assert result["conversations_imported"] == 0
        assert result["conversations_skipped"] == 1
        assert result["skip_reasons"]["already_exists"] == 1

    @pytest.mark.asyncio
    async def test_import_updates_when_more_messages(self):
        conn = AsyncMock()
        self.db.insert_source = AsyncMock(return_value=1)
        self.db.get_conversation = AsyncMock(return_value={"message_count": 0})
        self.db.delete_messages = AsyncMock(return_value=0)
        self.db.insert_messages_batch = AsyncMock(return_value=2)
        self.db.update_conversation = AsyncMock()

        conversations = [_make_conversation()]
        result = await self.importer.import_data(conn, "user-123", conversations)

        assert result["conversations_updated"] == 1
        assert result["messages_imported"] == 2
        self.db.delete_messages.assert_called_once()

    @pytest.mark.asyncio
    async def test_import_handles_parse_error(self):
        conn = AsyncMock()
        self.db.insert_source = AsyncMock(return_value=1)
        self.db.get_conversation = AsyncMock(return_value=None)
        self.db.insert_conversation = AsyncMock()
        self.db.insert_messages_batch = AsyncMock(return_value=0)

        # Conversation with mapping where message is None — yields 0 messages
        conversations = [{"id": "conv-bad", "mapping": {"node": {"message": None}}}]
        result = await self.importer.import_data(conn, "user-123", conversations)

        # No parseable messages, but conversation still gets imported with 0 messages
        assert result["conversations_imported"] == 1
        assert result["messages_imported"] == 0

    @pytest.mark.asyncio
    async def test_import_multiple_conversations(self):
        conn = AsyncMock()
        self.db.insert_source = AsyncMock(return_value=1)
        self.db.get_conversation = AsyncMock(return_value=None)
        self.db.insert_conversation = AsyncMock()
        self.db.insert_messages_batch = AsyncMock(return_value=2)

        conversations = [
            _make_conversation(conv_id="conv-1", title="Chat 1"),
            _make_conversation(conv_id="conv-2", title="Chat 2"),
            _make_conversation(conv_id="conv-3", title="Chat 3"),
        ]
        result = await self.importer.import_data(conn, "user-123", conversations)

        assert result["conversations_imported"] == 3
        assert result["messages_imported"] == 6

    @pytest.mark.asyncio
    async def test_import_sets_source_type(self):
        conn = AsyncMock()
        self.db.insert_source = AsyncMock(return_value=1)
        self.db.get_conversation = AsyncMock(return_value=None)
        self.db.insert_conversation = AsyncMock()
        self.db.insert_messages_batch = AsyncMock(return_value=2)

        conversations = [_make_conversation()]
        await self.importer.import_data(conn, "user-123", conversations)

        call_kwargs = self.db.insert_conversation.call_args
        # Check source_type was passed
        assert call_kwargs[1]["source_type"] == "chatgpt"
