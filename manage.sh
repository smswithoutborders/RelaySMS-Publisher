#!/bin/bash

set -euo pipefail

INSTALL_DIR="/opt/relaysms/relaysms-publisher"
CARGO_BIN="$HOME/.cargo/bin"

TARGET_UNIT="relaysms-publisher.target"
SERVICE_UNITS=(
  relaysms-publisher-rest.service
  relaysms-publisher-grpc.service
  relaysms-publisher-worker.service
  relaysms-publisher-beat.service
)
ALL_UNITS=("$TARGET_UNIT" "${SERVICE_UNITS[@]}")

log() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"; }
error() {
  echo "[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2
  exit 1
}

check_sudo() { [ "$EUID" -eq 0 ] || error "Run with sudo"; }

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
