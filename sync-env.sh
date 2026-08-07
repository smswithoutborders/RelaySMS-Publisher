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

set -Eeuo pipefail

# Catches failures not already wrapped in error(), with line context.
on_err() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: aborted at line $1 (last command: $2)" >&2; }
trap 'on_err "$LINENO" "$BASH_COMMAND"' ERR

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${1:-$SCRIPT_DIR/.env}"
TEMPLATE_FILE="${2:-$SCRIPT_DIR/template.env}"

[ -f "$TEMPLATE_FILE" ] || {
  echo "Template not found: $TEMPLATE_FILE" >&2
  exit 1
}

if [ -e "$ENV_FILE" ]; then
  [ -w "$ENV_FILE" ] || {
    echo "No write permission on $ENV_FILE. Try: sudo $0 $*" >&2
    exit 1
  }
else
  [ -w "$(dirname "$ENV_FILE")" ] || {
    echo "No write permission in $(dirname "$ENV_FILE") to create $ENV_FILE. Try: sudo $0 $*" >&2
    exit 1
  }
  : >"$ENV_FILE"
fi

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
  BACKUP_FILE="$ENV_FILE.bak"
  cp -p "$ENV_FILE" "$BACKUP_FILE"
  printf '%s\n' "${env_lines[@]}" >"$ENV_FILE"
  echo "Added $added variable(s) to $ENV_FILE"
  echo "Previous file backed up to $BACKUP_FILE; delete it once you've confirmed the sync looks right."
fi
