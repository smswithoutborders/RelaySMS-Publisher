#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Adds template.env variables missing from .env, without touching existing
# values. Each goes in with its whole comment block, after the variable before
# it in the template. The first variable of a block goes after its section
# header if .env has it, otherwise at the end as a new block. With --prune,
# variables the template lacks are removed too. The changes are printed as a
# unified diff and written only once confirmed.

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "$SCRIPT_DIR/scripts/lib.sh"

ENV_FILE="$SCRIPT_DIR/.env"
TEMPLATE_FILE="$SCRIPT_DIR/template.env"
DRY_RUN=0
ASSUME_YES=0
PRUNE=0

usage() {
  cat <<'USAGE'
Usage: sync-env.sh [OPTIONS] [ENV_FILE] [TEMPLATE_FILE]

  ENV_FILE       File to sync (default: .env next to this script)
  TEMPLATE_FILE  File to sync it with (default: template.env next to this script)
  --prune        Also remove variables TEMPLATE_FILE doesn't have
  --dry-run      Print the changes without writing anything
  -y, --yes      Write the changes without asking for confirmation
  -h, --help     Show this help and exit
USAGE
}

parse_args() {
  local positional=()
  while [ $# -gt 0 ]; do
    case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --prune)
      PRUNE=1
      shift
      ;;
    -y | --yes)
      ASSUME_YES=1
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    -*)
      usage
      error "Unknown option: $1"
      ;;
    *)
      positional+=("$1")
      shift
      ;;
    esac
  done
  [ "${#positional[@]}" -le 2 ] || {
    usage
    error "Too many arguments"
  }
  ENV_FILE="${positional[0]:-$ENV_FILE}"
  TEMPLATE_FILE="${positional[1]:-$TEMPLATE_FILE}"
}

# Prints the env_lines index of the line setting $1, or nothing.
find_key() {
  local i
  for i in "${!env_lines[@]}"; do
    if [[ "${env_lines[i]}" =~ ^[[:space:]]*(export[[:space:]]+)?$1[[:space:]]*= ]]; then
      echo "$i"
      return
    fi
  done
}

# True if env_lines holds the remaining arguments starting at index $1.
lines_match_at() {
  local at="$1" want j
  shift
  want=("$@")
  ((at + ${#want[@]} <= ${#env_lines[@]})) || return 1
  for ((j = 0; j < ${#want[@]}; j++)); do
    [ "${env_lines[at + j]}" = "${want[j]}" ] || return 1
  done
}

# Prints the env_lines index of the last line of the first run matching the
# arguments, or nothing.
find_lines() {
  local i
  for ((i = 0; i + $# <= ${#env_lines[@]}; i++)); do
    if lines_match_at "$i" "$@"; then
      echo $((i + $# - 1))
      return
    fi
  done
}

# Inserts the remaining arguments into env_lines at index $1.
insert_at() {
  local at="$1"
  shift
  env_lines=("${env_lines[@]:0:at}" "$@" "${env_lines[@]:at}")
}

# Removes each env_lines line setting a variable the template lacks, with the
# comments right above it that the template lacks too. Sets removed to the count.
prune_env_lines() {
  local kept=() line just_dropped=0
  for line in "${env_lines[@]}"; do
    if [[ "$line" =~ ^[[:space:]]*(export[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*= ]] &&
      [ -z "${template_keys["${BASH_REMATCH[2]}"]:-}" ]; then
      while [ "${#kept[@]}" -gt 0 ] && [[ "${kept[-1]}" =~ ^[[:space:]]*# ]] &&
        [ -z "${template_comments["${kept[-1]}"]:-}" ]; do
        unset 'kept[-1]'
      done
      removed=$((removed + 1))
      just_dropped=1
      continue
    fi
    # Don't leave two blank lines where a whole block went.
    if [ "$just_dropped" -eq 1 ] && [[ "$line" =~ ^[[:space:]]*$ ]] &&
      { [ "${#kept[@]}" -eq 0 ] || [[ "${kept[-1]}" =~ ^[[:space:]]*$ ]]; }; then
      continue
    fi
    kept+=("$line")
    just_dropped=0
  done
  while [ "${#kept[@]}" -gt 0 ] && [[ "${kept[-1]}" =~ ^[[:space:]]*$ ]]; do
    unset 'kept[-1]'
  done
  env_lines=("${kept[@]}")
}

main() {
  parse_args "$@"
  [ -f "$TEMPLATE_FILE" ] || error "Template not found: $TEMPLATE_FILE"
  if [ "$DRY_RUN" -eq 0 ]; then
    if [ -e "$ENV_FILE" ]; then
      [ -w "$ENV_FILE" ] || error "No write permission on $ENV_FILE. Try: sudo $0 $*"
    else
      [ -w "$(dirname "$ENV_FILE")" ] ||
        error "No write permission in $(dirname "$ENV_FILE") to create $ENV_FILE. Try: sudo $0 $*"
    fi
  fi

  local env_lines=() line key added=0 removed=0 current="$ENV_FILE"
  local comments=() prev_key="" at answer
  local -A template_keys=() template_comments=()
  # ENV_FILE may not exist yet: it is only created once the changes are confirmed.
  [ -e "$ENV_FILE" ] || current=/dev/null
  mapfile -t env_lines <"$current"
  while IFS= read -r line; do
    if [[ "$line" =~ ^[[:space:]]*$ ]]; then
      comments=()
      prev_key=""
      continue
    fi
    if [[ "$line" =~ ^[[:space:]]*# ]]; then
      comments+=("$line")
      template_comments["$line"]=1
      # Commented-out variables like "# CELERY_REDIS_URL=..." are optional, not unused.
      [[ ! "$line" =~ ^[[:space:]]*#[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)= ]] ||
        template_keys["${BASH_REMATCH[1]}"]=1
      continue
    fi
    [[ "$line" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)= ]] || continue

    key="${BASH_REMATCH[1]}"
    template_keys["$key"]=1
    if [ -z "$(find_key "$key")" ]; then
      at=""
      [ -z "$prev_key" ] || at="$(find_key "$prev_key")"
      if [ -n "$at" ]; then
        at=$((at + 1))
        if lines_match_at "$at" "${comments[@]}"; then
          insert_at $((at + ${#comments[@]})) "$line"
        else
          insert_at "$at" "${comments[@]}" "$line"
        fi
      else
        [ "${#comments[@]}" -eq 0 ] || at="$(find_lines "${comments[@]}")"
        if [ -n "$at" ]; then
          insert_at $((at + 1)) "$line"
        else
          [ "${#env_lines[@]}" -eq 0 ] || [ -z "${env_lines[-1]}" ] || env_lines+=("")
          env_lines+=("${comments[@]}" "$line")
        fi
      fi
      added=$((added + 1))
    fi
    comments=()
    prev_key="$key"
  done <"$TEMPLATE_FILE"

  [ "$PRUNE" -eq 0 ] || prune_env_lines
  if [ "$added" -eq 0 ] && [ "$removed" -eq 0 ]; then
    log "Nothing to change: $ENV_FILE matches the variables in $TEMPLATE_FILE."
    return
  fi
  local name color=never changes="$added variable(s) added"
  [ "$PRUNE" -eq 0 ] || changes+=", $removed removed"
  name="$(basename "$ENV_FILE")"
  # lib.sh sets _grn only when stdout takes colors.
  [ -z "$_grn" ] || color=always
  # diff exits 1 when the files differ, which is expected here.
  diff -u --color="$color" --label "a/$name" --label "b/$name" \
    "$current" <(printf '%s\n' "${env_lines[@]}") || true

  if [ "$DRY_RUN" -eq 1 ]; then
    log "Dry run: $ENV_FILE left unchanged ($changes)."
    return
  fi
  if [ "$ASSUME_YES" -eq 0 ]; then
    # With no terminal to answer, prompt falls back to "n" and nothing is written.
    prompt answer "Write these changes to $ENV_FILE ($changes)? [y/N] " "n"
    case "$answer" in
    y | Y | yes | YES) ;;
    *)
      log "Aborted: $ENV_FILE left unchanged."
      return
      ;;
    esac
  fi
  [ "$current" = /dev/null ] || cp -p "$ENV_FILE" "$ENV_FILE.bak"
  printf '%s\n' "${env_lines[@]}" >"$ENV_FILE"
  log "Updated $ENV_FILE ($changes)."
  [ "$current" = /dev/null ] ||
    log "Previous file backed up to $ENV_FILE.bak. Delete it once you've confirmed the sync looks right."
}

main "$@"
