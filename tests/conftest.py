"""Shared test fixtures for chat-recall-prod."""

import pytest


@pytest.fixture
def sample_config():
    """Return a sample config dict for testing."""
    return {
        "DATABASE_URL": "postgresql://test:test@localhost:5432/chat_recall_test",
    }
