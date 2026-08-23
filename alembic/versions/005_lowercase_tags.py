"""Normalize existing tags to lowercase (trim + dedupe) in conversations and threads.

Tags are matched with exact JSONB containment, so `CAD-1728` and `cad-1728`
were distinct tags and tag search silently missed rows. The application now
normalizes tags at every write and query boundary (see chat_recall_prod.tags);
this migration folds pre-existing rows into the same shape.

Downgrade is a no-op: the original casing is not preserved anywhere, and
lowercased tags remain valid under the old code.

Revision ID: 005
Revises: 004
Create Date: 2026-08-22
"""

from typing import Sequence, Union

from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# jsonb_agg has no order guarantee under DISTINCT, so dedupe via a subquery
# that keeps the first occurrence's position — tag order is not load-bearing,
# but stable output makes the migration idempotent and diffable.
_NORMALIZE_SQL = """
UPDATE {table}
SET tags = COALESCE(
    (
        SELECT jsonb_agg(norm ORDER BY first_pos)
        FROM (
            SELECT MIN(ord) AS first_pos, norm
            FROM (
                SELECT ordinality AS ord, lower(btrim(t)) AS norm
                FROM jsonb_array_elements_text(tags) WITH ORDINALITY AS e(t, ordinality)
            ) AS elems
            WHERE norm <> ''
            GROUP BY norm
        ) AS deduped
    ),
    '[]'::jsonb
)
WHERE tags IS NOT NULL
  AND jsonb_typeof(tags) = 'array'
  AND EXISTS (
      SELECT 1 FROM jsonb_array_elements_text(tags) AS e(t)
      WHERE t <> lower(btrim(t)) OR t = ''
  )
"""


def upgrade() -> None:
    op.execute(_NORMALIZE_SQL.format(table="conversations"))
    op.execute(_NORMALIZE_SQL.format(table="threads"))


def downgrade() -> None:
    # Original casing is not recoverable; lowercase tags are valid either way.
    pass
