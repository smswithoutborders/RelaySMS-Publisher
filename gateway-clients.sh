#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-only

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/scripts/lib.sh"

INSTALL_DIR="$SCRIPT_DIR"

[ -f "$INSTALL_DIR/gateway_clients/cli.py" ] ||
  error "gateway_clients/cli.py not found under $INSTALL_DIR. Is RelaySMS Publisher installed there?"

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

Thin wrapper around 'python3 -m gateway_clients.cli' that:
  - runs from the correct install directory ($INSTALL_DIR)
  - loads environment variables from .env
  - always runs as the service user ($SERVICE_USER), so the registry
    file never ends up with mismatched ownership

Commands (forwarded to gateway_clients.cli):
  create --msisdn MSISDN --protocols PROTOCOLS
                                     Register a gateway client. Country,
                                     operator, and PLMN code are resolved
                                     automatically from the MSISDN.
  list [--msisdn MSISDN] [--country COUNTRY] [--operator OPERATOR]
                                     List registered gateway clients.
  update <MSISDN> [--country COUNTRY] [--operator OPERATOR] [--protocols PROTOCOLS]
                                     Update a gateway client.
  delete <MSISDN>                    Remove a gateway client.
  countries                          List unique countries in the registry.
  operators --country COUNTRY        List unique operators for a country.
  mcc-mnc list [--country-code CC] [--network NAME]
                                     Inspect the PLMN lookup table.
  mcc-mnc add-override --mcc MCC --mnc MNC --country-code CC --network NAME --country COUNTRY [--iso ISO]
                                     Add/replace a PLMN override entry.
  mcc-mnc remove-override --mcc MCC --mnc MNC
                                     Remove a PLMN override entry.

Extra commands:
  env                                Print resolved install dir, service
                                     user, and gateway-client-related .env
                                     values
  shell                              Open an interactive shell as the
                                     service user with .env loaded and the
                                     venv on PATH (useful for debugging)

Examples:
  $0 create --msisdn +237670000000 --protocols https
  $0 list --country Cameroon
  $0 mcc-mnc add-override --mcc 624 --mnc 01 --country-code 237 --network MTN --country Cameroon
EOF
}

cmd_env() {
  echo "Install dir   : $INSTALL_DIR"
  echo "Env file      : $ENV_FILE"
  echo "Service user  : $SERVICE_USER"
  echo "Current user  : $CURRENT_USER"
  echo "Venv          : $VENV_DIR"
  echo
  echo "GATEWAY_CLIENTS_REGISTRY_FILE = $(read_env_var GATEWAY_CLIENTS_REGISTRY_FILE "$ENV_FILE")"
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
    run_as_service_user "python3 -m gateway_clients.cli $quoted_args"
    ;;
  esac
}

main "$@"
