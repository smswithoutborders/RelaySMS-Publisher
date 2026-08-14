#!/bin/bash

set -Eeuo pipefail

DEFAULT_INSTALL_DIR="/opt/relaysms/relaysms-publisher"
if [ -n "${INSTALL_DIR:-}" ]; then
  INSTALL_DIR_SET=1
else
  INSTALL_DIR_SET=0
fi
INSTALL_DIR="${INSTALL_DIR:-$DEFAULT_INSTALL_DIR}"
if [ -n "${INSTANCE_NAME:-}" ]; then
  INSTANCE_NAME_SET=1
else
  INSTANCE_NAME_SET=0
fi
INSTANCE_NAME="${INSTANCE_NAME:-}"
REPO_URL="https://github.com/smswithoutborders/RelaySMS-Publisher.git"
BRANCH="${BRANCH:-main}"
CARGO_BIN="$HOME/.cargo/bin"
DEPS_MARKER="/var/lib/relaysms-publisher-deps-installed"
NGINX_CONF_TEMPLATE="relaysms-publisher-nginx.conf.template"
SITE_NAME="${SITE_NAME:-}"
LETSENCRYPT_EMAIL="${LETSENCRYPT_EMAIL:-}"
SKIP_NGINX="${SKIP_NGINX:-0}"
FORCE_DEPS="${FORCE_DEPS:-0}"
SETUP_DB="${SETUP_DB:-}"
if [ -n "${DB_EXISTING:-}" ]; then
  DB_EXISTING_SET=1
else
  DB_EXISTING_SET=0
fi
DB_EXISTING="${DB_EXISTING:-0}"
DB_HOST="${DB_HOST:-}"
DB_PORT="${DB_PORT:-}"
DB_NAME="${DB_NAME:-}"
DB_USER="${DB_USER:-}"
DB_PASSWORD="${DB_PASSWORD:-}"
SETUP_BROKER="${SETUP_BROKER:-}"
if [ -n "${BROKER_EXISTING:-}" ]; then
  BROKER_EXISTING_SET=1
else
  BROKER_EXISTING_SET=0
fi
BROKER_EXISTING="${BROKER_EXISTING:-0}"
BROKER_HOST="${BROKER_HOST:-}"
BROKER_PORT="${BROKER_PORT:-}"
BROKER_MGMT_PORT="${BROKER_MGMT_PORT:-}"
BROKER_VHOST="${BROKER_VHOST:-}"
BROKER_USER="${BROKER_USER:-}"
BROKER_PASSWORD="${BROKER_PASSWORD:-}"
SETUP_OBSERVABILITY="${SETUP_OBSERVABILITY:-}"
OBSERVABILITY_SITE_NAME="${OBSERVABILITY_SITE_NAME:-}"
OBSERVABILITY_LETSENCRYPT_EMAIL="${OBSERVABILITY_LETSENCRYPT_EMAIL:-}"

TARGET_UNIT_TEMPLATE="relaysms-publisher.target"
SERVICE_UNIT_TEMPLATES=(
  relaysms-publisher-rest.service
  relaysms-publisher-grpc.service
  relaysms-publisher-worker.service
  relaysms-publisher-beat.service
  relaysms-publisher-smtp.service
)
ALL_UNIT_TEMPLATES=("$TARGET_UNIT_TEMPLATE" "${SERVICE_UNIT_TEMPLATES[@]}")

unit_name_for() {
  local template="$1"
  if [ -z "$INSTANCE_NAME" ]; then
    echo "$template"
  else
    echo "$template" | sed -E "s/^relaysms-publisher/relaysms-publisher-$INSTANCE_NAME/"
  fi
}

if [ -n "${SUDO_USER:-}" ] && id "$SUDO_USER" &>/dev/null; then
  SERVICE_USER="$SUDO_USER"
else
  SERVICE_USER="relaysms"
fi

log() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"; }
error() {
  echo "[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2
  exit 1
}
on_err() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: aborted at line $1 (last command: $2)" >&2; }
trap 'on_err "$LINENO" "$BASH_COMMAND"' ERR

usage() {
  cat <<'EOF'
Usage: install.sh [OPTIONS]

  --install-dir PATH                       Installation directory (default: /opt/relaysms/relaysms-publisher)
  --instance-name NAME                     Namespace this install's systemd units so a second instance
                                            can coexist on the same host (default: unnamed/single instance)
  --branch BRANCH                          Git branch to install (default: main)
  --site-name DOMAIN                       Domain to front with nginx + Let's Encrypt
  --letsencrypt-email EMAIL                Email for Let's Encrypt renewal notices
  --skip-nginx                             Skip the nginx/TLS setup entirely
  --force-deps                             Reinstall system dependencies even if already marked done
  --setup-db {mysql|postgres}              Install and provision a database server, or connect to an existing one
  --db-existing                            Use an already-running database server instead of installing one locally
  --db-host HOST                           Database host (only valid with --db-existing)
  --db-port PORT                           Database port (only valid with --db-existing)
  --db-name NAME                           Database name (default: relaysms)
  --db-user USER                           Database user (default: relaysms)
  --db-password PASS                       Database password (default: randomly generated; required with --db-existing)
  --setup-broker {rabbitmq}                Install and provision a message broker for Celery, or connect to an existing one
  --broker-existing                        Use an already-running broker instead of installing one locally
  --broker-host HOST                       Broker host (only valid with --broker-existing)
  --broker-port PORT                       Broker AMQP port (only valid with --broker-existing)
  --broker-mgmt-port PORT                  Broker management API port, used to verify --broker-existing credentials (default: 15672)
  --broker-vhost NAME                      RabbitMQ vhost (default: relaysms)
  --broker-user USER                       RabbitMQ user (default: relaysms)
  --broker-password PASS                   RabbitMQ password (default: randomly generated; required with --broker-existing)
  --setup-observability                    Install and start SigNoz + Uptime Kuma
  --observability-site-name DOMAIN         Domain for the observability reverse proxy
  --observability-letsencrypt-email EMAIL  Email for its Let's Encrypt renewal notices
  -h, --help                               Show this help and exit

Piped through curl, pass options after `-s --`:
  curl -fsSL .../install.sh | sudo bash -s -- --site-name publisher.example.com
EOF
}

parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
    --install-dir)
      INSTALL_DIR="$2"
      INSTALL_DIR_SET=1
      shift 2
      ;;
    --install-dir=*)
      INSTALL_DIR="${1#*=}"
      INSTALL_DIR_SET=1
      shift
      ;;
    --instance-name)
      INSTANCE_NAME="$2"
      INSTANCE_NAME_SET=1
      shift 2
      ;;
    --instance-name=*)
      INSTANCE_NAME="${1#*=}"
      INSTANCE_NAME_SET=1
      shift
      ;;
    --branch)
      BRANCH="$2"
      shift 2
      ;;
    --branch=*)
      BRANCH="${1#*=}"
      shift
      ;;
    --site-name)
      SITE_NAME="$2"
      shift 2
      ;;
    --site-name=*)
      SITE_NAME="${1#*=}"
      shift
      ;;
    --letsencrypt-email)
      LETSENCRYPT_EMAIL="$2"
      shift 2
      ;;
    --letsencrypt-email=*)
      LETSENCRYPT_EMAIL="${1#*=}"
      shift
      ;;
    --skip-nginx)
      SKIP_NGINX=1
      shift
      ;;
    --force-deps)
      FORCE_DEPS=1
      shift
      ;;
    --setup-db)
      SETUP_DB="$2"
      shift 2
      ;;
    --setup-db=*)
      SETUP_DB="${1#*=}"
      shift
      ;;
    --db-existing)
      DB_EXISTING=1
      DB_EXISTING_SET=1
      shift
      ;;
    --db-host)
      DB_HOST="$2"
      shift 2
      ;;
    --db-host=*)
      DB_HOST="${1#*=}"
      shift
      ;;
    --db-port)
      DB_PORT="$2"
      shift 2
      ;;
    --db-port=*)
      DB_PORT="${1#*=}"
      shift
      ;;
    --db-name)
      DB_NAME="$2"
      shift 2
      ;;
    --db-name=*)
      DB_NAME="${1#*=}"
      shift
      ;;
    --db-user)
      DB_USER="$2"
      shift 2
      ;;
    --db-user=*)
      DB_USER="${1#*=}"
      shift
      ;;
    --db-password)
      DB_PASSWORD="$2"
      shift 2
      ;;
    --db-password=*)
      DB_PASSWORD="${1#*=}"
      shift
      ;;
    --setup-broker)
      SETUP_BROKER="$2"
      shift 2
      ;;
    --setup-broker=*)
      SETUP_BROKER="${1#*=}"
      shift
      ;;
    --broker-existing)
      BROKER_EXISTING=1
      BROKER_EXISTING_SET=1
      shift
      ;;
    --broker-host)
      BROKER_HOST="$2"
      shift 2
      ;;
    --broker-host=*)
      BROKER_HOST="${1#*=}"
      shift
      ;;
    --broker-port)
      BROKER_PORT="$2"
      shift 2
      ;;
    --broker-port=*)
      BROKER_PORT="${1#*=}"
      shift
      ;;
    --broker-mgmt-port)
      BROKER_MGMT_PORT="$2"
      shift 2
      ;;
    --broker-mgmt-port=*)
      BROKER_MGMT_PORT="${1#*=}"
      shift
      ;;
    --broker-vhost)
      BROKER_VHOST="$2"
      shift 2
      ;;
    --broker-vhost=*)
      BROKER_VHOST="${1#*=}"
      shift
      ;;
    --broker-user)
      BROKER_USER="$2"
      shift 2
      ;;
    --broker-user=*)
      BROKER_USER="${1#*=}"
      shift
      ;;
    --broker-password)
      BROKER_PASSWORD="$2"
      shift 2
      ;;
    --broker-password=*)
      BROKER_PASSWORD="${1#*=}"
      shift
      ;;
    --setup-observability)
      SETUP_OBSERVABILITY=1
      shift
      ;;
    --observability-site-name)
      OBSERVABILITY_SITE_NAME="$2"
      shift 2
      ;;
    --observability-site-name=*)
      OBSERVABILITY_SITE_NAME="${1#*=}"
      shift
      ;;
    --observability-letsencrypt-email)
      OBSERVABILITY_LETSENCRYPT_EMAIL="$2"
      shift 2
      ;;
    --observability-letsencrypt-email=*)
      OBSERVABILITY_LETSENCRYPT_EMAIL="${1#*=}"
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      usage
      error "Unknown option: $1"
      ;;
    esac
  done
}

check_root() { [ "$EUID" -eq 0 ] || error "Run with sudo"; }

configure_install_dir() {
  if [ "$INSTALL_DIR_SET" != "1" ]; then
    prompt INSTALL_DIR "Installation directory [$INSTALL_DIR]: " "$INSTALL_DIR"
  fi

  if [ -n "$INSTANCE_NAME" ]; then
    [[ "$INSTANCE_NAME" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$ ]] ||
      error "--instance-name '$INSTANCE_NAME' must start with a letter/digit and contain only letters, digits, underscores, and hyphens (max 32 chars)"
  fi

  # Blocks top-level dirs (so a later `rm -rf "$INSTALL_DIR"` can't wipe a
  # system directory) and sed-special characters (which would corrupt the
  # unit-file templating in install_services()).
  [[ "$INSTALL_DIR" =~ ^(/[A-Za-z0-9_.-]+){2,}/?$ ]] ||
    error "$INSTALL_DIR is not a safe install location; use an absolute path with at least two segments, letters/digits/._- only (e.g. /opt/relaysms/relaysms-publisher)"

  if [ -e "$INSTALL_DIR" ] && [ ! -d "$INSTALL_DIR" ]; then
    error "$INSTALL_DIR exists and is not a directory"
  fi

  if [ -d "$INSTALL_DIR" ] && [ -n "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]; then
    if [ -d "$INSTALL_DIR/.git" ] &&
      git -C "$INSTALL_DIR" remote get-url origin 2>/dev/null | grep -q "RelaySMS-Publisher"; then
      if [ -f "$INSTALL_DIR/.env" ]; then
        local existing_owner
        existing_owner=$(stat -c '%G' "$INSTALL_DIR/.env")
        if [ "$existing_owner" != "$SERVICE_USER" ]; then
          error "$INSTALL_DIR is an existing install owned by service user '$existing_owner', but this run resolved to '$SERVICE_USER'. Re-run install.sh with sudo as '$existing_owner' (SERVICE_USER follows the invoking sudo user), or use --install-dir to target a different directory."
        fi
      fi
      # manage.sh has no --instance-name flag, so persist it here for reuse.
      local existing_instance=""
      [ -f "$INSTALL_DIR/.instance-name" ] && existing_instance=$(<"$INSTALL_DIR/.instance-name")
      if [ -n "$existing_instance" ]; then
        if [ "$INSTANCE_NAME_SET" = "1" ] && [ "$INSTANCE_NAME" != "$existing_instance" ]; then
          error "$INSTALL_DIR was previously configured as instance '$existing_instance'. Pass --instance-name $existing_instance (or omit the flag) to reuse it, or use --install-dir to target a different directory for a new instance."
        fi
        INSTANCE_NAME="$existing_instance"
      fi
      log "Installation directory: $INSTALL_DIR (existing install for service user '$SERVICE_USER', will update)"
    else
      error "$INSTALL_DIR already exists and is not empty; choose an empty or non-existent directory with --install-dir, or point it at an existing RelaySMS Publisher checkout"
    fi
  else
    log "Installation directory: $INSTALL_DIR"
  fi

  TARGET_UNIT=$(unit_name_for "$TARGET_UNIT_TEMPLATE")
  SERVICE_UNITS=()
  local template
  for template in "${SERVICE_UNIT_TEMPLATES[@]}"; do
    SERVICE_UNITS+=("$(unit_name_for "$template")")
  done
  if [ -n "$INSTANCE_NAME" ]; then
    log "Instance: $INSTANCE_NAME (target unit: $TARGET_UNIT)"
  fi
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

# Reads from the controlling terminal even when piped via `curl | sudo
# bash` (stdin is the script itself there). Falls back to $default if no
# tty is reachable.
prompt() {
  local __resultvar="$1" question="> $2" default="${3:-}" reply=""
  if [ -t 0 ]; then
    read -r -p "$question" reply
  elif [ -r /dev/tty ]; then
    # -r only means the device node exists, not that a terminal is
    # attached; || true stops a failed open from aborting the install.
    read -r -p "$question" reply </dev/tty || true
  fi
  printf -v "$__resultvar" '%s' "${reply:-$default}"
}

# Same as prompt(), but a numbered menu instead of free text. Options are
# "label:value" pairs; default_idx is 1-based.
# Usage: prompt_menu RESULTVAR "Question" default_idx "Label one:value1" "Label two:value2"
prompt_menu() {
  local __resultvar="$1" question="$2" default_idx="$3"
  shift 3
  local -a menu_labels=() menu_values=()
  local menu_opt
  for menu_opt in "$@"; do
    menu_labels+=("${menu_opt%%:*}")
    menu_values+=("${menu_opt#*:}")
  done
  local menu_n=${#menu_labels[@]} menu_i menu_sel

  echo "$question"
  for ((menu_i = 0; menu_i < menu_n; menu_i++)); do
    if [ "$((menu_i + 1))" = "$default_idx" ]; then
      printf '  %d) %s (default)\n' "$((menu_i + 1))" "${menu_labels[$menu_i]}"
    else
      printf '  %d) %s\n' "$((menu_i + 1))" "${menu_labels[$menu_i]}"
    fi
  done

  while :; do
    prompt menu_sel "Enter a number [1-$menu_n]: " "$default_idx"
    if [[ "$menu_sel" =~ ^[0-9]+$ ]] && [ "$menu_sel" -ge 1 ] && [ "$menu_sel" -le "$menu_n" ]; then
      printf -v "$__resultvar" '%s' "${menu_values[$((menu_sel - 1))]}"
      return
    fi
    echo "Invalid choice: '$menu_sel' -- enter a number between 1 and $menu_n."
  done
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

_resolve_dir() {
  local dir="$1"
  [ -z "$dir" ] && return
  [[ "$dir" = /* ]] || dir="$INSTALL_DIR/$dir"
  local existing
  for existing in "${RW_DIRS[@]}"; do
    [ "$existing" = "$dir" ] && return
  done
  RW_DIRS+=("$dir")
}

install_system_deps() {
  if [ -f "$DEPS_MARKER" ] && [ "$FORCE_DEPS" != "1" ]; then
    log "System dependencies already installed, skipping (--force-deps to override)"
    return
  fi
  log "Installing system dependencies"
  apt-get update -qq
  apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv python3-dev \
    build-essential pkg-config \
    libsqlcipher-dev \
    libmagic1 \
    openssl git make curl
  mkdir -p "$(dirname "$DEPS_MARKER")"
  touch "$DEPS_MARKER"
}

install_rust() {
  if command -v cargo &>/dev/null || [ -x "$CARGO_BIN/cargo" ]; then
    log "Rust already installed"
    export PATH="$CARGO_BIN:$PATH"
    return
  fi
  log "Installing Rust"
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --no-modify-path
  export PATH="$CARGO_BIN:$PATH"
  cargo --version || error "cargo not found after install"
}

setup_service_user() {
  if [ "$SERVICE_USER" != "relaysms" ]; then
    log "Service user: $SERVICE_USER (invoking user)"
    return
  fi
  if id "relaysms" &>/dev/null; then
    log "Service user: relaysms (already exists)"
  else
    log "Creating service user: relaysms"
    useradd --system --no-create-home --shell /usr/sbin/nologin relaysms
  fi
}

clone_repository() {
  log "Cloning repository"
  # -c scopes the SSH-to-HTTPS rewrite to this command, not global git config.
  if [ -d "$INSTALL_DIR/.git" ]; then
    log "Repository exists, updating"
    cd "$INSTALL_DIR"
    git -c url."https://github.com/".insteadOf="git@github.com:" fetch origin
    git checkout "$BRANCH"
    git -c url."https://github.com/".insteadOf="git@github.com:" pull origin "$BRANCH"
    log "Updating submodules"
    git submodule update --init --recursive
  else
    mkdir -p "$(dirname "$INSTALL_DIR")"
    log "Cloning with submodules"
    git -c url."https://github.com/".insteadOf="git@github.com:" \
      clone --recurse-submodules -b "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
  fi
  # Git refuses to clone into a pre-existing non-empty dir, so this can't
  # move earlier -- $INSTALL_DIR is only guaranteed to exist past this point.
  echo "$INSTANCE_NAME" >"$INSTALL_DIR/.instance-name"
}

setup_virtualenv() {
  log "Setting up virtual environment"
  cd "$INSTALL_DIR"
  if [ -d "venv" ]; then
    log "Removing existing venv for a clean rebuild"
    rm -rf venv
  fi
  python3 -m venv venv
  venv/bin/pip install --quiet --upgrade pip
  venv/bin/pip install --quiet -r requirements.txt
}

build_application() {
  log "Building application"
  cd "$INSTALL_DIR"
  export PATH="$CARGO_BIN:$INSTALL_DIR/venv/bin:$PATH"
  make build-setup
}

setup_env() {
  log "Setting up configuration"
  cd "$INSTALL_DIR"
  if [ -f ".env" ]; then
    log ".env already exists, skipping generation"
  else
    [ -f "template.env" ] || error "template.env not found"
    cp template.env .env

    local db_key field_key data_key
    db_key=$(openssl rand -hex 32)
    field_key=$(openssl rand -hex 32)
    data_key=$(openssl rand -hex 32)
    sed -i "s|^DATABASE_ENCRYPTION_ENABLED=.*|DATABASE_ENCRYPTION_ENABLED=true|" .env
    sed -i "s|^DATABASE_FIELD_ENCRYPTION_ENABLED=.*|DATABASE_FIELD_ENCRYPTION_ENABLED=true|" .env
    sed -i "s|^DATABASE_ENCRYPTION_KEY=.*|DATABASE_ENCRYPTION_KEY=$db_key|" .env
    sed -i "s|^DATABASE_FIELD_ENCRYPTION_KEY=.*|DATABASE_FIELD_ENCRYPTION_KEY=$field_key|" .env
    sed -i "s|^DATA_ENCRYPTION_KEY=.*|DATA_ENCRYPTION_KEY=$data_key|" .env
    log ".env created with auto-generated encryption keys"
    log "Edit $INSTALL_DIR/.env before starting services"
  fi

  chown "root:$SERVICE_USER" .env
  chmod 640 .env
}

resolve_app_directories() {
  local envfile="$INSTALL_DIR/.env"
  [ -f "$envfile" ] || error ".env not found"

  local sqlite_path celery_broker_path celery_result_path celery_beat_path
  local adapters_dir adapters_venv adapters_assets registry_file
  local gateway_clients_registry_file
  sqlite_path=$(read_env_var "SQLITE_DATABASE_PATH" "$envfile")
  celery_broker_path=$(read_env_var "CELERY_BROKER_DB_PATH" "$envfile")
  celery_result_path=$(read_env_var "CELERY_RESULT_DB_PATH" "$envfile")
  celery_beat_path=$(read_env_var "CELERY_BEAT_SCHEDULE_PATH" "$envfile")
  adapters_dir=$(read_env_var "PLATFORMS_ADAPTERS_DIR" "$envfile")
  adapters_venv=$(read_env_var "PLATFORMS_ADAPTERS_VENV_DIR" "$envfile")
  adapters_assets=$(read_env_var "PLATFORMS_ADAPTERS_ASSETS_DIR" "$envfile")
  registry_file=$(read_env_var "PLATFORMS_REGISTRY_FILE" "$envfile")
  gateway_clients_registry_file=$(read_env_var "GATEWAY_CLIENTS_REGISTRY_FILE" "$envfile")

  RW_DIRS=()

  if [ -n "$sqlite_path" ] && [ "$sqlite_path" != ":memory:" ]; then
    _resolve_dir "$(dirname "$sqlite_path")"
  fi
  [ -n "$celery_broker_path" ] && _resolve_dir "$(dirname "$celery_broker_path")"
  [ -n "$celery_result_path" ] && _resolve_dir "$(dirname "$celery_result_path")"
  [ -n "$celery_beat_path" ] && _resolve_dir "$(dirname "$celery_beat_path")"
  _resolve_dir "$adapters_dir"
  _resolve_dir "$adapters_venv"
  _resolve_dir "$adapters_assets"
  [ -n "$registry_file" ] && _resolve_dir "$(dirname "$registry_file")"
  [ -n "$gateway_clients_registry_file" ] && _resolve_dir "$(dirname "$gateway_clients_registry_file")"

  return 0
}

create_app_directories() {
  log "Creating application directories"
  resolve_app_directories

  local dir
  for dir in "${RW_DIRS[@]}"; do
    mkdir -p "$dir"
    chown "$SERVICE_USER:" "$dir"
    chmod 750 "$dir"
    log "  $dir"
  done
}

run_migrations() {
  log "Running database migrations"
  sudo -u "$SERVICE_USER" bash -c "
    set -a
    # shellcheck disable=SC1091
    . '$INSTALL_DIR/.env'
    set +a
    cd '$INSTALL_DIR'
    PATH='$INSTALL_DIR/venv/bin:$PATH' make migrate-up
  "
}

install_services() {
  log "Installing systemd services"
  cd "$INSTALL_DIR"

  resolve_app_directories
  local rw_paths
  rw_paths=$(
    IFS=' '
    echo "${RW_DIRS[*]}"
  )
  [ -n "$rw_paths" ] || error "No application directories resolved for ReadWritePaths"

  # Only matches unit-name references (PartOf=, WantedBy=, ...), never
  # Description=/Documentation=: those read "RelaySMS Publisher" (space,
  # capitalized), not this lowercase-hyphenated pattern.
  local instance_sed_args=()
  if [ -n "$INSTANCE_NAME" ]; then
    instance_sed_args+=(-e "s/relaysms-publisher\.target/$TARGET_UNIT/g")
    local svc_name
    for svc_name in rest grpc worker beat smtp; do
      instance_sed_args+=(
        -e "s/relaysms-publisher-$svc_name\.service/relaysms-publisher-$INSTANCE_NAME-$svc_name.service/g"
        -e "s/relaysms-publisher-$svc_name\$/relaysms-publisher-$INSTANCE_NAME-$svc_name/g"
      )
    done
  fi

  local template dest
  for template in "${ALL_UNIT_TEMPLATES[@]}"; do
    [ -f "$template" ] || error "Service file not found: $template"
    dest=$(unit_name_for "$template")
    # rw_paths/INSTALL_DIR are absolute paths, so / can't be the sed delimiter.
    sed \
      -e "s/User=relaysms/User=$SERVICE_USER/" \
      -e "s#/opt/relaysms/relaysms-publisher#$INSTALL_DIR#g" \
      -e "s#__RW_PATHS__#$rw_paths#" \
      "${instance_sed_args[@]}" \
      "$template" >"/etc/systemd/system/$dest"
  done

  systemctl daemon-reload
  systemctl enable "$TARGET_UNIT"
  for svc in "${SERVICE_UNITS[@]}"; do
    systemctl restart "$svc"
  done
  systemctl start "$TARGET_UNIT"
}

configure_nginx() {
  if [ "${SKIP_NGINX:-0}" = "1" ]; then
    log "Skipping nginx setup (SKIP_NGINX=1)"
    return
  fi

  local site="${SITE_NAME:-}" interactive=0
  if [ -z "$site" ]; then
    interactive=1
    local enable=""
    prompt enable "Configure nginx as a reverse proxy with a Let's Encrypt certificate? [y/N] " "n"
    case "$enable" in
    y | Y | yes | YES) ;;
    *)
      log "Skipping nginx setup"
      return
      ;;
    esac
    prompt site "Domain name for this server (e.g. publisher.example.com): " ""
    [ -n "$site" ] || {
      log "No domain given, skipping nginx setup"
      return
    }
  fi
  # Rejects path separators (path traversal into conf_dest below) and
  # anything that could be read as a certbot flag instead of a domain.
  [[ "$site" =~ ^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$ ]] ||
    error "'$site' is not a valid hostname"

  if ! command -v nginx &>/dev/null || ! command -v certbot &>/dev/null; then
    log "Installing nginx and certbot"
    apt-get install -y --no-install-recommends nginx certbot python3-certbot-nginx
  fi
  mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled

  local envfile="$INSTALL_DIR/.env" rest_port grpc_port
  rest_port=$(read_env_var "PORT" "$envfile")
  grpc_port=$(read_env_var "GRPC_PORT" "$envfile")

  local conf_dest="/etc/nginx/sites-available/${site}.conf"
  if [ -f "$conf_dest" ]; then
    log "nginx site $conf_dest already exists, leaving it untouched"
  else
    [ -f "$INSTALL_DIR/$NGINX_CONF_TEMPLATE" ] || error "$NGINX_CONF_TEMPLATE not found"
    sed \
      -e "s/__SERVER_NAME__/$site/g" \
      -e "s/__REST_PORT__/${rest_port:-16000}/g" \
      -e "s/__GRPC_PORT__/${grpc_port:-6000}/g" \
      "$INSTALL_DIR/$NGINX_CONF_TEMPLATE" >"$conf_dest"
    log "Wrote $conf_dest"
  fi
  ln -sf "$conf_dest" "/etc/nginx/sites-enabled/${site}.conf"

  nginx -t || error "nginx config test failed"
  # Boot persistence is a nicety, not required for this run to succeed.
  systemctl enable nginx &>/dev/null || true
  systemctl reload nginx 2>/dev/null || systemctl restart nginx

  if [ -f "/etc/letsencrypt/live/${site}/fullchain.pem" ]; then
    log "Certificate for $site already exists, skipping certbot"
    return
  fi

  local do_cert="y"
  if [ "$interactive" = "1" ]; then
    prompt do_cert "No certificate found for $site. Obtain one with Certbot now? [Y/n] " "y"
  fi
  case "$do_cert" in
  n | N | no | NO)
    log "Skipping certificate issuance; run manually: certbot --nginx -d $site"
    return
    ;;
  esac

  local email="${LETSENCRYPT_EMAIL:-}"
  if [ -z "$email" ] && [ "$interactive" = "1" ]; then
    prompt email "Email for Let's Encrypt renewal notices (optional): " ""
  fi

  local certbot_args=(--nginx -d "$site" --redirect --agree-tos --non-interactive)
  if [ -n "$email" ]; then
    certbot_args+=(-m "$email")
  else
    certbot_args+=(--register-unsafely-without-email)
  fi

  log "Requesting certificate for $site"
  certbot "${certbot_args[@]}" || error "certbot failed to obtain a certificate for $site"
  log "Certificate installed for $site"
}

configure_database() {
  local dialect="$SETUP_DB"
  if [ -z "$dialect" ]; then
    local choice=""
    prompt_menu choice "Install and provision a database server?" 3 \
      "MySQL:mysql" \
      "PostgreSQL:postgres" \
      "SQLite:sqlite" \
      "Skip:skip"
    case "$choice" in
    mysql) dialect="mysql" ;;
    postgres) dialect="postgres" ;;
    sqlite)
      log "Keeping SQLite"
      return
      ;;
    skip)
      log "Skipping database setup"
      return
      ;;
    esac
  fi

  case "$dialect" in
  mysql | postgres) ;;
  *) error "--setup-db must be 'mysql' or 'postgres', got '$dialect'" ;;
  esac

  if [ "$DB_EXISTING_SET" != "1" ]; then
    local choice=""
    prompt_menu choice "Use an existing $dialect server, or create a new local one?" 1 \
      "New:new" \
      "Existing:existing" \
      "Skip:skip"
    case "$choice" in
    existing) DB_EXISTING=1 ;;
    skip)
      log "Skipping $dialect setup"
      return
      ;;
    *) DB_EXISTING=0 ;;
    esac
  fi

  local args=(--install-dir "$INSTALL_DIR")
  [ -n "$DB_NAME" ] && args+=(--db-name "$DB_NAME")

  if [ "$DB_EXISTING" = "1" ]; then
    args+=(--existing)
    [ -n "$DB_HOST" ] || prompt DB_HOST "Existing $dialect host: " ""
    [ -n "$DB_HOST" ] || error "A host is required to use an existing database"
    [ -n "$DB_USER" ] || prompt DB_USER "Existing $dialect user: " ""
    [ -n "$DB_USER" ] || error "A user is required to use an existing database"
    [ -n "$DB_PASSWORD" ] || prompt_secret DB_PASSWORD "Existing $dialect password: "
    [ -n "$DB_PASSWORD" ] || error "A password is required to use an existing database"
    args+=(--db-host "$DB_HOST" --db-user "$DB_USER" --db-password "$DB_PASSWORD")
    [ -n "$DB_PORT" ] && args+=(--db-port "$DB_PORT")
  else
    [ -n "$DB_USER" ] && args+=(--db-user "$DB_USER")
    [ -n "$DB_PASSWORD" ] && args+=(--db-password "$DB_PASSWORD")
  fi

  log "Setting up $dialect"
  "$INSTALL_DIR/scripts/setup-$dialect.sh" "${args[@]}"
}

configure_broker() {
  local broker="$SETUP_BROKER"
  if [ -z "$broker" ]; then
    local choice=""
    prompt_menu choice "Install and provision a message broker for Celery?" 2 \
      "RabbitMQ:rabbitmq" \
      "SQLite:sqlite" \
      "Skip:skip"
    case "$choice" in
    rabbitmq) broker="rabbitmq" ;;
    sqlite)
      log "Keeping SQLite broker"
      return
      ;;
    skip)
      log "Skipping broker setup"
      return
      ;;
    esac
  fi

  case "$broker" in
  rabbitmq) ;;
  *) error "--setup-broker must be 'rabbitmq', got '$broker'" ;;
  esac

  if [ "$BROKER_EXISTING_SET" != "1" ]; then
    local choice=""
    prompt_menu choice "Use an existing RabbitMQ server, or create a new local one?" 1 \
      "New:new" \
      "Existing:existing" \
      "Skip:skip"
    case "$choice" in
    existing) BROKER_EXISTING=1 ;;
    skip)
      log "Skipping RabbitMQ setup"
      return
      ;;
    *) BROKER_EXISTING=0 ;;
    esac
  fi

  local args=(--install-dir "$INSTALL_DIR")
  [ -n "$BROKER_VHOST" ] && args+=(--broker-vhost "$BROKER_VHOST")

  if [ "$BROKER_EXISTING" = "1" ]; then
    args+=(--existing)
    [ -n "$BROKER_HOST" ] || prompt BROKER_HOST "Existing RabbitMQ host: " ""
    [ -n "$BROKER_HOST" ] || error "A host is required to use an existing broker"
    [ -n "$BROKER_USER" ] || prompt BROKER_USER "Existing RabbitMQ user: " ""
    [ -n "$BROKER_USER" ] || error "A user is required to use an existing broker"
    [ -n "$BROKER_PASSWORD" ] || prompt_secret BROKER_PASSWORD "Existing RabbitMQ password: "
    [ -n "$BROKER_PASSWORD" ] || error "A password is required to use an existing broker"
    args+=(--broker-host "$BROKER_HOST" --broker-user "$BROKER_USER" --broker-password "$BROKER_PASSWORD")
    [ -n "$BROKER_PORT" ] && args+=(--broker-port "$BROKER_PORT")
    [ -n "$BROKER_MGMT_PORT" ] && args+=(--broker-mgmt-port "$BROKER_MGMT_PORT")
  else
    [ -n "$BROKER_USER" ] && args+=(--broker-user "$BROKER_USER")
    [ -n "$BROKER_PASSWORD" ] && args+=(--broker-password "$BROKER_PASSWORD")
  fi

  log "Setting up $broker"
  "$INSTALL_DIR/scripts/setup-$broker.sh" "${args[@]}"
}

configure_observability() {
  local do_setup="$SETUP_OBSERVABILITY"
  if [ -z "$do_setup" ]; then
    local choice=""
    prompt choice "Set up observability (SigNoz + Uptime Kuma)? [y/N] " "n"
    case "$choice" in
    y | Y | yes | YES) do_setup=1 ;;
    *)
      log "Skipping observability setup"
      return
      ;;
    esac
  fi
  [ "$do_setup" = "1" ] || {
    log "Skipping observability setup"
    return
  }

  if [ -z "$OBSERVABILITY_SITE_NAME" ]; then
    local enable=""
    prompt enable "Configure a reverse proxy for observability with a Let's Encrypt certificate? [y/N] " "n"
    case "$enable" in
    y | Y | yes | YES)
      prompt OBSERVABILITY_SITE_NAME "Domain name for observability (e.g. ops.example.com): " ""
      if [ -n "$OBSERVABILITY_SITE_NAME" ] && [ -z "$OBSERVABILITY_LETSENCRYPT_EMAIL" ]; then
        prompt OBSERVABILITY_LETSENCRYPT_EMAIL "Email for Let's Encrypt renewal notices (optional): " ""
      fi
      ;;
    esac
  fi

  local args=(--install-dir "$INSTALL_DIR")
  [ -n "$OBSERVABILITY_SITE_NAME" ] && args+=(--site-name "$OBSERVABILITY_SITE_NAME")
  [ -n "$OBSERVABILITY_LETSENCRYPT_EMAIL" ] &&
    args+=(--letsencrypt-email "$OBSERVABILITY_LETSENCRYPT_EMAIL")

  log "Setting up observability"
  "$INSTALL_DIR/scripts/setup-observability.sh" "${args[@]}"
}

main() {
  parse_args "$@"
  check_root
  git check-ref-format --branch "$BRANCH" &>/dev/null ||
    error "--branch '$BRANCH' is not a valid branch name"
  log "Installing RelaySMS Publisher (service user: $SERVICE_USER)"

  configure_install_dir
  install_system_deps
  install_rust
  setup_service_user
  clone_repository
  setup_virtualenv
  build_application
  setup_env
  configure_database
  configure_broker
  create_app_directories
  run_migrations
  install_services
  configure_nginx
  configure_observability

  log "Installation complete"
  log "  Config : $INSTALL_DIR/.env"
  log "  Manage : $INSTALL_DIR/manage.sh {start|stop|restart|status|logs|update}"
  log "  Platforms : $INSTALL_DIR/platforms.sh {add|remove|update|list|recover|env|shell}"
  log "  Gateway Clients : $INSTALL_DIR/gateway-clients.sh {create|list|update|delete|env|shell}"
}

main "$@"
