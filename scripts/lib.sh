#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Shared helpers sourced by the other scripts in this repo.

# Colors are skipped when the relevant stream isn't a terminal.
_no_color="${NO_COLOR:-}"
if [[ -t 1 && -z "$_no_color" ]]; then
  _grn=$'\033[0;32m'
else
  _grn=''
fi
if [[ -t 2 && -z "$_no_color" ]]; then
  _red=$'\033[0;31m'
  _ylw=$'\033[0;33m'
else
  _red=''
  _ylw=''
fi

# $1=color $2=symbol $3=fd (1 or 2) $4=message. Reset code is derived from
# whether $1 is set, so callers don't have to track a matching "off" value.
_log_line() {
  local now off=''
  printf -v now '%(%Y-%m-%d %H:%M:%S)T' -1
  [[ -n "$1" ]] && off=$'\033[0m'
  printf '%s[%s]%s [%s] %s\n' "$1" "$2" "$off" "$now" "$4" >&"$3"
}

log() { _log_line "$_grn" '*' 1 "$*"; }
warn() { _log_line "$_ylw" '!' 2 "$*"; }
error() {
  _log_line "$_red" 'x' 2 "ERROR: $*"
  exit 1
}
on_err() { _log_line "$_red" 'x' 2 "ERROR: aborted at line $1 (last command: $2)"; }
trap 'on_err "$LINENO" "$BASH_COMMAND"' ERR

# Keeps output like generated credentials from getting lost in the log.
highlight() {
  local line
  echo
  echo "################################################################"
  for line in "$@"; do
    echo "# $line"
  done
  echo "################################################################"
  echo
}

# Excludes characters unsafe in SQL/AMQP, and can't start with - (CLI flag).
validate_identifier() {
  local name="$1" value="$2"
  [[ "$value" =~ ^[A-Za-z_][A-Za-z0-9_]{0,63}$ ]] ||
    error "$name must contain only letters, digits, and underscores, and start with a letter or underscore (got: '$value')"
}

# Excludes characters that could break out of SQL/sed/amqp:// contexts.
validate_secret() {
  local name="$1" value="$2"
  [[ "$value" =~ ^[A-Za-z0-9_.,!?+=~^-]+$ ]] ||
    error "$name contains unsupported characters (letters, digits, and _.,!?+=~^- only)"
}

# Rejects slashes (path traversal into nginx conf paths) and a leading -
# (could be mistaken for a certbot flag).
validate_hostname() {
  local name="$1" value="$2"
  [[ "$value" =~ ^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$ ]] ||
    error "$name must be a valid hostname (got: '$value')"
}

# Reads from the controlling terminal even when piped via `curl | sudo
# bash` (stdin is the script itself there). Falls back to $default if no
# tty is reachable.
prompt() {
  local __resultvar="$1" question="> $2" default="${3:-}" reply=""
  if [ -t 0 ]; then
    read -r -p "$question" reply
  elif [ -r /dev/tty ]; then
    # -r only means the device node exists, not that a terminal is attached.
    read -r -p "$question" reply </dev/tty || true
  fi
  printf -v "$__resultvar" '%s' "${reply:-$default}"
}

# Same as prompt(), but the value isn't echoed to the terminal as it's typed.
prompt_secret() {
  local __resultvar="$1" question="> $2" reply=""
  if [ -t 0 ]; then
    read -rs -p "$question" reply
    echo
  elif [ -r /dev/tty ]; then
    read -rs -p "$question" reply </dev/tty || true
    echo
  fi
  printf -v "$__resultvar" '%s' "$reply"
}

# True (0) if nothing is currently listening on the given local TCP port.
port_is_free() {
  local port="$1"
  ! ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE ":${port}\$"
}

require_root() { [ "$EUID" -eq 0 ] || error "Run with sudo"; }

SYSTEMD_DIR="/etc/systemd/system"
TARGET_UNIT_TEMPLATE="relaysms-publisher.target"
SERVICE_UNIT_TEMPLATES=(
  relaysms-publisher-rest.service
  relaysms-publisher-grpc.service
  relaysms-publisher-worker.service
  relaysms-publisher-beat.service
  relaysms-publisher-smtp.service
)

# Expects INSTANCE_NAME to already be set by the caller (empty is fine).
unit_name_for() {
  local template="$1"
  if [ -z "${INSTANCE_NAME:-}" ]; then
    echo "$template"
  else
    echo "$template" | sed -E "s/^relaysms-publisher/relaysms-publisher-$INSTANCE_NAME/"
  fi
}

# Sets TARGET_UNIT and SERVICE_UNITS for INSTANCE_NAME.
set_unit_names() {
  local template
  # shellcheck disable=SC2034
  TARGET_UNIT="$(unit_name_for "$TARGET_UNIT_TEMPLATE")"
  SERVICE_UNITS=()
  for template in "${SERVICE_UNIT_TEMPLATES[@]}"; do
    SERVICE_UNITS+=("$(unit_name_for "$template")")
  done
}

# Renders every unit template into SYSTEMD_DIR. Expects INSTALL_DIR and
# INSTANCE_NAME to already be set by the caller.
render_units() {
  local unit_user="$1" rw_paths
  rw_paths="$(app_directories | paste -sd ' ')"
  # Only matches unit-name references (PartOf=, WantedBy=, ...), never
  # Description=/Documentation=: those read "RelaySMS Publisher" (space,
  # capitalized), not this lowercase-hyphenated pattern.
  local instance_sed_args=() template name
  if [ -n "${INSTANCE_NAME:-}" ]; then
    instance_sed_args+=(-e "s/relaysms-publisher\.target/$(unit_name_for "$TARGET_UNIT_TEMPLATE")/g")
    for template in "${SERVICE_UNIT_TEMPLATES[@]}"; do
      name="$(unit_name_for "$template")"
      instance_sed_args+=(
        -e "s/${template%.service}\.service/$name/g"
        -e "s/${template%.service}\$/${name%.service}/g"
      )
    done
  fi

  for template in "$TARGET_UNIT_TEMPLATE" "${SERVICE_UNIT_TEMPLATES[@]}"; do
    sed \
      -e "s/User=relaysms/User=$unit_user/" \
      -e "s#/opt/relaysms/relaysms-publisher#$INSTALL_DIR#g" \
      -e "s#__RW_PATHS__#$rw_paths#" \
      "${instance_sed_args[@]}" \
      "$INSTALL_DIR/deploy/systemd/$template" >"$SYSTEMD_DIR/$(unit_name_for "$template")"
  done
}

# Expects INSTALL_DIR to already be set by the caller.
read_instance_name() {
  [ -f "$INSTALL_DIR/.instance-name" ] && cat "$INSTALL_DIR/.instance-name" || true
}

# `|| true` on the grep stops a no-match from tripping pipefail.
read_env_var() {
  local key="$1" file="$2" val
  val=$( (grep -E "^(export[[:space:]]+)?${key}[[:space:]]*=" "$file" 2>/dev/null || true) |
    tail -1 | sed -E 's/^(export[[:space:]]+)?[^=]*=//; s/^[[:space:]]*//; s/[[:space:]]*$//')
  val="${val%\"}"
  val="${val#\"}"
  val="${val%\'}"
  val="${val#\'}"
  echo "$val"
}

# Every directory the services write to, one per line, absolute and
# deduplicated. Vars unset in .env fall back to template.env, which holds the
# same defaults as publisher/config.py. Expects INSTALL_DIR to already be set.
app_directories() {
  local var kind path
  while read -r var kind; do
    path=$(read_env_var "$var" "$INSTALL_DIR/.env")
    [ -n "$path" ] || path=$(read_env_var "$var" "$INSTALL_DIR/template.env")
    [ -n "$path" ] && [ "$path" != ":memory:" ] || continue
    [ "$kind" = dir ] || path=$(dirname "$path")
    [[ "$path" = /* ]] || path="$INSTALL_DIR/$path"
    path="${path%/.}"
    echo "${path%/}"
  done <<'EOF' | awk '!seen[$0]++'
SQLITE_DATABASE_PATH file
CELERY_BROKER_DB_PATH file
CELERY_RESULT_DB_PATH file
CELERY_BEAT_SCHEDULE_PATH file
PLATFORMS_ADAPTERS_DIR dir
PLATFORMS_ADAPTERS_VENV_DIR dir
PLATFORMS_ADAPTERS_ASSETS_DIR dir
PLATFORMS_REGISTRY_FILE file
GATEWAY_CLIENTS_REGISTRY_FILE file
EOF
}

# The install root itself stays owned by whoever installed it.
ensure_app_directories() {
  local unit_user="$1" dir root
  root="$(realpath "$INSTALL_DIR")"
  while read -r dir; do
    [ "$dir" != "$INSTALL_DIR" ] || continue
    # The services can write these dirs, so a symlink planted in one could
    # point root's chown at any directory.
    if [ "$(realpath -m "$dir")" != "${dir/#"$INSTALL_DIR"/$root}" ]; then
      warn "Skipping $dir: its path goes through a symlink"
      continue
    fi
    mkdir -p "$dir"
    chown "$unit_user:" "$dir"
    chmod 750 "$dir"
    log "  $dir"
  done < <(app_directories)
}

# Prints nothing when the services aren't installed. Expects INSTANCE_NAME to
# already be set by the caller.
installed_service_user() {
  local unit
  unit="$SYSTEMD_DIR/$(unit_name_for "relaysms-publisher-rest.service")"
  [ -f "$unit" ] || return 0
  awk -F= '/^User=/ { print $2; exit }' "$unit"
}

# Prefers the installed unit's User=, then .env's owner, then whoever is
# running the script. Expects ENV_FILE and INSTANCE_NAME to already be set.
detect_service_user() {
  local user
  user="$(installed_service_user)"
  [ -z "$user" ] && [ -f "$ENV_FILE" ] && user="$(stat -c '%U' "$ENV_FILE" 2>/dev/null)"
  echo "${user:-$(id -un)}"
}

# Renders the nginx site for $1 into $2, with the ports from .env.
render_nginx_site() {
  local site="$1" conf="$2" rest_port grpc_port
  rest_port=$(read_env_var PORT "$INSTALL_DIR/.env")
  grpc_port=$(read_env_var GRPC_PORT "$INSTALL_DIR/.env")
  sed \
    -e "s/__SERVER_NAME__/$site/g" \
    -e "s/__REST_PORT__/${rest_port:-16000}/g" \
    -e "s/__GRPC_PORT__/${grpc_port:-6000}/g" \
    "$INSTALL_DIR/deploy/nginx/relaysms-publisher-nginx.conf.template" >"$conf"
}

install_nginx_certbot() {
  if ! command -v nginx &>/dev/null || ! command -v certbot &>/dev/null; then
    log "Installing nginx and certbot"
    apt-get install -y --no-install-recommends nginx certbot python3-certbot-nginx
  fi
  mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled
}

reload_nginx() {
  nginx -t || error "nginx config test failed"
  systemctl enable nginx &>/dev/null || true
  systemctl reload nginx 2>/dev/null || systemctl restart nginx
}

# Obtains a certificate for site $1 and points its nginx site at it. $2 is an
# optional email for renewal notices.
request_certificate() {
  local site="$1" email="${2:-}"
  local args=(--nginx -d "$site" --redirect --agree-tos --non-interactive)
  if [ -n "$email" ]; then
    args+=(-m "$email")
  else
    args+=(--register-unsafely-without-email)
  fi
  log "Requesting certificate for $site"
  certbot "${args[@]}"
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

# Runs a command as SERVICE_USER, in INSTALL_DIR, with the venv on PATH.
# Python commands load .env themselves through config. Expects INSTALL_DIR,
# ENV_FILE, VENV_DIR, SERVICE_USER, and CURRENT_USER to be set by the caller.
run_as_service_user() {
  local inner_cmd="$1"
  local run_cmd="
    cd '$INSTALL_DIR'
    export PATH=\"$VENV_DIR/bin:$PATH\"
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

# Opens an interactive shell as SERVICE_USER with .env exported, for running
# commands by hand.
run_service_shell() {
  log "Opening shell as '$SERVICE_USER' in $INSTALL_DIR ..."
  run_as_service_user "set -a; . '$ENV_FILE'; set +a; exec bash"
}
