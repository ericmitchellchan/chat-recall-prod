"""Shared test fixtures for chat-recall-prod."""

import asyncio
import sys

import pytest

# psycopg refuses to run async on Windows' default ProactorEventLoop, so the
# Postgres integration tests cannot even open a connection without this. No-op
# everywhere else, CI included — Linux already uses a selector loop.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture
def sample_config():
    """Return a sample config dict for testing."""
    return {
        "DATABASE_URL": "postgresql://test:test@localhost:5432/chat_recall_test",
    }
