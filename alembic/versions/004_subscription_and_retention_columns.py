"""Add subscription status, trial, and retention columns to users table.

Supports billing lifecycle (trial → active → cancelled → deleted) and
the 30-day data retention grace period enforcement.

Revision ID: 004
Revises: 003
Create Date: 2026-03-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column(
        "subscription_status", sa.Text,
        nullable=False, server_default="none",
    ))
    op.add_column("users", sa.Column(
        "trial_ends_at", sa.DateTime(timezone=True),
    ))
    op.add_column("users", sa.Column(
        "cancelled_at", sa.DateTime(timezone=True),
    ))
    op.add_column("users", sa.Column(
        "retention_warned_at", sa.DateTime(timezone=True),
    ))
    op.create_index(
        "idx_users_subscription_status", "users", ["subscription_status"],
    )


def downgrade() -> None:
    op.drop_index("idx_users_subscription_status")
    op.drop_column("users", "retention_warned_at")
    op.drop_column("users", "cancelled_at")
    op.drop_column("users", "trial_ends_at")
    op.drop_column("users", "subscription_status")
