#!/bin/bash
set -euo pipefail

# ---------------------------------------------------------------------------
# Chat Recall — Run Alembic Migrations (Production)
#
# Usage:
#   DATABASE_URL="postgresql://..." ./scripts/migrate.sh
#
# If DATABASE_URL is not set, the script reads it from AWS SSM Parameter Store.
# ---------------------------------------------------------------------------

AWS_REGION="${AWS_REGION:-us-west-2}"
SSM_PARAM_NAME="/chatrecall/production/database-url"

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

log()  { echo "[migrate] $*"; }
fail() { echo "[migrate] ERROR: $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Resolve DATABASE_URL
# ---------------------------------------------------------------------------

if [[ -z "${DATABASE_URL:-}" ]]; then
  log "DATABASE_URL not set — reading from SSM Parameter Store (${SSM_PARAM_NAME})..."
  DATABASE_URL=$(aws ssm get-parameter \
    --name "$SSM_PARAM_NAME" \
    --with-decryption \
    --query "Parameter.Value" \
    --output text \
    --region "$AWS_REGION") || fail "Could not read DATABASE_URL from SSM."
fi

export DATABASE_URL

# ---------------------------------------------------------------------------
# Show current revision
# ---------------------------------------------------------------------------

log "Current Alembic revision:"
cd "$SCRIPT_DIR"
uv run alembic current 2>&1 | sed 's/^/  /'

# ---------------------------------------------------------------------------
# Run migrations
# ---------------------------------------------------------------------------

log "Running alembic upgrade head..."
MIGRATE_OUTPUT=$(uv run alembic upgrade head 2>&1)
echo "$MIGRATE_OUTPUT" | sed 's/^/  /'

# ---------------------------------------------------------------------------
# Report result
# ---------------------------------------------------------------------------

if echo "$MIGRATE_OUTPUT" | grep -q "Running upgrade"; then
  APPLIED=$(echo "$MIGRATE_OUTPUT" | grep "Running upgrade" | wc -l)
  log "Applied ${APPLIED} migration(s)."
else
  log "Database is already up to date — no migrations applied."
fi

log "New revision:"
uv run alembic current 2>&1 | sed 's/^/  /'

log "Done."
