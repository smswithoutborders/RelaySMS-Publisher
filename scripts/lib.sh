#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-only
# Shared helpers sourced by the other scripts in this repo.

log() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"; }
error() {
  echo "[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2
  exit 1
}
on_err() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: aborted at line $1 (last command: $2)" >&2; }
trap 'on_err "$LINENO" "$BASH_COMMAND"' ERR

# Keeps output like generated credentials from getting lost in the log.
highlight() {
  local line
  echo
  echo "################################################################"
  for line in "$@"; do
    echo "# $line"
  done
  echo "################################################################"
  echo
}

# Excludes characters unsafe in SQL/AMQP, and can't start with - (CLI flag).
validate_identifier() {
  local name="$1" value="$2"
  [[ "$value" =~ ^[A-Za-z_][A-Za-z0-9_]{0,63}$ ]] ||
    error "$name must contain only letters, digits, and underscores, and start with a letter or underscore (got: '$value')"
}

# Excludes characters that could break out of SQL/sed/amqp:// contexts.
validate_secret() {
  local name="$1" value="$2"
  [[ "$value" =~ ^[A-Za-z0-9_.,!?+=~^-]+$ ]] ||
    error "$name contains unsupported characters (letters, digits, and _.,!?+=~^- only)"
}

# Rejects slashes (path traversal into nginx conf paths) and a leading -
# (could be mistaken for a certbot flag).
validate_hostname() {
  local name="$1" value="$2"
  [[ "$value" =~ ^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$ ]] ||
    error "$name must be a valid hostname (got: '$value')"
}

# Reads from the controlling terminal even when piped via `curl | sudo
# bash` (stdin is the script itself there). Falls back to $default if no
# tty is reachable. Mirrors install.sh's own copy, which can't source this
# file (must also run standalone via curl | sudo bash).
prompt() {
  local __resultvar="$1" question="> $2" default="${3:-}" reply=""
  if [ -t 0 ]; then
    read -r -p "$question" reply
  elif [ -r /dev/tty ]; then
    read -r -p "$question" reply </dev/tty || true
  fi
  printf -v "$__resultvar" '%s' "${reply:-$default}"
}

# True (0) if nothing is currently listening on the given local TCP port.
port_is_free() {
  local port="$1"
  ! ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE ":${port}\$"
}

# Mirrors install.sh's own copy, which can't source this file (must also
# run standalone via curl | sudo bash).
TARGET_UNIT_TEMPLATE="relaysms-publisher.target"
SERVICE_UNIT_TEMPLATES=(
  relaysms-publisher-rest.service
  relaysms-publisher-grpc.service
  relaysms-publisher-worker.service
  relaysms-publisher-beat.service
  relaysms-publisher-smtp.service
)
ALL_UNIT_TEMPLATES=("$TARGET_UNIT_TEMPLATE" "${SERVICE_UNIT_TEMPLATES[@]}")

# Expects INSTANCE_NAME to already be set by the caller (empty is fine).
unit_name_for() {
  local template="$1"
  if [ -z "${INSTANCE_NAME:-}" ]; then
    echo "$template"
  else
    echo "$template" | sed -E "s/^relaysms-publisher/relaysms-publisher-$INSTANCE_NAME/"
  fi
}

# Expects INSTALL_DIR to already be set by the caller.
read_instance_name() {
  [ -f "$INSTALL_DIR/.instance-name" ] && cat "$INSTALL_DIR/.instance-name" || true
}

# `|| true` on the grep stops a no-match from tripping pipefail.
read_env_var() {
  local key="$1" file="$2" val
  val=$( (grep -E "^(export[[:space:]]+)?${key}[[:space:]]*=" "$file" 2>/dev/null || true) |
    tail -1 | sed -E 's/^(export[[:space:]]+)?[^=]*=//; s/^[[:space:]]*//; s/[[:space:]]*$//')
  val="${val%\"}"
  val="${val#\"}"
  val="${val%\'}"
  val="${val#\'}"
  echo "$val"
}

# Prefers the installed unit's User=, then .env's owner, then whoever is
# running the script. Expects ENV_FILE and INSTANCE_NAME to already be set.
detect_service_user() {
  local unit="/etc/systemd/system/$(unit_name_for "relaysms-publisher-rest.service")"
  if [ -f "$unit" ]; then
    grep -E "^User=" "$unit" | head -1 | cut -d= -f2 && return
  fi
  if [ -f "$ENV_FILE" ]; then
    stat -c '%U' "$ENV_FILE" 2>/dev/null && return
  fi
  id -un
}

# Runs a command as SERVICE_USER, in INSTALL_DIR, with .env loaded and the
# venv on PATH. Expects INSTALL_DIR, ENV_FILE, VENV_DIR, SERVICE_USER, and
# CURRENT_USER to already be set by the caller.
run_as_service_user() {
  local inner_cmd="$1"
  local run_cmd="
    set -a
    # shellcheck disable=SC1090
    . '$ENV_FILE'
    set +a
    cd '$INSTALL_DIR'
    export PATH=\"$VENV_DIR/bin:$PATH\"
    $inner_cmd
  "

  if [ "$CURRENT_USER" = "$SERVICE_USER" ]; then
    bash -c "$run_cmd"
  elif [ "$EUID" -eq 0 ]; then
    sudo -u "$SERVICE_USER" bash -c "$run_cmd"
  else
    error "Must run as '$SERVICE_USER' or with sudo (current user: $CURRENT_USER)."
  fi
}
