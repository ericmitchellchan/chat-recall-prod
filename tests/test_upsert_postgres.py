"""SWIT-23 — the push_content upsert, against a real Postgres.

The rest of this suite is mocks, which can prove the branching is right but
cannot prove the SQL is. Three claims in SWIT-22 rested on reading the DDL
rather than on watching Postgres behave:

  1. `search_vector` regenerates when a replace deletes and reinserts the row.
     If it does not, search returns the OLD text forever — the worst failure a
     recall tool has, because nothing errors and nothing looks broken.
  2. `IS NOT DISTINCT FROM` matches the NULL user_id that stdio mode writes.
  3. A replace leaves one row, not two. The whole point of the change.

Skipped unless TEST_DATABASE_URL is set, so a laptop without Docker runs the
suite exactly as fast as before:

    docker run -d --name chat-recall-test-pg \\
      -e POSTGRES_DB=chat_recall_test -e POSTGRES_USER=recall \\
      -e POSTGRES_PASSWORD=testpass -p 55432:5432 postgres:16-alpine
    DATABASE_URL=postgresql+psycopg://recall:testpass@localhost:55432/chat_recall_test \\
      python -m alembic upgrade head
    TEST_DATABASE_URL=postgresql://recall:testpass@localhost:55432/chat_recall_test \\
      python -m pytest tests/test_upsert_postgres.py
"""

import os
import uuid
from unittest.mock import MagicMock

import pytest
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from chat_recall_prod.db.queries import Database
from chat_recall_prod.writer import push_content

pytestmark = pytest.mark.postgres

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

skip_without_db = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL not set — see this module's docstring",
)


@pytest.fixture
async def conn():
    """A connection whose writes are rolled back, so tests cannot see each other."""
    connection = await AsyncConnection.connect(TEST_DATABASE_URL, autocommit=False)
    connection.row_factory = dict_row
    try:
        yield connection
    finally:
        await connection.rollback()
        await connection.close()


@pytest.fixture
def db():
    # Every Database method takes an explicit conn, so the pool it is
    # constructed with is never touched on these paths.
    return Database(MagicMock())


async def _make_user(conn: AsyncConnection) -> str:
    """conversations.user_id is a UUID FK to users.id, so a real row is needed."""
    email = f"{uuid.uuid4()}@example.test"
    cur = await conn.execute(
        "INSERT INTO users (email, name) VALUES (%s, %s) RETURNING id",
        (email, "Test User"),
    )
    return str((await cur.fetchone())["id"])


async def _row_count(conn: AsyncConnection, conv_id: str) -> int:
    cur = await conn.execute(
        "SELECT COUNT(*) AS n FROM conversations WHERE id = %s", (conv_id,)
    )
    return (await cur.fetchone())["n"]


# ── the replace itself ──────────────────────────────────────────────────────


@skip_without_db
async def test_replacing_leaves_one_row_with_the_new_content(conn, db):
    user_id = await _make_user(conn)

    first = await push_content(
        db, conn, user_id,
        content="the original thread body",
        external_id="C123:1700000000.1",
    )
    second = await push_content(
        db, conn, user_id,
        content="the thread body after more replies",
        external_id="C123:1700000000.1",
    )

    assert first["conversation_id"] == second["conversation_id"]
    assert first["replaced"] is False
    assert second["replaced"] is True
    assert await _row_count(conn, first["conversation_id"]) == 1

    messages = await db.get_messages(conn, user_id, first["conversation_id"])
    assert len(messages) == 1
    assert messages[0]["content_text"] == "the thread body after more replies"


@skip_without_db
async def test_replacing_keeps_create_time_and_moves_update_time(conn, db):
    """First-seen has to survive, or a refreshed thread reads as brand new."""
    user_id = await _make_user(conn)

    pushed = await push_content(
        db, conn, user_id, content="v1", external_id="k1"
    )
    conv_id = pushed["conversation_id"]
    before = await db.get_conversation(conn, user_id, conv_id)

    await push_content(db, conn, user_id, content="v2", external_id="k1")
    after = await db.get_conversation(conn, user_id, conv_id)

    assert after["create_time"] == before["create_time"]
    assert after["update_time"] >= before["update_time"]


# ── the assumption that could rot silently ──────────────────────────────────


@skip_without_db
async def test_full_text_search_follows_the_replacement(conn, db):
    """search_vector is GENERATED ALWAYS ... STORED, so reinserting the row is
    supposed to be all the index refresh a replace needs.

    This is the claim worth proving. If it is wrong, search keeps answering
    with content that is no longer stored, and nothing anywhere reports an
    error.
    """
    user_id = await _make_user(conn)

    await push_content(
        db, conn, user_id,
        content="discussion about the zeppelin proposal",
        external_id="C9:1.1",
    )
    pushed = await push_content(
        db, conn, user_id,
        content="discussion about the submarine proposal",
        external_id="C9:1.1",
    )
    conv_id = pushed["conversation_id"]

    async def matches(word: str) -> int:
        cur = await conn.execute(
            "SELECT COUNT(*) AS n FROM messages "
            "WHERE conversation_id = %s "
            "AND search_vector @@ plainto_tsquery(\'english\', %s)",
            (conv_id, word),
        )
        return (await cur.fetchone())["n"]

    assert await matches("submarine") == 1, "the replacement is not indexed"
    assert await matches("zeppelin") == 0, "the replaced text is still indexed"


# ── the predicate SWIT-22 changed ───────────────────────────────────────────


@skip_without_db
async def test_null_user_id_round_trips(conn, db):
    """Stdio mode writes user_id NULL when RECALL_USER_ID is unset.

    `user_id = NULL` is never true, so before IS NOT DISTINCT FROM these
    lookups matched nothing and a re-push silently kept the old content.
    """
    created = await push_content(
        db, conn, None, content="stdio content v1", external_id="local-1"
    )
    assert created["replaced"] is False

    fetched = await db.get_conversation(conn, None, created["conversation_id"])
    assert fetched is not None, "a NULL-user row could not find itself"

    replaced = await push_content(
        db, conn, None, content="stdio content v2", external_id="local-1"
    )
    assert replaced["replaced"] is True
    assert await _row_count(conn, created["conversation_id"]) == 1

    messages = await db.get_messages(conn, None, created["conversation_id"])
    assert len(messages) == 1, "the old message survived the replace"
    assert messages[0]["content_text"] == "stdio content v2"


# ── isolation ───────────────────────────────────────────────────────────────


@skip_without_db
async def test_two_users_sharing_an_external_id_do_not_collide(conn, db):
    """conversations.id is globally unique, not unique per user.

    With the user id outside the hash, the second writer would land on the
    first one's primary key and insert_conversation's ON CONFLICT DO NOTHING
    would drop their content into the first user's row.
    """
    mine = await _make_user(conn)
    theirs = await _make_user(conn)

    a = await push_content(db, conn, mine, content="my note", external_id="same")
    b = await push_content(db, conn, theirs, content="their note", external_id="same")

    assert a["conversation_id"] != b["conversation_id"]
    assert b["replaced"] is False, "their push replaced my row"

    a_messages = await db.get_messages(conn, mine, a["conversation_id"])
    assert a_messages[0]["content_text"] == "my note"


@skip_without_db
async def test_a_user_cannot_replace_another_users_entry(conn, db):
    """The upsert consults get_conversation, which is user-scoped. Someone
    else's id must read as absent, not as replaceable."""
    mine = await _make_user(conn)
    theirs = await _make_user(conn)

    a = await push_content(db, conn, mine, content="mine", external_id="k")
    seen = await db.get_conversation(conn, theirs, a["conversation_id"])

    assert seen is None


@skip_without_db
async def test_without_an_external_id_each_push_is_a_new_row(conn, db):
    """The pre-existing contract, unchanged."""
    user_id = await _make_user(conn)

    a = await push_content(db, conn, user_id, content="note")
    b = await push_content(db, conn, user_id, content="note")

    assert a["conversation_id"] != b["conversation_id"]
    assert a["replaced"] is False and b["replaced"] is False
