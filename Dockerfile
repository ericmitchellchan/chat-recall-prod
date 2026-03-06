FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-editable
COPY src/ src/
COPY alembic/ alembic/
COPY alembic.ini ./
RUN uv sync --frozen --no-dev
EXPOSE 8080
CMD ["uv", "run", "python", "-m", "chat_recall_prod.server", "--transport", "http", "--port", "8080"]
