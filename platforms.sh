#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-only
#
# Wrapper around `python3 -m platforms.cli` that removes the guesswork of
# running the platform adapter CLI correctly: it resolves the install
# directory, loads .env, runs as the correct service user (so file
# ownership never drifts), and uses the project venv automatically.

set -Eeuo pipefail

DEFAULT_INSTALL_DIR="/opt/relaysms/relaysms-publisher"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"; }
error() {
  echo "[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2
  exit 1
}
# Catches failures not already wrapped in error(), with line context.
on_err() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: aborted at line $1 (last command: $2)" >&2; }
trap 'on_err "$LINENO" "$BASH_COMMAND"' ERR

# Resolve INSTALL_DIR: prefer the production install path if it exists and
# looks like a real install, otherwise fall back to this script's own
# directory (development checkout).
if [ -f "$DEFAULT_INSTALL_DIR/platforms/cli.py" ]; then
  INSTALL_DIR="$DEFAULT_INSTALL_DIR"
else
  INSTALL_DIR="$SCRIPT_DIR"
fi

[ -f "$INSTALL_DIR/platforms/cli.py" ] ||
  error "platforms/cli.py not found under $INSTALL_DIR. Is RelaySMS Publisher installed there?"

ENV_FILE="$INSTALL_DIR/.env"
[ -f "$ENV_FILE" ] || error ".env not found at $ENV_FILE. Run install.sh or copy template.env first."

VENV_DIR="$INSTALL_DIR/venv"
[ -x "$VENV_DIR/bin/python3" ] ||
  error "Virtualenv not found at $VENV_DIR. Run install.sh or 'make build-setup' first."

# Resolve the service user: prefer the User= set in the installed systemd
# unit (source of truth after install.sh), fall back to the .env owner,
# then to whoever is running this script.
detect_service_user() {
  local unit="/etc/systemd/system/relaysms-publisher-rest.service"
  if [ -f "$unit" ]; then
    grep -E "^User=" "$unit" | head -1 | cut -d= -f2 && return
  fi
  if [ -f "$ENV_FILE" ]; then
    stat -c '%U' "$ENV_FILE" 2>/dev/null && return
  fi
  id -un
}

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

read_env_var() {
  local key="$1"
  grep -E "^${key}[[:space:]]*=" "$ENV_FILE" 2>/dev/null | tail -1 |
    sed 's/^[^=]*=//;s/^[[:space:]]*//;s/[[:space:]]*$//'
}

cmd_env() {
  echo "Install dir   : $INSTALL_DIR"
  echo "Env file      : $ENV_FILE"
  echo "Service user  : $SERVICE_USER"
  echo "Current user  : $CURRENT_USER"
  echo "Venv          : $VENV_DIR"
  echo
  echo "PLATFORMS_ADAPTERS_DIR        = $(read_env_var PLATFORMS_ADAPTERS_DIR)"
  echo "PLATFORMS_ADAPTERS_VENV_DIR   = $(read_env_var PLATFORMS_ADAPTERS_VENV_DIR)"
  echo "PLATFORMS_ADAPTERS_ASSETS_DIR = $(read_env_var PLATFORMS_ADAPTERS_ASSETS_DIR)"
  echo "PLATFORMS_REGISTRY_FILE       = $(read_env_var PLATFORMS_REGISTRY_FILE)"
}

# Runs a command line as SERVICE_USER, in INSTALL_DIR, with .env loaded and
# the venv on PATH. Works whether this script is invoked as root, via sudo,
# or directly as the service user (no unnecessary sudo prompt in that case).
run_as_service_user() {
  local inner_cmd="$1"
  local run_cmd="
    set -a
    # shellcheck disable=SC1090
    . '$ENV_FILE'
    set +a
    cd '$INSTALL_DIR'
    export PATH=\"$VENV_DIR/bin:\$PATH\"
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
