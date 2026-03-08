#!/bin/bash
set -euo pipefail

# ---------------------------------------------------------------------------
# Chat Recall — Deploy to ECS
#
# Usage:
#   ./scripts/deploy.sh api      # Deploy the API service only
#   ./scripts/deploy.sh mcp      # Deploy the MCP service only
#   ./scripts/deploy.sh all      # Deploy both services
# ---------------------------------------------------------------------------

AWS_REGION="us-west-2"
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REPO_API="chatrecall-api"
ECR_REPO_MCP="chatrecall-mcp"
ECS_CLUSTER="chatrecall"
ECS_SERVICE_API="chatrecall-api"
ECS_SERVICE_MCP="chatrecall-mcp"

# Paths to Dockerfiles (relative to this repo's parent directory)
API_CONTEXT="$(cd "$(dirname "$0")/../../chat-recall-api" && pwd)"
MCP_CONTEXT="$(cd "$(dirname "$0")/.." && pwd)"

IMAGE_TAG="${IMAGE_TAG:-$(git -C "$MCP_CONTEXT" rev-parse --short HEAD)}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

log()  { echo "[deploy] $*"; }
fail() { echo "[deploy] ERROR: $*" >&2; exit 1; }

ecr_login() {
  log "Authenticating with ECR..."
  aws ecr get-login-password --region "$AWS_REGION" \
    | docker login --username AWS --password-stdin \
        "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
}

build_and_push() {
  local service="$1"
  local context="$2"
  local ecr_repo="$3"
  local ecr_uri="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ecr_repo}"

  log "Building ${service} from ${context}..."
  docker build -t "${ecr_repo}:${IMAGE_TAG}" -t "${ecr_repo}:latest" "$context"

  log "Tagging ${service} for ECR..."
  docker tag "${ecr_repo}:${IMAGE_TAG}" "${ecr_uri}:${IMAGE_TAG}"
  docker tag "${ecr_repo}:latest"       "${ecr_uri}:latest"

  log "Pushing ${service} to ECR..."
  docker push "${ecr_uri}:${IMAGE_TAG}"
  docker push "${ecr_uri}:latest"

  log "${service} image pushed: ${ecr_uri}:${IMAGE_TAG}"
}

deploy_ecs_service() {
  local service="$1"
  local ecs_service="$2"

  log "Forcing new deployment for ECS service ${ecs_service}..."
  aws ecs update-service \
    --cluster "$ECS_CLUSTER" \
    --service "$ecs_service" \
    --force-new-deployment \
    --region "$AWS_REGION" \
    --no-cli-pager > /dev/null

  log "Waiting for ${ecs_service} to stabilize (this may take a few minutes)..."
  if aws ecs wait services-stable \
    --cluster "$ECS_CLUSTER" \
    --services "$ecs_service" \
    --region "$AWS_REGION"; then
    log "${service} deployment SUCCEEDED."
  else
    fail "${service} deployment FAILED — service did not stabilize."
  fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

SERVICE="${1:-}"

if [[ -z "$SERVICE" ]]; then
  fail "Usage: $0 {api|mcp|all}"
fi

ecr_login

case "$SERVICE" in
  api)
    build_and_push "api" "$API_CONTEXT" "$ECR_REPO_API"
    deploy_ecs_service "api" "$ECS_SERVICE_API"
    ;;
  mcp)
    build_and_push "mcp" "$MCP_CONTEXT" "$ECR_REPO_MCP"
    deploy_ecs_service "mcp" "$ECS_SERVICE_MCP"
    ;;
  all)
    build_and_push "api" "$API_CONTEXT" "$ECR_REPO_API"
    build_and_push "mcp" "$MCP_CONTEXT" "$ECR_REPO_MCP"
    deploy_ecs_service "api" "$ECS_SERVICE_API"
    deploy_ecs_service "mcp" "$ECS_SERVICE_MCP"
    ;;
  *)
    fail "Unknown service: ${SERVICE}. Use api, mcp, or all."
    ;;
esac

log "Done."
