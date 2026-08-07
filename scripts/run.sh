#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -Eeuo pipefail

PYTHON="${PYTHON:-python3}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-16000}"
WORKERS="${WORKERS:-1}"

log() {
  echo "[$(date +'%Y-%m-%d %H:%M:%S')] [$1] $2"
}

# Catches failures not already wrapped in error(), with line context.
on_err() { log ERROR "aborted at line $1 (last command: $2)"; }
trap 'on_err "$LINENO" "$BASH_COMMAND"' ERR

log INFO "Starting gRPC, FastAPI, Celery worker, Celery beat scheduler ..."

"$PYTHON" -u grpc_server.py &
GRPC_PID=$!

"$PYTHON" -m uvicorn app:app --workers "$WORKERS" --host "$HOST" --port "$PORT" \
  --proxy-headers --forwarded-allow-ips "*" &
FASTAPI_PID=$!

"$PYTHON" -m celery -A tasks.celery_app:celery_app worker \
  --loglevel=info \
  --without-gossip \
  --without-mingle \
  --without-heartbeat &
CELERY_PID=$!

"$PYTHON" -m celery -A tasks.celery_app:celery_app beat \
  --loglevel=info &
BEAT_PID=$!

PIDS=("$GRPC_PID" "$FASTAPI_PID" "$CELERY_PID" "$BEAT_PID")

if [ "${SMTP_TRANSPORT_ENABLED:-false}" = "true" ]; then
  log INFO "Starting SMTP listener ..."
  "$PYTHON" -u smtp_listener.py &
  PIDS+=("$!")
fi

trap 'log INFO "Shutting down ..."; kill "${PIDS[@]}" 2>/dev/null; wait' INT TERM

wait
