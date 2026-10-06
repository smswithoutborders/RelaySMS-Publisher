#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -Eeuo pipefail

if [ -n "${OTEL_EXPORTER_OTLP_ENDPOINT:-}" ]; then
  exec opentelemetry-instrument "$@"
else
  exec "$@"
fi
