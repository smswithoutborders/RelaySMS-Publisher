#!/bin/bash

set -Eeuo pipefail

INSTALL_DIR="/opt/relaysms/relaysms-publisher"
CARGO_BIN="$HOME/.cargo/bin"

TARGET_UNIT="relaysms-publisher.target"
SERVICE_UNITS=(
  relaysms-publisher-rest.service
  relaysms-publisher-grpc.service
  relaysms-publisher-worker.service
  relaysms-publisher-beat.service
  relaysms-publisher-smtp.service
)
ALL_UNITS=("$TARGET_UNIT" "${SERVICE_UNITS[@]}")

log() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"; }
error() {
  echo "[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2
  exit 1
}
# Catches failures not already wrapped in error(), with line context.
on_err() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: aborted at line $1 (last command: $2)" >&2; }
trap 'on_err "$LINENO" "$BASH_COMMAND"' ERR

check_sudo() { [ "$EUID" -eq 0 ] || error "Run with sudo"; }

detect_service_user() {
  local unit="/etc/systemd/system/relaysms-publisher-rest.service"
  grep -E "^User=" "$unit" 2>/dev/null | head -1 | cut -d= -f2
}

read_env_var() {
  local key="$1" file="$INSTALL_DIR/.env"
  grep -E "^${key}[[:space:]]*=" "$file" 2>/dev/null | tail -1 |
    sed 's/^[^=]*=//;s/^[[:space:]]*//;s/[[:space:]]*$//'
}

# git pull doesn't fix ownership for directories .env references that were
# added since the last install.sh run. Re-apply it here too.
sync_app_directories() {
  local service_user
  service_user="$(detect_service_user)"
  [ -n "$service_user" ] || return

  local dirs=(
    "$(dirname "$(read_env_var SQLITE_DATABASE_PATH)")"
    "$(dirname "$(read_env_var CELERY_BROKER_DB_PATH)")"
    "$(dirname "$(read_env_var CELERY_RESULT_DB_PATH)")"
    "$(dirname "$(read_env_var CELERY_BEAT_SCHEDULE_PATH)")"
    "$(read_env_var PLATFORMS_ADAPTERS_DIR)"
    "$(read_env_var PLATFORMS_ADAPTERS_VENV_DIR)"
    "$(read_env_var PLATFORMS_ADAPTERS_ASSETS_DIR)"
    "$(dirname "$(read_env_var PLATFORMS_REGISTRY_FILE)")"
    "$(dirname "$(read_env_var GATEWAY_CLIENTS_REGISTRY_FILE)")"
  )

  local dir
  for dir in "${dirs[@]}"; do
    [ -n "$dir" ] && [ "$dir" != "." ] || continue
    [[ "$dir" = /* ]] || dir="$INSTALL_DIR/$dir"
    mkdir -p "$dir"
    chown "$service_user:" "$dir"
    chmod 750 "$dir"
  done
}

cmd_start() {
  check_sudo
  systemctl start "$TARGET_UNIT"
  log "Services started"
}

cmd_stop() {
  check_sudo
  local svc
  for svc in "${SERVICE_UNITS[@]}"; do
    systemctl stop "$svc"
  done
  systemctl stop "$TARGET_UNIT"
  log "Services stopped"
}

cmd_restart() {
  check_sudo
  local svc
  for svc in "${SERVICE_UNITS[@]}"; do
    systemctl restart "$svc"
  done
  log "Services restarted"
}

cmd_status() {
  systemctl status "${SERVICE_UNITS[@]}" || true
}

cmd_logs() {
  local args=() svc
  for svc in "${SERVICE_UNITS[@]}"; do
    args+=(-u "$svc")
  done
  journalctl "${args[@]}" -f || true
}

cmd_enable() {
  check_sudo
  systemctl enable "$TARGET_UNIT"
  log "Services enabled on boot"
}

cmd_disable() {
  check_sudo
  systemctl disable "$TARGET_UNIT"
  log "Services disabled on boot"
}

cmd_update() {
  check_sudo
  local svc
  for svc in "${SERVICE_UNITS[@]}"; do
    systemctl stop "$svc"
  done

  cd "$INSTALL_DIR"
  git pull
  git submodule update --init --recursive --remote --merge

  venv/bin/pip install --quiet --upgrade pip
  venv/bin/pip install --quiet -r requirements.txt

  export PATH="$CARGO_BIN:$INSTALL_DIR/venv/bin:$PATH"
  make build-setup

  sync_app_directories

  systemctl daemon-reload
  for svc in "${SERVICE_UNITS[@]}"; do
    systemctl restart "$svc"
  done
  systemctl start "$TARGET_UNIT"
  log "Update complete"
}

cmd_uninstall() {
  check_sudo
  local confirm
  read -r -p "Remove all services and data? (yes/no): " confirm || confirm="no"
  if [ "$confirm" != "yes" ]; then
    log "Cancelled"
    return 0
  fi

  local unit
  for unit in "${SERVICE_UNITS[@]}"; do
    systemctl stop "$unit" 2>/dev/null || true
  done
  systemctl stop "$TARGET_UNIT" 2>/dev/null || true
  systemctl disable "$TARGET_UNIT" 2>/dev/null || true

  for unit in "${ALL_UNITS[@]}"; do
    rm -f "/etc/systemd/system/$unit"
  done
  systemctl daemon-reload

  rm -rf "$INSTALL_DIR"
  log "Uninstall complete"
}

usage() {
  echo "Usage: $0 {start|stop|restart|status|logs|enable|disable|update|uninstall}"
  exit 1
}

main() {
  case "${1:-}" in
  start) cmd_start ;;
  stop) cmd_stop ;;
  restart) cmd_restart ;;
  status) cmd_status ;;
  logs) cmd_logs ;;
  enable) cmd_enable ;;
  disable) cmd_disable ;;
  update) cmd_update ;;
  uninstall) cmd_uninstall ;;
  *) usage ;;
  esac
}

main "$@"
