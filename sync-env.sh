#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Usage: ./sync-env.sh [env-file] [template-file]
#
# Adds template.env variables missing from .env, without touching existing
# values. Each is inserted after its section header if that header already
# exists in .env, otherwise appended as a new block.

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "$SCRIPT_DIR/scripts/lib.sh"

ENV_FILE="${1:-$SCRIPT_DIR/.env}"
TEMPLATE_FILE="${2:-$SCRIPT_DIR/template.env}"

# Inserts $2 after the env_lines entry for anchor $1: the same variable for a
# KEY=value anchor (its value may differ), the same text for a comment. A
# comment anchor that isn't there yet starts a new block.
insert_after_or_append() {
  local anchor="$1" new_line="$2" i
  for i in "${!env_lines[@]}"; do
    if [ -n "$anchor" ] && { [ "${env_lines[$i]}" = "$anchor" ] ||
      [[ "$anchor" != \#* && "${env_lines[$i]}" == "${anchor%%=*}="* ]]; }; then
      env_lines=("${env_lines[@]:0:$((i + 1))}" "$new_line" "${env_lines[@]:$((i + 1))}")
      return
    fi
  done
  [[ "$anchor" != \#* ]] || env_lines+=("" "$anchor")
  env_lines+=("$new_line")
}

main() {
  [ -f "$TEMPLATE_FILE" ] || error "Template not found: $TEMPLATE_FILE"
  if [ -e "$ENV_FILE" ]; then
    [ -w "$ENV_FILE" ] || error "No write permission on $ENV_FILE. Try: sudo $0 $*"
  else
    [ -w "$(dirname "$ENV_FILE")" ] ||
      error "No write permission in $(dirname "$ENV_FILE") to create $ENV_FILE. Try: sudo $0 $*"
    : >"$ENV_FILE"
  fi

  local env_lines line key added=0 last_comment=""
  mapfile -t env_lines <"$ENV_FILE"
  while IFS= read -r line; do
    if [[ "$line" =~ ^[[:space:]]*$ ]]; then
      last_comment=""
      continue
    fi
    if [[ "$line" =~ ^[[:space:]]*# ]]; then
      last_comment="$line"
      continue
    fi
    [[ "$line" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)= ]] || continue

    key="${BASH_REMATCH[1]}"
    if ! printf '%s\n' "${env_lines[@]}" | grep -qE "^${key}[[:space:]]*="; then
      insert_after_or_append "$last_comment" "$line"
      log "Added: $key"
      added=$((added + 1))
    fi
    last_comment="$line"
  done <"$TEMPLATE_FILE"

  if [ "$added" -eq 0 ]; then
    log "Nothing to add; $ENV_FILE already has every variable from $TEMPLATE_FILE."
    return
  fi
  cp -p "$ENV_FILE" "$ENV_FILE.bak"
  printf '%s\n' "${env_lines[@]}" >"$ENV_FILE"
  log "Added $added variable(s) to $ENV_FILE"
  log "Previous file backed up to $ENV_FILE.bak; delete it once you've confirmed the sync looks right."
}

main "$@"
