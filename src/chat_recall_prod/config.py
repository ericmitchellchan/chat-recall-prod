"""Configuration for chat-recall-prod, loaded from environment variables."""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ProdConfig:
    """Production configuration loaded from environment variables."""

    database_url: str
    github_client_id: str = ""
    github_client_secret: str = ""
    recall_base_url: str = ""
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> ProdConfig:
        """Load configuration from environment variables."""
        database_url = os.environ.get("DATABASE_URL", "")
        if not database_url:
            logger.warning("DATABASE_URL not set — database operations will fail")

        return cls(
            database_url=database_url,
            github_client_id=os.environ.get("GITHUB_CLIENT_ID", ""),
            github_client_secret=os.environ.get("GITHUB_CLIENT_SECRET", ""),
            recall_base_url=os.environ.get("RECALL_BASE_URL", ""),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
        )
