# Chat Recall — Production MCP Server

Postgres-backed, multi-user MCP server for Chat Recall SaaS.

## Setup

```bash
uv sync
export DATABASE_URL=postgresql://user:pass@localhost:5432/chat_recall
python -m chat_recall_prod.server
```

## Testing

```bash
python -m pytest tests/ -x -q --tb=short
```
