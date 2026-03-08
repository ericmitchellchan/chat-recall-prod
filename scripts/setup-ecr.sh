#!/bin/bash
set -euo pipefail

# ---------------------------------------------------------------------------
# Chat Recall — One-Time ECR Repository Setup
#
# Creates ECR repositories for the API and MCP services and configures
# a lifecycle policy to keep only the last 10 images.
#
# Usage:
#   ./scripts/setup-ecr.sh
# ---------------------------------------------------------------------------

AWS_REGION="us-west-2"
REPOS=("chatrecall-api" "chatrecall-mcp")

log()  { echo "[setup-ecr] $*"; }
fail() { echo "[setup-ecr] ERROR: $*" >&2; exit 1; }

LIFECYCLE_POLICY=$(cat <<'POLICY'
{
  "rules": [
    {
      "rulePriority": 1,
      "description": "Keep only the last 10 images",
      "selection": {
        "tagStatus": "any",
        "countType": "imageCountMoreThan",
        "countNumber": 10
      },
      "action": {
        "type": "expire"
      }
    }
  ]
}
POLICY
)

for REPO in "${REPOS[@]}"; do
  log "Creating ECR repository: ${REPO}..."
  REPO_URI=$(aws ecr create-repository \
    --repository-name "$REPO" \
    --region "$AWS_REGION" \
    --image-scanning-configuration scanOnPush=true \
    --query "repository.repositoryUri" \
    --output text 2>/dev/null) || {
      # Repository may already exist — fetch its URI instead
      REPO_URI=$(aws ecr describe-repositories \
        --repository-names "$REPO" \
        --region "$AWS_REGION" \
        --query "repositories[0].repositoryUri" \
        --output text)
      log "Repository ${REPO} already exists."
    }

  log "Setting lifecycle policy for ${REPO}..."
  aws ecr put-lifecycle-policy \
    --repository-name "$REPO" \
    --lifecycle-policy-text "$LIFECYCLE_POLICY" \
    --region "$AWS_REGION" \
    --no-cli-pager > /dev/null

  log "Repository URI: ${REPO_URI}"
  echo ""
done

log "ECR setup complete."
