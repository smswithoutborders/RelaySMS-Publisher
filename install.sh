#!/bin/bash

set -e

INSTALL_DIR="/opt/relaysms/relaysms-publisher"
SERVICE_NAME="relaysms-publisher"
REPO_URL="https://github.com/smswithoutborders/RelaySMS-Publisher.git"
BRANCH="${BRANCH:-main}"
CARGO_BIN="$HOME/.cargo/bin"

# Determine service user: prefer the invoking user (SUDO_USER) so no extra
# system account is needed. Fall back to a dedicated 'relaysms' system user
# when running directly as root.
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

check_root() { [ "$EUID" -eq 0 ] || error "Run with sudo"; }

# Read a single key from an env file without evaluating the file.
read_env_var() {
  local key="$1" file="$2"
  grep -E "^${key}[[:space:]]*=" "$file" 2>/dev/null | tail -1 |
    sed 's/^[^=]*=//;s/^[[:space:]]*//;s/[[:space:]]*$//'
}

install_system_deps() {
  log "Installing system dependencies"
  apt-get update -qq
  apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv python3-dev \
    build-essential pkg-config \
    libsqlcipher-dev \
    openssl git make curl ||
    error "Failed to install system dependencies"
}

install_rust() {
  if command -v cargo &>/dev/null || [ -x "$CARGO_BIN/cargo" ]; then
    log "Rust already installed"
    export PATH="$CARGO_BIN:$PATH"
    return
  fi
  log "Installing Rust"
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs |
    sh -s -- -y --no-modify-path ||
    error "Rust installation failed"
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
    useradd --system --no-create-home --shell /usr/sbin/nologin relaysms ||
      error "Failed to create service user"
  fi
}

clone_repository() {
  log "Cloning repository"
  if [ -d "$INSTALL_DIR/.git" ]; then
    log "Repository exists, updating"
    cd "$INSTALL_DIR"
    git fetch origin
    git checkout "$BRANCH"
    git pull origin "$BRANCH" || error "Failed to update repository"
    log "Updating submodules"
    git submodule update --init --recursive || error "Failed to update submodules"
  else
    mkdir -p "$(dirname "$INSTALL_DIR")"
    # Rewrite SSH submodule URLs to HTTPS so build works without SSH credentials
    git config --global url."https://github.com/".insteadOf "git@github.com:"
    log "Cloning with submodules"
    git clone --recurse-submodules -b "$BRANCH" "$REPO_URL" "$INSTALL_DIR" ||
      error "Failed to clone repository"
  fi
}

setup_virtualenv() {
  log "Setting up virtual environment"
  cd "$INSTALL_DIR"
  [ -d "venv" ] || python3 -m venv venv || error "Failed to create venv"
  venv/bin/pip install --quiet --upgrade pip || error "Failed to upgrade pip"
  venv/bin/pip install --quiet -r requirements.txt || error "Failed to install Python dependencies"
}

build_application() {
  log "Building application"
  cd "$INSTALL_DIR"
  export PATH="$CARGO_BIN:$INSTALL_DIR/venv/bin:$PATH"
  make build-setup || error "Failed to build application"
}

setup_env() {
  log "Setting up configuration"
  cd "$INSTALL_DIR"
  if [ -f ".env" ]; then
    log ".env already exists, skipping"
    return
  fi
  [ -f "template.env" ] || error "template.env not found"
  cp template.env .env

  local db_key
  db_key=$(openssl rand -hex 32) || error "Failed to generate database encryption key"
  field_key=$(openssl rand -hex 32) || error "Failed to generate database field encryption key"
  data_key=$(openssl rand -hex 32) || error "Failed to generate data encryption key"
  sed -i "s|^DATABASE_ENCRYPTION_ENABLED=.*|DATABASE_ENCRYPTION_ENABLED=true|" .env
  sed -i "s|^DATABASE_FIELD_ENCRYPTION_ENABLED=.*|DATABASE_FIELD_ENCRYPTION_ENABLED=true|" .env
  sed -i "s|^DATABASE_ENCRYPTION_KEY=.*|DATABASE_ENCRYPTION_KEY=$db_key|" .env
  sed -i "s|^DATABASE_FIELD_ENCRYPTION_KEY=.*|DATABASE_FIELD_ENCRYPTION_KEY=$field_key|" .env
  sed -i "s|^DATA_ENCRYPTION_KEY=.*|DATA_ENCRYPTION_KEY=$data_key|" .env

  chown "root:$SERVICE_USER" .env
  chmod 640 .env
  log ".env created with auto-generated encryption keys"
  log "Edit $INSTALL_DIR/.env before starting services"
}

create_app_directories() {
  log "Creating application directories"
  local envfile="$INSTALL_DIR/.env"
  [ -f "$envfile" ] || error ".env not found"

  local sqlite_path adapters_dir adapters_venv adapters_assets
  sqlite_path=$(read_env_var "SQLITE_DATABASE_PATH" "$envfile")
  adapters_dir=$(read_env_var "PLATFORMS_ADAPTERS_DIR" "$envfile")
  adapters_venv=$(read_env_var "PLATFORMS_ADAPTERS_VENV_DIR" "$envfile")
  adapters_assets=$(read_env_var "PLATFORMS_ADAPTERS_ASSETS_DIR" "$envfile")

  _make_dir() {
    local dir="$1" label="${2:-}"
    [ -z "$dir" ] && return
    [[ "$dir" = /* ]] || dir="$INSTALL_DIR/$dir"
    mkdir -p "$dir"
    chown "$SERVICE_USER:" "$dir"
    chmod 750 "$dir"
    log "  $dir${label:+ ($label)}"
  }

  if [ -n "$sqlite_path" ] && [ "$sqlite_path" != ":memory:" ]; then
    _make_dir "$(dirname "$sqlite_path")" "sqlite"
  fi

  _make_dir "$adapters_dir" "adapters"
  _make_dir "$adapters_venv" "adapters venv"
  _make_dir "$adapters_assets" "adapters assets"
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
  " || error "Database migrations failed"
}

install_services() {
  log "Installing systemd services"
  cd "$INSTALL_DIR"
  for svc in relaysms-publisher.target relaysms-publisher-rest.service relaysms-publisher-grpc.service; do
    [ -f "$svc" ] || error "Service file not found: $svc"
    sed "s/User=relaysms/User=$SERVICE_USER/" "$svc" >"/etc/systemd/system/$svc" ||
      error "Failed to install $svc"
  done
  systemctl daemon-reload || error "Failed to reload systemd"
  systemctl enable "$SERVICE_NAME.target" || error "Failed to enable service"
  systemctl start "$SERVICE_NAME.target" || error "Failed to start service"
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
}

main "$@"
