"""Add analytics counter columns to users table.

Tracks total_conversations, total_messages, total_uploads, and last_upload_at
so the app can display usage stats without expensive COUNT queries.

Revision ID: 003
Revises: 002
Create Date: 2026-03-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("total_conversations", sa.Integer, nullable=False, server_default="0"))
    op.add_column("users", sa.Column("total_messages", sa.Integer, nullable=False, server_default="0"))
    op.add_column("users", sa.Column("total_uploads", sa.Integer, nullable=False, server_default="0"))
    op.add_column("users", sa.Column("last_upload_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("users", "last_upload_at")
    op.drop_column("users", "total_uploads")
    op.drop_column("users", "total_messages")
    op.drop_column("users", "total_conversations")
