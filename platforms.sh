#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-only

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/scripts/lib.sh"

INSTALL_DIR="$SCRIPT_DIR"

[ -f "$INSTALL_DIR/platforms/cli.py" ] ||
  error "platforms/cli.py not found under $INSTALL_DIR. Is RelaySMS Publisher installed there?"

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

Thin wrapper around 'python3 -m platforms.cli' that:
  - runs from the correct install directory ($INSTALL_DIR)
  - loads environment variables from .env
  - always runs as the service user ($SERVICE_USER), so adapter
    files and the registry never end up with mismatched ownership

Commands (forwarded to platforms.cli):
  add <GITHUB_URL>                  Add an adapter from a GitHub repository
  remove <NAME> [--proto-id ID] [--cat-id ID]
                                     Remove an adapter
  update [NAME] [--proto-id ID] [--cat-id ID] [--install]
                                     Update one or all adapters
  list [--name NAME] [--proto-id ID] [--cat-id ID]
                                     List registered adapters
  recover                            Rebuild the registry from disk
  exec <NAME> [--proto-id ID] [--cat-id ID] -- <ARGS...>
                                     Run an adapter's own admin cli.py (if it
                                     has one) inside its own venv. Put '--'
                                     before the adapter's own arguments.

Extra commands:
  env                                Print resolved install dir, service
                                     user, and platform-related .env values
  shell                              Open an interactive shell as the
                                     service user with .env loaded and the
                                     venv on PATH (useful for debugging)

Examples:
  $0 add https://github.com/example/adapter-repo.git
  $0 remove gmail
  $0 update --install
  $0 list
  $0 exec mastodon -- register -i
EOF
}

cmd_env() {
  echo "Install dir   : $INSTALL_DIR"
  echo "Env file      : $ENV_FILE"
  echo "Service user  : $SERVICE_USER"
  echo "Current user  : $CURRENT_USER"
  echo "Venv          : $VENV_DIR"
  echo
  echo "PLATFORMS_ADAPTERS_DIR        = $(read_env_var PLATFORMS_ADAPTERS_DIR "$ENV_FILE")"
  echo "PLATFORMS_ADAPTERS_VENV_DIR   = $(read_env_var PLATFORMS_ADAPTERS_VENV_DIR "$ENV_FILE")"
  echo "PLATFORMS_ADAPTERS_ASSETS_DIR = $(read_env_var PLATFORMS_ADAPTERS_ASSETS_DIR "$ENV_FILE")"
  echo "PLATFORMS_REGISTRY_FILE       = $(read_env_var PLATFORMS_REGISTRY_FILE "$ENV_FILE")"
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
    run_as_service_user "python3 -m platforms.cli $quoted_args"
    ;;
  esac
}

main "$@"
