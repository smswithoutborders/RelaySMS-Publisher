#!/bin/bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/scripts/lib.sh"

INSTALL_DIR="$SCRIPT_DIR"
CARGO_BIN="$HOME/.cargo/bin"

INSTANCE_NAME="$(read_instance_name)"
TARGET_UNIT="$(unit_name_for "$TARGET_UNIT_TEMPLATE")"
SERVICE_UNITS=()
for _template in "${SERVICE_UNIT_TEMPLATES[@]}"; do
  SERVICE_UNITS+=("$(unit_name_for "$_template")")
done
unset _template
ALL_UNITS=("$TARGET_UNIT" "${SERVICE_UNITS[@]}")

check_sudo() { [ "$EUID" -eq 0 ] || error "Run with sudo"; }

# Only targets an already-installed service, so no fallback beyond the unit file.
detect_service_user() {
  local unit="/etc/systemd/system/$(unit_name_for "relaysms-publisher-rest.service")"
  grep -E "^User=" "$unit" 2>/dev/null | head -1 | cut -d= -f2
}

# git pull doesn't fix ownership for directories .env added since the last run.
sync_app_directories() {
  local service_user
  service_user="$(detect_service_user)"
  [ -n "$service_user" ] || return

  local envfile="$INSTALL_DIR/.env"
  local dirs=(
    "$(dirname "$(read_env_var SQLITE_DATABASE_PATH "$envfile")")"
    "$(dirname "$(read_env_var CELERY_BROKER_DB_PATH "$envfile")")"
    "$(dirname "$(read_env_var CELERY_RESULT_DB_PATH "$envfile")")"
    "$(dirname "$(read_env_var CELERY_BEAT_SCHEDULE_PATH "$envfile")")"
    "$(read_env_var PLATFORMS_ADAPTERS_DIR "$envfile")"
    "$(read_env_var PLATFORMS_ADAPTERS_VENV_DIR "$envfile")"
    "$(read_env_var PLATFORMS_ADAPTERS_ASSETS_DIR "$envfile")"
    "$(dirname "$(read_env_var PLATFORMS_REGISTRY_FILE "$envfile")")"
    "$(dirname "$(read_env_var GATEWAY_CLIENTS_REGISTRY_FILE "$envfile")")"
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

run_migrations() {
  local service_user
  service_user="$(detect_service_user)"
  [ -n "$service_user" ] || error "Could not detect service user from installed unit files"

  log "Running database migrations"
  sudo -u "$service_user" bash -c "
    set -a
    # shellcheck disable=SC1091
    . '$INSTALL_DIR/.env'
    set +a
    cd '$INSTALL_DIR'
    PATH='$INSTALL_DIR/venv/bin:$PATH' make migrate-up
  "
}

cmd_migrate() {
  check_sudo
  run_migrations
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

# Appends to the caller's local `units` array via dynamic scoping. Must be
# called directly, not through $(...), or error()'s exit would only kill
# the subshell instead of stopping the script.
add_unit() {
  local name="$1" full="$1" svc
  [[ "$name" == *.service ]] || full="relaysms-publisher-${name}.service"
  for svc in "${SERVICE_UNITS[@]}"; do
    if [ "$svc" = "$full" ]; then
      units+=("$full")
      return
    fi
  done
  error "Unknown service unit: $name (choose from: rest, grpc, worker, beat, smtp, or a full unit name)"
}

logs_usage() {
  cat <<'EOF'
Usage: manage.sh logs [OPTIONS]

  -u, --unit NAME      Service to show (rest|grpc|worker|beat|smtp), repeatable (default: all)
  -n, --lines N         Number of lines to show before following/exiting
  -s, --since DATE      Only show entries at or after DATE (journalctl --since syntax)
  --no-follow           Print the selected range and exit instead of tailing
  -h, --help            Show this help and exit
EOF
}

cmd_logs() {
  local units=() since="" lines="" follow=1

  while [ $# -gt 0 ]; do
    case "$1" in
    -u | --unit)
      add_unit "$2"
      shift 2
      ;;
    --unit=*)
      add_unit "${1#*=}"
      shift
      ;;
    -n | --lines)
      lines="$2"
      shift 2
      ;;
    --lines=*)
      lines="${1#*=}"
      shift
      ;;
    -s | --since)
      since="$2"
      shift 2
      ;;
    --since=*)
      since="${1#*=}"
      shift
      ;;
    --no-follow)
      follow=0
      shift
      ;;
    -h | --help)
      logs_usage
      return
      ;;
    *)
      logs_usage
      error "Unknown logs option: $1"
      ;;
    esac
  done

  [ "${#units[@]}" -gt 0 ] || units=("${SERVICE_UNITS[@]}")

  local args=() u
  for u in "${units[@]}"; do
    args+=(-u "$u")
  done
  [ -n "$lines" ] && args+=(-n "$lines")
  [ -n "$since" ] && args+=(--since "$since")
  [ "$follow" = "1" ] && args+=(-f)

  journalctl "${args[@]}" || true
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

update_usage() {
  cat <<'EOF'
Usage: manage.sh update [OPTIONS]

  -m, --migrate   Run database migrations after pulling and rebuilding
  -h, --help      Show this help and exit
EOF
}

cmd_update() {
  local migrate=0
  while [ $# -gt 0 ]; do
    case "$1" in
    -m | --migrate)
      migrate=1
      shift
      ;;
    -h | --help)
      update_usage
      return
      ;;
    *)
      update_usage
      error "Unknown update option: $1"
      ;;
    esac
  done

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
  # Only update observability deps if they were opted into in the first place.
  if venv/bin/pip show opentelemetry-sdk &>/dev/null; then
    venv/bin/pip install --quiet -r requirements-observability.txt
  fi

  export PATH="$CARGO_BIN:$INSTALL_DIR/venv/bin:$PATH"
  make build-setup

  sync_app_directories

  [ "$migrate" = "1" ] && run_migrations

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

  # Belt-and-suspenders against a top-level directory, even though
  # INSTALL_DIR is always self-derived from this script's own location.
  [[ "$INSTALL_DIR" =~ ^(/[^/]+){2,}/?$ ]] || error "Refusing to remove '$INSTALL_DIR': not a safe path"
  rm -rf "$INSTALL_DIR"
  log "Uninstall complete"
}

usage() {
  echo "Usage: $0 {start|stop|restart|status|logs|enable|disable|migrate|update|uninstall}"
  exit 1
}

main() {
  case "${1:-}" in
  start) cmd_start ;;
  stop) cmd_stop ;;
  restart) cmd_restart ;;
  status) cmd_status ;;
  logs)
    shift
    cmd_logs "$@"
    ;;
  enable) cmd_enable ;;
  disable) cmd_disable ;;
  migrate) cmd_migrate ;;
  update)
    shift
    cmd_update "$@"
    ;;
  uninstall) cmd_uninstall ;;
  *) usage ;;
  esac
}

main "$@"
