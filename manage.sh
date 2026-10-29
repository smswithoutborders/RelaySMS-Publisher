#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "$SCRIPT_DIR/scripts/lib.sh"

INSTALL_DIR="$SCRIPT_DIR"
CARGO_BIN="$HOME/.cargo/bin"

INSTANCE_NAME="$(read_instance_name)"
set_unit_names
ALL_UNITS=("$TARGET_UNIT" "${SERVICE_UNITS[@]}")
SERVICE_USER="$(installed_service_user)"

require_installed() {
  [ -n "$SERVICE_USER" ] ||
    error "No installed service found. Run install.sh first, or for a local check: venv/bin/python -m publisher config check"
}

run_migrations() {
  require_installed
  log "Running database migrations"
  (cd "$INSTALL_DIR" && sudo -u "$SERVICE_USER" venv/bin/python -m alembic upgrade head)
  # Registers adapter directories with no database row, and moves their files
  # out of their code directories.
  (cd "$INSTALL_DIR" && sudo -u "$SERVICE_USER" venv/bin/python -m publisher platforms import)
}

run_config_check() {
  require_installed
  log "Checking configuration"
  (cd "$INSTALL_DIR" && sudo -u "$SERVICE_USER" venv/bin/python -m publisher config check)
}

cmd_check() {
  require_root
  run_config_check
}

cmd_migrate() {
  require_root
  run_migrations
}

cmd_start() {
  require_root
  systemctl start "$TARGET_UNIT"
  log "Services started"
}

cmd_stop() {
  require_root
  local svc
  for svc in "${SERVICE_UNITS[@]}"; do
    systemctl stop "$svc"
  done
  systemctl stop "$TARGET_UNIT"
  log "Services stopped"
}

cmd_restart() {
  require_root
  # Pick up unit files edited since the last reload.
  systemctl daemon-reload
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

  -u, --unit NAME       Service to show (rest|grpc|worker|beat|smtp), repeatable (default: all)
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
  require_root
  systemctl enable "$TARGET_UNIT"
  log "Services enabled on boot"
}

cmd_disable() {
  require_root
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
  local migrate=0 pulled=0
  while [ $# -gt 0 ]; do
    case "$1" in
    -m | --migrate)
      migrate=1
      shift
      ;;
    --pulled)
      pulled=1
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

  require_root
  cd "$INSTALL_DIR"
  local svc
  if [ "$pulled" = "0" ]; then
    # A failed fetch leaves the services running.
    git fetch
    for svc in "${SERVICE_UNITS[@]}"; do
      systemctl stop "$svc"
    done
    # Follows a force-pushed branch, and fails rather than overwrite local edits.
    git reset --keep "@{upstream}"
    git submodule update --init --recursive
    # Runs the rest of the update with the manage.sh just checked out.
    local args=(--pulled)
    [ "$migrate" = "1" ] && args+=(--migrate)
    exec "$INSTALL_DIR/manage.sh" update "${args[@]}"
  fi

  venv/bin/pip install --quiet --upgrade pip
  local reqs=requirements.txt
  # Only update observability deps if they were opted into. Their requirements
  # file includes requirements.txt.
  if venv/bin/pip show opentelemetry-distro &>/dev/null; then
    reqs=requirements-observability.txt
  fi
  venv/bin/pip install --quiet -r "$reqs"

  export PATH="$CARGO_BIN:$PATH"
  make build

  # Directories and units follow .env, which the migration may have just changed.
  "$INSTALL_DIR/scripts/migrate-runtime-data.sh"
  require_installed
  ensure_app_directories "$SERVICE_USER"
  render_units "$SERVICE_USER"

  # A config error is reported after every service restarts.
  local config_ok=1
  run_config_check || config_ok=0

  [ "$migrate" = "1" ] && run_migrations

  systemctl daemon-reload
  for svc in "${SERVICE_UNITS[@]}"; do
    systemctl restart "$svc"
  done
  systemctl start "$TARGET_UNIT"
  # book/ exists only when install.sh set up a site for the manual.
  if [ -d book ]; then
    ./scripts/build-book.sh
  fi
  [ "$config_ok" = "1" ] || error "Update applied, but .env has errors (above); services using those settings won't start"
  log "Update complete"
}

nginx_usage() {
  cat <<'EOF'
Usage: manage.sh nginx [DOMAIN]

Re-renders the nginx site from the template, reattaches or obtains its
certificate, enables HTTP/2 for gRPC and reloads nginx. DOMAIN defaults to
this install's site. The previous file is kept as <site>.conf.bak and
restored on failure.
EOF
}

docs_usage() {
  cat <<'EOF'
Usage: manage.sh docs [DOMAIN]

Builds the manual into book/, then renders its nginx site from the template,
reattaches or obtains its certificate and reloads nginx. DOMAIN defaults to
this install's manual site. The previous file is kept as <site>.conf.bak and
restored on failure. manage.sh update rebuilds the manual afterwards.
EOF
}

# Matches publisher_rest_<PORT> (this install) or an unsuffixed publisher_rest.
detect_nginx_site() {
  local port sites=()
  port=$(read_env_var PORT "$INSTALL_DIR/.env")
  mapfile -t sites < <(grep -lE "upstream publisher_rest(_${port:-16000})? \{" \
    /etc/nginx/sites-available/*.conf 2>/dev/null)
  [ "${#sites[@]}" -eq 1 ] ||
    error "Found ${#sites[@]} matching nginx sites; pass the domain: $0 nginx DOMAIN"
  basename "${sites[0]}" .conf
}

detect_docs_site() {
  local sites=()
  mapfile -t sites < <(grep -lF "root $INSTALL_DIR/book;" /etc/nginx/sites-available/*.conf 2>/dev/null)
  [ "${#sites[@]}" -eq 1 ] ||
    error "Found ${#sites[@]} matching nginx sites; pass the domain: $0 docs DOMAIN"
  basename "${sites[0]}" .conf
}

# $1=domain $2=site file $3=function that writes it, called as "$3 DOMAIN FILE"
install_nginx_site() {
  local site="$1" conf="$2" render="$3"
  "$render" "$site" "$conf" || return 1
  ln -sf "$conf" "/etc/nginx/sites-enabled/${site}.conf" || return 1

  # Re-adds the 443 block that re-rendering dropped.
  if [ -f "/etc/letsencrypt/live/${site}/fullchain.pem" ]; then
    certbot install --nginx --cert-name "$site" --redirect --non-interactive || return 1
  else
    request_certificate "$site" "${LETSENCRYPT_EMAIL:-}" || return 1
  fi

  enable_nginx_http2 "$conf" || return 1
  nginx -t || return 1
}

require_nginx() {
  if ! command -v nginx &>/dev/null || ! command -v certbot &>/dev/null; then
    error "nginx and certbot must be installed"
  fi
}

# $1=domain $2=function that writes its site file
apply_nginx_site() {
  local site="$1" render="$2"
  validate_hostname "DOMAIN" "$site"

  local conf="/etc/nginx/sites-available/${site}.conf"
  [ -f "$conf" ] && cp -p "$conf" "$conf.bak"

  if ! install_nginx_site "$site" "$conf" "$render"; then
    if [ -f "$conf.bak" ]; then
      cp -p "$conf.bak" "$conf"
      nginx -t && systemctl reload nginx
    fi
    error "nginx setup failed for $site; previous config restored"
  fi
  systemctl reload nginx
  log "nginx site $site updated"
}

cmd_nginx() {
  case "${1:-}" in
  -h | --help)
    nginx_usage
    return
    ;;
  esac
  require_root
  require_nginx
  local site="${1:-}"
  [ -n "$site" ] || site=$(detect_nginx_site)
  apply_nginx_site "$site" render_nginx_site
}

cmd_docs() {
  case "${1:-}" in
  -h | --help)
    docs_usage
    return
    ;;
  esac
  require_root
  require_nginx
  local site="${1:-}"
  [ -n "$site" ] || site=$(detect_docs_site)
  validate_hostname "DOMAIN" "$site"
  "$INSTALL_DIR/scripts/build-book.sh"
  apply_nginx_site "$site" render_docs_site
}

cmd_uninstall() {
  require_root
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
    rm -f "$SYSTEMD_DIR/$unit"
  done
  systemctl daemon-reload

  [[ "$INSTALL_DIR" =~ ^(/[^/]+){2,}/?$ ]] || error "Refusing to remove '$INSTALL_DIR': not a safe path"
  rm -rf "$INSTALL_DIR"
  log "Uninstall complete"
}

usage() {
  echo "Usage: $0 {start|stop|restart|status|logs|enable|disable|check|migrate|update|nginx|docs|uninstall}"
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
  check) cmd_check ;;
  migrate) cmd_migrate ;;
  nginx)
    shift
    cmd_nginx "$@"
    ;;
  docs)
    shift
    cmd_docs "$@"
    ;;
  update)
    shift
    cmd_update "$@"
    ;;
  uninstall) cmd_uninstall ;;
  *) usage ;;
  esac
}

main "$@"
