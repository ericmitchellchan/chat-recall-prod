"""SWIT-25 — tag normalization against a real Postgres.

Two halves:
1. Round-trip: a push through the writer with mixed-case tags must be
   findable by lowercase tag containment (the server normalizes at the tool
   boundary; here we verify the query shape the DB actually answers).
2. Migration 005: pre-existing mixed-case rows get folded to lowercase,
   trimmed, deduped — and NULL/empty/already-clean rows survive untouched.

Same activation as test_upsert_postgres.py — skipped unless TEST_DATABASE_URL
is set; see that module's docstring for the docker/alembic incantation.
"""

import importlib.util
import json
import os
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from chat_recall_prod.db.queries import Database
from chat_recall_prod.search import SearchEngine
from chat_recall_prod.tags import normalize_tags
from chat_recall_prod.writer import push_content

pytestmark = pytest.mark.postgres

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

skip_without_db = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL not set — see test_upsert_postgres's docstring",
)


def _migration_sql() -> str:
    """Load _NORMALIZE_SQL from the 005 migration so the test exercises the
    exact SQL that will run on prod, not a copy that can drift."""
    path = Path(__file__).parent.parent / "alembic" / "versions" / "005_lowercase_tags.py"
    spec = importlib.util.spec_from_file_location("migration_005", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._NORMALIZE_SQL


@pytest.fixture
async def conn():
    connection = await AsyncConnection.connect(TEST_DATABASE_URL, autocommit=False)
    connection.row_factory = dict_row
    try:
        yield connection
    finally:
        await connection.rollback()
        await connection.close()


@pytest.fixture
def db():
    return Database(MagicMock())


async def _make_user(conn: AsyncConnection) -> str:
    cur = await conn.execute(
        "INSERT INTO users (email, name) VALUES (%s, %s) RETURNING id",
        (f"{uuid.uuid4()}@example.test", "Test User"),
    )
    row = await cur.fetchone()
    return str(row["id"])


@skip_without_db
async def test_normalized_push_found_by_lowercase_tag_search(conn, db):
    user_id = await _make_user(conn)
    # Server boundary normalizes before the writer sees them.
    tags = normalize_tags(["CAD-9999", "  Handoff "])
    await push_content(
        db, conn, user_id,
        content="checkpoint body", title="mixed-case tag push", tags=tags,
    )
    engine = SearchEngine()
    result = await engine.search_by_tags(conn, user_id, ["cad-9999", "handoff"])
    assert result.total == 1
    assert result.conversations[0].tags == ["cad-9999", "handoff"]


@skip_without_db
async def test_migration_005_folds_existing_rows(conn, db):
    user_id = await _make_user(conn)
    sql = _migration_sql()
    source_id = await db.insert_source(conn, "push", "push", metadata={"push": True})

    async def insert(conv_id: str, tags_json: str | None):
        await conn.execute(
            "INSERT INTO conversations (id, user_id, source_id, title, tags) "
            "VALUES (%s, %s, %s, %s, %s::jsonb)",
            (conv_id, user_id, source_id, "t", tags_json),
        )

    mixed = f"push-{uuid.uuid4()}"
    clean = f"push-{uuid.uuid4()}"
    nul = f"push-{uuid.uuid4()}"
    await insert(mixed, json.dumps(["CAD-1728", "cad-1728", "  Handoff ", ""]))
    await insert(clean, json.dumps(["already", "lower"]))
    await insert(nul, None)

    await conn.execute(sql.format(table="conversations"))

    async def tags_of(conv_id: str):
        cur = await conn.execute("SELECT tags FROM conversations WHERE id = %s", (conv_id,))
        row = await cur.fetchone()
        val = row["tags"]
        return json.loads(val) if isinstance(val, str) else val

    assert await tags_of(mixed) == ["cad-1728", "handoff"]
    assert await tags_of(clean) == ["already", "lower"]  # untouched
    assert await tags_of(nul) is None  # NULL stays NULL

    # Idempotent: second run changes nothing.
    await conn.execute(sql.format(table="conversations"))
    assert await tags_of(mixed) == ["cad-1728", "handoff"]
