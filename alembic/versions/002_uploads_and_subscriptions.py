"""Uploads and subscriptions tables for import tracking and Stripe billing.

Revision ID: 002
Revises: 001
Create Date: 2026-03-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Uploads — tracks import jobs (ChatGPT export files, etc.)
    op.create_table(
        "uploads",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("conversations_imported", sa.Integer, nullable=False, server_default="0"),
        sa.Column("messages_imported", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("idx_uploads_user_id", "uploads", ["user_id"])
    op.create_index("idx_uploads_status", "uploads", ["status"])

    # Subscriptions — Stripe billing state
    op.create_table(
        "subscriptions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), unique=True, nullable=False),
        sa.Column("stripe_customer_id", sa.String(255)),
        sa.Column("stripe_subscription_id", sa.String(255)),
        sa.Column("plan", sa.Text, nullable=False, server_default="free"),
        sa.Column("status", sa.Text, nullable=False, server_default="active"),
        sa.Column("current_period_end", sa.DateTime(timezone=True)),
        sa.Column("conversation_limit", sa.Integer, nullable=False, server_default="200"),
    )
    op.create_index("idx_subscriptions_stripe_customer", "subscriptions", ["stripe_customer_id"])


def downgrade() -> None:
    op.drop_table("subscriptions")
    op.drop_table("uploads")
