"""Initial schema: users, sources, conversations, messages with tsvector, threads.

Revision ID: 001
Revises: None
Create Date: 2026-03-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Users
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("name", sa.String(255)),
        sa.Column("github_id", sa.String(100), unique=True),
        sa.Column("google_id", sa.String(100), unique=True),
        sa.Column("avatar_url", sa.Text),
        sa.Column("password_hash", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Sources
    op.create_table(
        "sources",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("source_type", sa.Text, nullable=False),
        sa.Column("file_path", sa.Text, nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("record_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("metadata", JSONB),
    )

    # Conversations
    op.create_table(
        "conversations",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("source_id", sa.Integer, sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("title", sa.Text),
        sa.Column("create_time", sa.Double),
        sa.Column("update_time", sa.Double),
        sa.Column("model", sa.Text),
        sa.Column("gizmo_id", sa.Text),
        sa.Column("message_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("has_branches", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("metadata", JSONB),
        sa.Column("source_type", sa.Text),
        sa.Column("project", sa.Text),
        sa.Column("tags", JSONB),
    )
    op.create_index("idx_conversations_user_id", "conversations", ["user_id"])
    op.create_index("idx_conversations_source", "conversations", ["source_id"])
    op.create_index("idx_conversations_source_type", "conversations", ["source_type"])
    op.create_index("idx_conversations_project", "conversations", ["project"])
    op.create_index("idx_conversations_create_time", "conversations", ["create_time"])

    # Messages (without search_vector — added via raw SQL for GENERATED column)
    op.create_table(
        "messages",
        sa.Column("id", sa.Text, nullable=False),
        sa.Column("conversation_id", sa.Text, sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("parent_id", sa.Text),
        sa.Column("role", sa.Text),
        sa.Column("content_type", sa.Text),
        sa.Column("content_text", sa.Text),
        sa.Column("raw_content", sa.Text),
        sa.Column("is_canonical", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("create_time", sa.Double),
        sa.Column("attachments", JSONB),
        sa.Column("metadata", JSONB),
        sa.PrimaryKeyConstraint("id", "conversation_id"),
    )
    op.create_index("idx_messages_conversation", "messages", ["conversation_id"])
    op.create_index("idx_messages_canonical", "messages", ["conversation_id", "is_canonical"])

    # Add tsvector generated column and GIN index via raw SQL
    op.execute(
        "ALTER TABLE messages ADD COLUMN search_vector tsvector "
        "GENERATED ALWAYS AS (to_tsvector('english', coalesce(content_text, ''))) STORED"
    )
    op.execute("CREATE INDEX idx_messages_search ON messages USING GIN(search_vector)")

    # Threads
    op.create_table(
        "threads",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("status", sa.Text, nullable=False, server_default="active"),
        sa.Column("tags", JSONB),
        sa.Column("create_time", sa.Double, nullable=False),
        sa.Column("update_time", sa.Double, nullable=False),
    )

    # Thread-Conversation join table
    op.create_table(
        "thread_conversations",
        sa.Column("thread_id", sa.Text, sa.ForeignKey("threads.id"), nullable=False),
        sa.Column("conversation_id", sa.Text, sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("note", sa.Text),
        sa.Column("added_time", sa.Double, nullable=False),
        sa.PrimaryKeyConstraint("thread_id", "conversation_id"),
    )
    op.create_index("idx_thread_conversations_thread", "thread_conversations", ["thread_id"])
    op.create_index("idx_thread_conversations_conversation", "thread_conversations", ["conversation_id"])


def downgrade() -> None:
    op.drop_table("thread_conversations")
    op.drop_table("threads")
    op.execute("DROP INDEX IF EXISTS idx_messages_search")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("sources")
    op.drop_table("users")
