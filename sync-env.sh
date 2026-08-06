#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-only
#
# Adds variables from template.env that are missing from .env, without
# touching any existing value. Safe to re-run any time template.env gains
# new fields.
#
# Each missing variable is inserted right after its section's comment
# header if that header already exists in .env; otherwise the variable
# (with its header, if any) is appended as a new block at the end.
#
# Usage: ./sync-env.sh [env-file] [template-file]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${1:-$SCRIPT_DIR/.env}"
TEMPLATE_FILE="${2:-$SCRIPT_DIR/template.env}"

[ -f "$TEMPLATE_FILE" ] || {
  echo "Template not found: $TEMPLATE_FILE" >&2
  exit 1
}
[ -f "$ENV_FILE" ] || : >"$ENV_FILE"

mapfile -t env_lines <"$ENV_FILE"

# Inserts $2 right after the line in env_lines matching $1 (exact text), or
# appends both (as a new block) if $1 is empty or not found.
insert_after_or_append() {
  local anchor="$1" new_line="$2" i
  if [ -n "$anchor" ]; then
    for i in "${!env_lines[@]}"; do
      if [ "${env_lines[$i]}" = "$anchor" ]; then
        env_lines=("${env_lines[@]:0:$((i + 1))}" "$new_line" "${env_lines[@]:$((i + 1))}")
        return
      fi
    done
    env_lines+=("" "$anchor" "$new_line")
    return
  fi
  env_lines+=("$new_line")
}

added=0
last_comment=""
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
  if printf '%s\n' "${env_lines[@]}" | grep -qE "^${key}[[:space:]]*="; then
    last_comment="$line"
    continue
  fi

  insert_after_or_append "$last_comment" "$line"
  echo "Added: $key"
  added=$((added + 1))
  last_comment="$line"
done <"$TEMPLATE_FILE"

if [ "$added" -eq 0 ]; then
  echo "Nothing to add; $ENV_FILE already has every variable from $TEMPLATE_FILE."
else
  printf '%s\n' "${env_lines[@]}" >"$ENV_FILE"
  echo "Added $added variable(s) to $ENV_FILE"
fi
