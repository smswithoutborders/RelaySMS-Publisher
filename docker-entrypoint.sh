#!/bin/bash

set -e

export HOST="${HOST:-0.0.0.0}"
export PORT="${PORT:-80}"
export WORKERS="${WORKERS:-4}"
export GRPC_HOST="${GRPC_HOST:-0.0.0.0}"

python3 -m alembic upgrade head

exec ./scripts/run.sh
