"""Production server context — holds shared dependencies."""

from __future__ import annotations

from dataclasses import dataclass

from psycopg_pool import AsyncConnectionPool

from chat_recall_prod.config import ProdConfig
from chat_recall_prod.db.queries import Database
from chat_recall_prod.search import SearchEngine


@dataclass
class ProdContext:
    """Holds the database, search engine, pool, and config for the server.

    Created once at startup. Tools access it via the module-level getter.
    """

    pool: AsyncConnectionPool
    db: Database
    engine: SearchEngine
    config: ProdConfig
