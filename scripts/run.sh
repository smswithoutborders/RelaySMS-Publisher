#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "$SCRIPT_DIR/lib.sh"

# Export .env so the host, port and OTEL settings used below match the app's.
ENV_FILE="$SCRIPT_DIR/../.env"
if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

PYTHON="${PYTHON:-python3}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-16000}"
WORKERS="${WORKERS:-1}"
OTEL_WRAP="$SCRIPT_DIR/otel-wrap.sh"

log "Starting gRPC, FastAPI, Celery worker, Celery beat scheduler ..."

OTEL_SERVICE_NAME="relaysms-publisher-grpc" "$OTEL_WRAP" "$PYTHON" -u -m publisher.api.grpc &
GRPC_PID=$!

OTEL_SERVICE_NAME="relaysms-publisher-rest" "$OTEL_WRAP" "$PYTHON" -m uvicorn publisher.api.rest.app:app \
  --workers "$WORKERS" --host "$HOST" --port "$PORT" \
  --proxy-headers --forwarded-allow-ips "*" &
FASTAPI_PID=$!

OTEL_SERVICE_NAME="relaysms-publisher-worker" "$OTEL_WRAP" "$PYTHON" -m celery \
  -A publisher.tasks.celery_app:celery_app worker \
  --loglevel=info \
  --without-gossip \
  --without-mingle \
  --without-heartbeat &
CELERY_PID=$!

OTEL_SERVICE_NAME="relaysms-publisher-beat" "$OTEL_WRAP" "$PYTHON" -m celery \
  -A publisher.tasks.celery_app:celery_app beat \
  --loglevel=info &
BEAT_PID=$!

PIDS=("$GRPC_PID" "$FASTAPI_PID" "$CELERY_PID" "$BEAT_PID")

if [ "${SMTP_TRANSPORT_ENABLED:-false}" = "true" ]; then
  log "Starting SMTP listener ..."
  OTEL_SERVICE_NAME="relaysms-publisher-smtp" "$OTEL_WRAP" "$PYTHON" -u -m publisher.smtp &
  PIDS+=("$!")
fi

trap 'log "Shutting down ..."; kill "${PIDS[@]}" 2>/dev/null; wait' INT TERM

wait
