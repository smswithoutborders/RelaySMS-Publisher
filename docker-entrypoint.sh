#!/bin/bash

set -e

python3 -u grpc_server.py &
exec python3 -m uvicorn app:app \
    --host "${HOST:-0.0.0.0}" \
    --port "${PORT:-80}" \
    --workers "${WORKERS:-4}" \
    --proxy-headers \
    --forwarded-allow-ips "*"
