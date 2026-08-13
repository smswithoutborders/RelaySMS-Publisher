#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Runs the given command through OpenTelemetry auto-instrumentation if
# OTEL_EXPORTER_OTLP_ENDPOINT is set, otherwise runs it plain.
# See observability/README.md.
set -euo pipefail

if [ -n "${OTEL_EXPORTER_OTLP_ENDPOINT:-}" ]; then
  exec opentelemetry-instrument "$@"
else
  exec "$@"
fi
