"""Async ChatGPT conversations.json importer for Postgres.

Ported from chat-recall-mcp with async operations and user_id isolation.
"""

import json
import logging
from typing import Any

from psycopg import AsyncConnection

from chat_recall_prod.content import extract_text
from chat_recall_prod.db.queries import Database

logger = logging.getLogger(__name__)


class ChatGPTImporter:
    """Import ChatGPT conversation exports (conversations.json) into Postgres."""

    source_type = "chatgpt"

    def __init__(self, db: Database):
        self.db = db

    async def import_data(
        self,
        conn: AsyncConnection,
        user_id: str,
        conversations_data: list[dict[str, Any]],
        file_path: str = "upload",
    ) -> dict[str, Any]:
        """Import conversations from parsed JSON data.

        Args:
            conn: Async Postgres connection.
            user_id: User who owns the data.
            conversations_data: Parsed conversations.json content.
            file_path: Source file identifier for the sources table.

        Returns:
            Stats dict with import counts.
        """
        source_id = await self.db.insert_source(
            conn, self.source_type, file_path,
            record_count=len(conversations_data),
        )

        total_messages = 0
        imported_convos = 0
        updated_convos = 0
        skipped_convos = 0
        skip_reasons: dict[str, int] = {
            "already_exists": 0,
            "missing_id": 0,
            "parse_error": 0,
        }
        errors: list[str] = []

        for conv in conversations_data:
            conv_id = conv.get("id")
            if not conv_id:
                skipped_convos += 1
                skip_reasons["missing_id"] += 1
                continue

            try:
                messages, has_branches = self._parse_conversation(conv, conv_id)
            except (KeyError, TypeError, json.JSONDecodeError) as e:
                logger.warning("Skipping conversation %s: %s", conv_id, e, exc_info=True)
                skipped_convos += 1
                skip_reasons["parse_error"] += 1
                errors.append(f"{conv_id}: {e}")
                continue

            # Check if already imported for this user
            existing = await self.db.get_conversation(conn, user_id, conv_id)
            if existing:
                if len(messages) > existing["message_count"]:
                    await self.db.delete_messages(conn, user_id, conv_id)
                    await self.db.insert_messages_batch(conn, messages)
                    await self.db.update_conversation(
                        conn, user_id, conv_id,
                        message_count=len(messages),
                        update_time=conv.get("update_time"),
                    )
                    total_messages += len(messages)
                    updated_convos += 1
                else:
                    skipped_convos += 1
                    skip_reasons["already_exists"] += 1
                continue

            model = self._detect_model(conv, messages)

            metadata = {
                k: v for k, v in conv.items()
                if k in ("conversation_template_id", "is_archived", "safe_urls")
            } or None

            await self.db.insert_conversation(
                conn,
                user_id=user_id,
                id=conv_id,
                source_id=source_id,
                title=conv.get("title"),
                create_time=conv.get("create_time"),
                update_time=conv.get("update_time"),
                model=model,
                gizmo_id=conv.get("gizmo_id"),
                message_count=len(messages),
                has_branches=has_branches,
                metadata=metadata,
                source_type=self.source_type,
            )

            count = await self.db.insert_messages_batch(conn, messages)
            total_messages += count
            imported_convos += 1

        return {
            "conversations_imported": imported_convos,
            "conversations_updated": updated_convos,
            "conversations_skipped": skipped_convos,
            "messages_imported": total_messages,
            "source_id": source_id,
            "skip_reasons": skip_reasons,
            "errors": errors,
        }

    def _parse_conversation(
        self, conv: dict, conv_id: str,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Parse messages from a conversation, tracing the canonical path."""
        mapping = conv.get("mapping", {})
        if not mapping:
            return [], False

        current_node = conv.get("current_node")
        canonical_ids = self._trace_canonical_path(mapping, current_node)
        has_branches = self._detect_branches(mapping)

        messages = []
        for node_id, node in mapping.items():
            msg = node.get("message")
            if msg is None:
                continue

            author = msg.get("author", {})
            role = author.get("role")
            content = msg.get("content", {})
            content_type = content.get("content_type", "text") if content else "text"
            content_text = extract_text(content)

            if role == "system" and not content_text:
                continue

            raw_content = json.dumps(content) if content else None
            attachments = msg.get("metadata", {}).get("attachments")

            msg_metadata = {}
            msg_meta = msg.get("metadata", {})
            if msg_meta.get("model_slug"):
                msg_metadata["model_slug"] = msg_meta["model_slug"]
            if msg_meta.get("finish_details"):
                msg_metadata["finish_details"] = msg_meta["finish_details"]

            messages.append({
                "id": msg.get("id", node_id),
                "conversation_id": conv_id,
                "parent_id": node.get("parent"),
                "role": role,
                "content_type": content_type,
                "content_text": content_text if content_text else None,
                "raw_content": raw_content,
                "is_canonical": node_id in canonical_ids,
                "create_time": msg.get("create_time"),
                "attachments": attachments,
                "metadata": msg_metadata if msg_metadata else None,
            })

        return messages, has_branches

    def _trace_canonical_path(
        self, mapping: dict, current_node: str | None,
    ) -> set[str]:
        """Walk from current_node back to root to find canonical message path."""
        canonical = set()
        if not current_node:
            return canonical
        node_id = current_node
        while node_id:
            canonical.add(node_id)
            node = mapping.get(node_id)
            if not node:
                break
            node_id = node.get("parent")
        return canonical

    def _detect_branches(self, mapping: dict) -> bool:
        """Detect if conversation has branches (any node with >1 child)."""
        for node in mapping.values():
            children = node.get("children", [])
            if len(children) > 1:
                return True
        return False

    def _detect_model(
        self, conv: dict, messages: list[dict[str, Any]],
    ) -> str | None:
        """Detect the model used from conversation or message metadata."""
        default = conv.get("default_model_slug")
        if default:
            return default
        for msg in messages:
            if msg["role"] == "assistant" and msg.get("metadata"):
                meta = msg["metadata"]
                if isinstance(meta, dict):
                    slug = meta.get("model_slug")
                    if slug:
                        return slug
        return None
