"""Test configuration loading."""

import os
from chat_recall_prod.config import ProdConfig


def test_config_from_env(monkeypatch):
    """Config loads DATABASE_URL from environment."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/testdb")
    config = ProdConfig.from_env()
    assert config.database_url == "postgresql://test:test@localhost/testdb"


def test_config_defaults(monkeypatch):
    """Config handles missing env vars gracefully."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    config = ProdConfig.from_env()
    assert config.database_url == ""
    assert config.log_level == "INFO"
