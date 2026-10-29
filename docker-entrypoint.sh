#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "$SCRIPT_DIR/scripts/lib.sh"

export HOST="${HOST:-0.0.0.0}"
export PORT="${PORT:-80}"
export WORKERS="${WORKERS:-4}"
export GRPC_HOST="${GRPC_HOST:-0.0.0.0}"

python3 -m alembic upgrade head

exec "$SCRIPT_DIR/scripts/run.sh"
