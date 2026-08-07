#!/bin/bash

set -Eeuo pipefail

INSTALL_DIR="/opt/relaysms/relaysms-publisher"
REPO_URL="https://github.com/smswithoutborders/RelaySMS-Publisher.git"
BRANCH="${BRANCH:-main}"
CARGO_BIN="$HOME/.cargo/bin"
DEPS_MARKER="/var/lib/relaysms-publisher-deps-installed"

TARGET_UNIT="relaysms-publisher.target"
SERVICE_UNITS=(
  relaysms-publisher-rest.service
  relaysms-publisher-grpc.service
  relaysms-publisher-worker.service
  relaysms-publisher-beat.service
  relaysms-publisher-smtp.service
)
ALL_UNITS=("$TARGET_UNIT" "${SERVICE_UNITS[@]}")

# Runtime files are owned by the invoking user if run via sudo, otherwise
# a dedicated 'relaysms' user. The build itself still runs as root.
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
# Catches failures not already wrapped in error(), with line context.
on_err() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: aborted at line $1 (last command: $2)" >&2; }
trap 'on_err "$LINENO" "$BASH_COMMAND"' ERR

check_root() { [ "$EUID" -eq 0 ] || error "Run with sudo"; }

# Reads KEY=value from a file without sourcing it. `|| true` on the grep
# stops a no-match from tripping pipefail.
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

# Adds a dir to the global RW_DIRS array, de-duped, relative to INSTALL_DIR.
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
  if [ -f "$DEPS_MARKER" ] && [ "${FORCE_DEPS:-0}" != "1" ]; then
    log "System dependencies already installed, skipping (FORCE_DEPS=1 to force)"
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

# Shared by create_app_directories and install_services so both stay in
# sync with .env.
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

  local svc
  for svc in "${ALL_UNITS[@]}"; do
    [ -f "$svc" ] || error "Service file not found: $svc"
    # # as delimiter, a resolved path could contain a pipe.
    sed \
      -e "s/User=relaysms/User=$SERVICE_USER/" \
      -e "s#__RW_PATHS__#$rw_paths#" \
      "$svc" >"/etc/systemd/system/$svc"
  done

  systemctl daemon-reload
  systemctl enable "$TARGET_UNIT"
  for svc in "${SERVICE_UNITS[@]}"; do
    systemctl restart "$svc"
  done
  systemctl start "$TARGET_UNIT"
}

main() {
  check_root
  log "Installing RelaySMS Publisher (service user: $SERVICE_USER)"

  install_system_deps
  install_rust
  setup_service_user
  clone_repository
  setup_virtualenv
  build_application
  setup_env
  create_app_directories
  run_migrations
  install_services

  log "Installation complete"
  log "  Config : $INSTALL_DIR/.env"
  log "  Manage : $INSTALL_DIR/manage.sh {start|stop|restart|status|logs|update}"
  log "  Platforms : $INSTALL_DIR/platforms.sh {add|remove|update|list|recover|env|shell}"
  log "  Gateway Clients : $INSTALL_DIR/gateway-clients.sh {create|list|update|delete|env|shell}"
}

main "$@"
