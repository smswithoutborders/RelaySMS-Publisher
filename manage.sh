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

nginx_usage() {
  cat <<'EOF'
Usage: manage.sh nginx [DOMAIN]

Re-renders the nginx site from the template, reattaches or obtains its
certificate, enables HTTP/2 for gRPC and reloads nginx. DOMAIN defaults to
this install's site. The previous file is kept as <site>.conf.bak and
restored on failure.
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

# gRPC needs HTTP/2, which certbot never enables. nginx 1.25.1+ takes
# "http2 on;"; below 1.25.1 only "listen ... http2" works.
enable_nginx_http2() {
  local conf="$1" version
  version=$(nginx -v 2>&1 | sed -n 's#.*nginx/\([0-9.]*\).*#\1#p')
  if printf '%s\n' 1.25.1 "$version" | sort -V -C; then
    sed -i 's/^\(\s*\)listen 443 ssl;.*/&\n\1http2 on;/' "$conf"
  else
    sed -i \
      -e "s/listen 443 ssl;/listen 443 ssl http2;/" \
      -e "s/listen \\[::\\]:443 ssl;/listen [::]:443 ssl http2;/" \
      -e "s/listen \\[::\\]:443 ssl ipv6only=on;/listen [::]:443 ssl http2 ipv6only=on;/" \
      "$conf"
  fi
}

install_nginx_site() {
  local site="$1" conf="$2" envfile="$INSTALL_DIR/.env" rest_port grpc_port
  rest_port=$(read_env_var PORT "$envfile")
  grpc_port=$(read_env_var GRPC_PORT "$envfile")

  sed \
    -e "s/__SERVER_NAME__/$site/g" \
    -e "s/__REST_PORT__/${rest_port:-16000}/g" \
    -e "s/__GRPC_PORT__/${grpc_port:-6000}/g" \
    "$INSTALL_DIR/relaysms-publisher-nginx.conf.template" >"$conf" || return 1
  ln -sf "$conf" "/etc/nginx/sites-enabled/${site}.conf" || return 1

  # Re-adds the 443 block that re-rendering dropped.
  if [ -f "/etc/letsencrypt/live/${site}/fullchain.pem" ]; then
    certbot install --nginx --cert-name "$site" --redirect --non-interactive || return 1
  else
    local email_args=(--register-unsafely-without-email)
    [ -n "${LETSENCRYPT_EMAIL:-}" ] && email_args=(-m "$LETSENCRYPT_EMAIL")
    certbot --nginx -d "$site" --redirect --agree-tos --non-interactive \
      "${email_args[@]}" || return 1
  fi

  enable_nginx_http2 "$conf" || return 1
  nginx -t || return 1
}

cmd_nginx() {
  case "${1:-}" in
  -h | --help)
    nginx_usage
    return
    ;;
  esac
  check_sudo
  command -v nginx &>/dev/null && command -v certbot &>/dev/null ||
    error "nginx and certbot must be installed"

  local site="${1:-}"
  [ -n "$site" ] || site=$(detect_nginx_site)
  validate_hostname "DOMAIN" "$site"

  local conf="/etc/nginx/sites-available/${site}.conf"
  [ -f "$conf" ] && cp -p "$conf" "$conf.bak"

  if ! install_nginx_site "$site" "$conf"; then
    if [ -f "$conf.bak" ]; then
      cp -p "$conf.bak" "$conf"
      nginx -t && systemctl reload nginx
    fi
    error "nginx setup failed for $site; previous config restored"
  fi
  systemctl reload nginx
  log "nginx site $site updated"
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
  echo "Usage: $0 {start|stop|restart|status|logs|enable|disable|migrate|update|nginx|uninstall}"
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
  nginx)
    shift
    cmd_nginx "$@"
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
