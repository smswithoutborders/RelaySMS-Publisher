#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-only

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/scripts/lib.sh"

INSTALL_DIR="$SCRIPT_DIR"

[ -f "$INSTALL_DIR/creds/cli.py" ] ||
  error "creds/cli.py not found under $INSTALL_DIR. Is RelaySMS Publisher installed there?"

ENV_FILE="$INSTALL_DIR/.env"
[ -f "$ENV_FILE" ] || error ".env not found at $ENV_FILE. Run install.sh or copy template.env first."

VENV_DIR="$INSTALL_DIR/venv"
[ -x "$VENV_DIR/bin/python3" ] ||
  error "Virtualenv not found at $VENV_DIR. Run install.sh, or see Development in README.md."

INSTANCE_NAME="$(read_instance_name)"
SERVICE_USER="$(detect_service_user)"
CURRENT_USER="$(id -un)"

usage() {
  cat <<EOF
Usage: $0 <command> [args...]

Thin wrapper around 'python3 -m creds.cli' that:
  - runs from the correct install directory ($INSTALL_DIR)
  - loads environment variables from .env
  - always runs as the service user ($SERVICE_USER), so the database
    file never ends up with mismatched ownership

Commands (forwarded to creds.cli):
  scopes                             List the available scopes.
  create --username NAME SCOPES      Create a credential. A strong password
                                     is generated and shown once.
  list                               List credentials with status, scopes,
                                     last login and active session count.
  set-scopes --username NAME SCOPES  Replace a credential's scopes.
  reset-password --username NAME     Generate a new password (shown once)
                                     and end the credential's sessions.
  disable --username NAME            Disable a credential and end its
                                     sessions.
  enable --username NAME             Re-enable a disabled credential.
  delete --username NAME [--yes]     Permanently delete a credential.
  revoke-sessions --username NAME    Log a credential out of every web
                                     session.

  SCOPES is --scope SCOPE (repeatable) or --administrator for every scope.

Extra commands:
  env                                Print resolved install dir, service
                                     user, and auth-related .env values
  shell                              Open an interactive shell as the
                                     service user with .env loaded and the
                                     venv on PATH (useful for debugging)

Examples:
  $0 create --username ops --administrator
  $0 create --username analyst --scope stats:publications:read
  $0 set-scopes --username analyst --scope stats:publications:read --scope stats:publications:reasons
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
  for var in AUTH_WEB_ORIGINS AUTH_SESSION_COOKIE_SECURE \
    AUTH_SESSION_IDLE_MINUTES AUTH_SESSION_MAX_HOURS PLATFORMS_GITHUB_ORGS; do
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
    run_service_shell
    ;;
  *)
    local args=("$@")
    printf -v quoted_args '%q ' "${args[@]}"
    run_as_service_user "python3 -m creds.cli $quoted_args"
    ;;
  esac
}

main "$@"
