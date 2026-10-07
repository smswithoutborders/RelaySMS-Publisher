#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "$SCRIPT_DIR/scripts/lib.sh"

INSTALL_DIR="$SCRIPT_DIR"

[ -f "$INSTALL_DIR/publisher/__main__.py" ] ||
  error "publisher/__main__.py not found under $INSTALL_DIR. Is RelaySMS Publisher installed there?"

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
Usage: $0 GROUP COMMAND [ARGS...]
       $0 env | shell

Runs 'python3 -m publisher' from $INSTALL_DIR as the service user
($SERVICE_USER), so the database, registries and adapter files keep the
right ownership.

Extra commands:
  env     Print the install dir, service user and the .env values the CLI uses
  shell   Open a shell as the service user with .env loaded and the venv on PATH

Examples:
  $0 creds create --username ops --administrator
  $0 platforms add https://github.com/example/adapter-repo.git
  $0 gateway-clients list
  $0 config check

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
  for var in AUTH_WEB_ORIGINS AUTH_SESSION_COOKIE_SECURE AUTH_SESSION_IDLE_MINUTES \
    AUTH_SESSION_MAX_HOURS PLATFORMS_GITHUB_ORGS PLATFORMS_ADAPTERS_DIR \
    PLATFORMS_ADAPTERS_VENV_DIR PLATFORMS_ADAPTERS_ASSETS_DIR; do
    echo "$var = $(read_env_var "$var" "$ENV_FILE")"
  done
}

main() {
  case "${1:-}" in
  "" | -h | --help | help)
    usage
    run_as_service_user "python3 -m publisher --help"
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
    run_as_service_user "python3 -m publisher $quoted_args"
    ;;
  esac
}

main "$@"
