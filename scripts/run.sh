#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -Eeuo pipefail

PYTHON="${PYTHON:-python3}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-16000}"
WORKERS="${WORKERS:-1}"
OTEL_WRAP="$(dirname "$0")/otel-wrap.sh"

log() {
  echo "[$(date +'%Y-%m-%d %H:%M:%S')] [$1] $2"
}

on_err() { log ERROR "aborted at line $1 (last command: $2)"; }
trap 'on_err "$LINENO" "$BASH_COMMAND"' ERR

log INFO "Starting gRPC, FastAPI, Celery worker, Celery beat scheduler ..."

OTEL_SERVICE_NAME="relaysms-publisher-grpc" "$OTEL_WRAP" "$PYTHON" -u grpc_server.py &
GRPC_PID=$!

OTEL_SERVICE_NAME="relaysms-publisher-rest" "$OTEL_WRAP" "$PYTHON" -m uvicorn app:app \
  --workers "$WORKERS" --host "$HOST" --port "$PORT" \
  --proxy-headers --forwarded-allow-ips "*" &
FASTAPI_PID=$!

OTEL_SERVICE_NAME="relaysms-publisher-worker" "$OTEL_WRAP" "$PYTHON" -m celery \
  -A tasks.celery_app:celery_app worker \
  --loglevel=info \
  --without-gossip \
  --without-mingle \
  --without-heartbeat &
CELERY_PID=$!

OTEL_SERVICE_NAME="relaysms-publisher-beat" "$OTEL_WRAP" "$PYTHON" -m celery \
  -A tasks.celery_app:celery_app beat \
  --loglevel=info &
BEAT_PID=$!

PIDS=("$GRPC_PID" "$FASTAPI_PID" "$CELERY_PID" "$BEAT_PID")

if [ "${SMTP_TRANSPORT_ENABLED:-false}" = "true" ]; then
  log INFO "Starting SMTP listener ..."
  OTEL_SERVICE_NAME="relaysms-publisher-smtp" "$OTEL_WRAP" "$PYTHON" -u smtp_listener.py &
  PIDS+=("$!")
fi

trap 'log INFO "Shutting down ..."; kill "${PIDS[@]}" 2>/dev/null; wait' INT TERM

wait
