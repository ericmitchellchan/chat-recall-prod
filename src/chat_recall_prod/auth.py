"""OAuth provider factory and user resolution for production MCP server.

In HTTP mode: GitHubProvider handles OAuth, resolve_user_id maps to Postgres users.
In stdio mode: No auth, user_id comes from RECALL_USER_ID env var or None.
"""

from __future__ import annotations

import logging
import os

from psycopg import AsyncConnection

from chat_recall_prod.db.queries import Database

logger = logging.getLogger(__name__)


def get_auth_provider():
    """Build a GitHubProvider from env vars, or return None for unauthenticated mode.

    Required env vars (all must be set together):
        GITHUB_CLIENT_ID     – GitHub OAuth App client ID
        GITHUB_CLIENT_SECRET – GitHub OAuth App client secret
        RECALL_BASE_URL      – Public URL of this server (e.g. https://recall.example.com)

    Optional:
        RECALL_JWT_SIGNING_KEY – Secret for signing JWTs (defaults to client_secret)
    """
    client_id = os.environ.get("GITHUB_CLIENT_ID", "")
    client_secret = os.environ.get("GITHUB_CLIENT_SECRET", "")
    base_url = os.environ.get("RECALL_BASE_URL", "")
    jwt_key = os.environ.get("RECALL_JWT_SIGNING_KEY", "")

    if not client_id:
        return None

    if not client_secret:
        logger.warning("GITHUB_CLIENT_ID is set but GITHUB_CLIENT_SECRET is missing — skipping auth")
        return None

    if not base_url:
        raise RuntimeError(
            "RECALL_BASE_URL is required when GITHUB_CLIENT_ID is set "
            "(e.g. https://recall.example.com)"
        )

    from fastmcp.server.auth.providers.github import GitHubProvider

    return GitHubProvider(
        client_id=client_id,
        client_secret=client_secret,
        base_url=base_url,
        jwt_signing_key=jwt_key or client_secret,
        allowed_client_redirect_uris=[
            "https://claude.ai/api/mcp/auth_callback",
        ],
        required_scopes=["read:user"],
    )


async def resolve_user_id(
    db: Database,
    conn: AsyncConnection,
    *,
    github_username: str,
    github_id: str | None = None,
    email: str | None = None,
    name: str | None = None,
    avatar_url: str | None = None,
) -> str:
    """Map a GitHub identity to a Postgres user UUID. Auto-provisions if new.

    Lookup order:
    1. By github_id (most reliable)
    2. By email (links existing account)
    3. Create new user (auto-provision)
    """
    # Try by github_id
    if github_id:
        user = await db.get_user_by_github_id(conn, github_id)
        if user:
            return user["id"]

    # Try by email
    if email:
        user = await db.get_user_by_email(conn, email)
        if user:
            # Link GitHub ID if not already set
            if github_id and not user.get("github_id"):
                await db.update_user(conn, user["id"], github_id=github_id)
                await conn.commit()
            return user["id"]

    # Auto-provision new user
    user = await db.create_user(
        conn,
        email=email or f"{github_username}@users.noreply.github.com",
        name=name or github_username,
        github_id=github_id,
        avatar_url=avatar_url,
    )
    await conn.commit()
    return user["id"]
