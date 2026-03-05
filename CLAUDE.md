# Chat Recall Production Server

## Overview
Production MCP server for Chat Recall SaaS. Uses Postgres (not SQLite) with tsvector/GIN for full-text search. Multi-user with user_id isolation on all queries.

## Testing
```
python -m pytest tests/ -x -q --tb=short
```

## Conventions
- Async-first: all database operations are async (psycopg async)
- All queries must include user_id parameter for multi-tenant isolation
- Read existing code before modifying
- Run tests before declaring work complete
