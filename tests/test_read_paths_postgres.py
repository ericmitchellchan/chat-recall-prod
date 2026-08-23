"""SWIT-24, first slice — the read paths, against a real Postgres.

Every counting query in search.py and queries.py ran on a connection carrying
dict_row (each function sets it on its own first line) and then read its COUNT
row positionally. dict rows do not index by position, so each was a
`KeyError: 0` on a live database — SearchEngine.search deterministically,
confirmed by probe before the fix. The deployed server predates whatever
introduced this, which is why prod search still works; this repo's main had
simply never been run against a real database until SWIT-23 added one.

Mocks are what kept it alive: the fixtures returned tuples, faithfully
asserting the broken assumption. These tests exist so the read paths can never
again pass green without a database having actually answered them.

Same activation as test_upsert_postgres.py — skipped unless TEST_DATABASE_URL
is set; see that module's docstring for the docker/alembic incantation.
"""

import os
import uuid
from unittest.mock import MagicMock

import pytest
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from chat_recall_prod.db.queries import Database
from chat_recall_prod.search import SearchEngine
from chat_recall_prod.writer import push_content

pytestmark = pytest.mark.postgres

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

skip_without_db = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL not set — see test_upsert_postgres's docstring",
)


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
    return str((await cur.fetchone())["id"])


@skip_without_db
async def test_search_finds_pushed_content(conn, db):
    """Push, then search — the workflow every user of this product runs.

    This exact sequence raised KeyError: 0 before the fix: push_content sets
    dict_row, search's own first line sets it again, and search's count row
    was then read as row[0].
    """
    user_id = await _make_user(conn)
    await push_content(
        db, conn, user_id,
        content="the quarterly cormorant census is complete",
        external_id="read-paths:1",
    )

    result = await SearchEngine().search(conn, user_id, "cormorant")

    assert result.total == 1
    assert len(result.hits) == 1
    assert "cormorant" in result.hits[0].snippet


@skip_without_db
async def test_search_scopes_to_the_searching_user(conn, db):
    user_id = await _make_user(conn)
    other = await _make_user(conn)
    await push_content(
        db, conn, other,
        content="a private note about ptarmigans",
        external_id="read-paths:2",
    )

    result = await SearchEngine().search(conn, user_id, "ptarmigans")

    assert result.total == 0


@skip_without_db
async def test_list_conversations_totals_and_pages(conn, db):
    user_id = await _make_user(conn)
    for i in range(3):
        await push_content(
            db, conn, user_id, content=f"note {i}", external_id=f"read-paths:list-{i}"
        )

    rows, total = await db.list_conversations(conn, user_id, page=1, page_size=2)

    assert total == 3
    assert len(rows) == 2


@skip_without_db
async def test_search_by_tags_counts_matches(conn, db):
    user_id = await _make_user(conn)
    await push_content(
        db, conn, user_id,
        content="tagged entry",
        tags=["slack", "channel:eng"],
        external_id="read-paths:tags",
    )
    await push_content(
        db, conn, user_id,
        content="untagged entry",
        external_id="read-paths:untagged",
    )

    result = await SearchEngine().search_by_tags(conn, user_id, ["slack"])

    assert result.total == 1
    assert result.conversations[0].tags == ["slack", "channel:eng"]


@skip_without_db
async def test_get_stats_counts_real_rows(conn, db):
    user_id = await _make_user(conn)
    await push_content(
        db, conn, user_id, content="stats fodder", external_id="read-paths:stats"
    )

    stats = await db.get_stats(conn, user_id)
    assert stats["conversations"] == 1
    assert stats["messages"] == 1

    engine_stats = await SearchEngine().get_stats(conn, user_id)
    assert engine_stats.conversations == 1
    assert engine_stats.messages == 1
