#!/bin/bash

set -Ee

# Catches failures not already wrapped in error(), with line context.
on_err() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: aborted at line $1 (last command: $2)" >&2; }
trap 'on_err "$LINENO" "$BASH_COMMAND"' ERR

export HOST="${HOST:-0.0.0.0}"
export PORT="${PORT:-80}"
export WORKERS="${WORKERS:-4}"
export GRPC_HOST="${GRPC_HOST:-0.0.0.0}"

python3 -m alembic upgrade head

exec ./scripts/run.sh
