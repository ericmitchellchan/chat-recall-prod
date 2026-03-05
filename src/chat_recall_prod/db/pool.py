"""Async connection pool for Postgres via psycopg."""

import os

from psycopg_pool import AsyncConnectionPool

_pool: AsyncConnectionPool | None = None


async def init_pool(database_url: str | None = None, min_size: int = 2, max_size: int = 10) -> AsyncConnectionPool:
    """Initialize the global async connection pool."""
    global _pool
    if _pool is not None:
        return _pool

    url = database_url or os.environ.get("DATABASE_URL", "")
    if not url:
        raise ValueError("DATABASE_URL is required")

    _pool = AsyncConnectionPool(conninfo=url, min_size=min_size, max_size=max_size, open=False)
    await _pool.open()
    return _pool


def get_pool() -> AsyncConnectionPool:
    """Return the global connection pool. Raises if not initialized."""
    if _pool is None:
        raise RuntimeError("Connection pool not initialized. Call init_pool() first.")
    return _pool


async def close_pool() -> None:
    """Close the global connection pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
