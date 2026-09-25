#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-only

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/scripts/lib.sh"

INSTALL_DIR="$SCRIPT_DIR"

[ -f "$INSTALL_DIR/admin_users/cli.py" ] ||
  error "admin_users/cli.py not found under $INSTALL_DIR. Is RelaySMS Publisher installed there?"

ENV_FILE="$INSTALL_DIR/.env"
[ -f "$ENV_FILE" ] || error ".env not found at $ENV_FILE. Run install.sh or copy template.env first."

VENV_DIR="$INSTALL_DIR/venv"
[ -x "$VENV_DIR/bin/python3" ] ||
  error "Virtualenv not found at $VENV_DIR. Run install.sh or 'make build-setup' first."

INSTANCE_NAME="$(read_instance_name)"
SERVICE_USER="$(detect_service_user)"
CURRENT_USER="$(id -un)"

usage() {
  cat <<EOF
Usage: $0 <command> [args...]

Thin wrapper around 'python3 -m admin_users.cli' that:
  - runs from the correct install directory ($INSTALL_DIR)
  - loads environment variables from .env
  - always runs as the service user ($SERVICE_USER), so the database
    file never ends up with mismatched ownership

Commands (forwarded to admin_users.cli):
  create --email EMAIL               Create an admin. A strong password is
                                     generated and shown once.
  list                               List admins with status, last login and
                                     active session count.
  reset-password --email EMAIL       Generate a new password (shown once)
                                     and end the admin's sessions.
  disable --email EMAIL              Disable an admin and end their sessions.
  enable --email EMAIL               Re-enable a disabled admin.
  delete --email EMAIL [--yes]       Permanently delete an admin.
  revoke-sessions --email EMAIL      Log an admin out of every web session.

Extra commands:
  env                                Print resolved install dir, service
                                     user, and admin-auth-related .env values
  shell                              Open an interactive shell as the
                                     service user with .env loaded and the
                                     venv on PATH (useful for debugging)

Examples:
  $0 create --email admin@example.org
  $0 reset-password --email admin@example.org
EOF
}

cmd_env() {
  echo "Install dir   : $INSTALL_DIR"
  echo "Env file      : $ENV_FILE"
  echo "Service user  : $SERVICE_USER"
  echo "Current user  : $CURRENT_USER"
  echo "Venv          : $VENV_DIR"
  echo
  local var
  for var in ADMIN_WEB_ORIGINS ADMIN_SESSION_COOKIE_SAMESITE ADMIN_SESSION_COOKIE_SECURE \
    ADMIN_SESSION_COOKIE_DOMAIN ADMIN_SESSION_IDLE_MINUTES ADMIN_SESSION_MAX_HOURS; do
    echo "$var = $(read_env_var "$var" "$ENV_FILE")"
  done
}

main() {
  [ "$#" -eq 0 ] && {
    usage
    exit 1
  }

  case "$1" in
  -h | --help | help)
    usage
    ;;
  env)
    cmd_env
    ;;
  shell)
    log "Opening shell as '$SERVICE_USER' in $INSTALL_DIR ..."
    run_as_service_user "exec bash"
    ;;
  *)
    local args=("$@")
    printf -v quoted_args '%q ' "${args[@]}"
    run_as_service_user "python3 -m admin_users.cli $quoted_args"
    ;;
  esac
}

main "$@"
