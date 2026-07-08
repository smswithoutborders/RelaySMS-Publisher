# Installation Guide

## Quick Install

```bash
curl -fsSL https://raw.githubusercontent.com/smswithoutborders/RelaySMS-Publisher/main/install.sh | sudo bash
```

## Manual Installation

### System Dependencies

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv python3-dev \
    build-essential pkg-config libsqlcipher-dev git make curl
```

### Rust

Required to compile the payload-specs library:

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
source "$HOME/.cargo/env"
```

### Service User

The installer uses the invoking user (`$SUDO_USER`) as the service user when run via `sudo`, so no extra system account is created. When run directly as root, it creates a `relaysms` system user instead.

To create the service user manually (only needed when running directly as root):

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin relaysms
```

### Clone Repository

```bash
# Rewrite SSH submodule URLs to HTTPS (no SSH key required)
git config --global url."https://github.com/".insteadOf "git@github.com:"

sudo git clone --recurse-submodules \
    https://github.com/smswithoutborders/RelaySMS-Publisher.git \
    /opt/relaysms/relaysms-publisher
cd /opt/relaysms/relaysms-publisher
```

### Python Environment

```bash
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt
```

### Build

```bash
make build-setup
```

Downloads and compiles the gRPC protos and payload-specs library.

### Configure

```bash
cp template.env .env
sudo chown root:relaysms .env
sudo chmod 640 .env
```

Edit `.env` (see [Configuration](#configuration) below).

### Application Directories

Create the directories referenced in `.env` and assign ownership to the service user. Replace `$SERVICE_USER` with your username (or `relaysms` if you created that account). By default, the SQLite database, Celery broker/result/beat files all live under `data/` and the adapters live under `platforms/`:

```bash
SERVICE_USER=$(whoami)

# SQLite database + Celery broker/result/beat schedule directory (default)
sudo mkdir -p data
sudo chown "$SERVICE_USER": data && sudo chmod 750 data

# Platform adapter directories
sudo mkdir -p platforms/adapters platforms/adapters_venv platforms/adapters_assets
sudo chown "$SERVICE_USER": platforms/adapters platforms/adapters_venv platforms/adapters_assets
sudo chmod 750 platforms/adapters platforms/adapters_venv platforms/adapters_assets
```

If you changed any of the following path variables in `.env`, create the parent directory of each instead, and see [Install Services](#install-services) below for how to keep the systemd sandbox in sync:

- `SQLITE_DATABASE_PATH`
- `CELERY_BROKER_DB_PATH`, `CELERY_RESULT_DB_PATH` (sqlite broker only)
- `CELERY_BEAT_SCHEDULE_PATH`
- `PLATFORMS_ADAPTERS_DIR`, `PLATFORMS_ADAPTERS_VENV_DIR`, `PLATFORMS_ADAPTERS_ASSETS_DIR`
- `PLATFORMS_REGISTRY_FILE`

### Run Migrations

```bash
set -a && . .env && set +a
make migrate-up
```

### Install Services

The provided service unit files use a `__RW_PATHS__` placeholder for `ReadWritePaths=` instead of a hardcoded path, since all the paths listed above can be changed in `.env`. Substitute it with the actual, resolved directories before installing (`install.sh` does this for you automatically):

```bash
RW_PATHS="$(pwd)/data $(pwd)/platforms/adapters $(pwd)/platforms/adapters_venv $(pwd)/platforms/adapters_assets"

sudo sed \
    -e "s/User=relaysms/User=$SERVICE_USER/" \
    -e "s|__RW_PATHS__|$RW_PATHS|" \
    -i relaysms-publisher-rest.service relaysms-publisher-grpc.service \
       relaysms-publisher-worker.service relaysms-publisher-beat.service

sudo cp relaysms-publisher.target relaysms-publisher-*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable relaysms-publisher.target
sudo systemctl start relaysms-publisher.target
```

> [!WARNING]
> All four services (`rest`, `grpc`, `worker`, `beat`) run with `ProtectSystem=strict` and `ProtectHome=true`, which make the entire filesystem read-only except for paths explicitly listed in `ReadWritePaths`. If you moved the SQLite database, Celery broker/result/beat files, or any adapter directory outside the installation root, add each resolved parent directory to `RW_PATHS` above - a path missing from `ReadWritePaths` will silently fail to write.

## Service Management

```bash
./manage.sh start       # Start all services
./manage.sh stop        # Stop all services
./manage.sh restart     # Restart all services
./manage.sh status      # Check status
./manage.sh logs        # View logs
./manage.sh enable      # Enable on boot
./manage.sh disable     # Disable on boot
./manage.sh update      # Pull latest code and restart
./manage.sh uninstall   # Remove installation
```

## Managing Platform Adapters

Use `platforms.sh` instead of calling `python3 -m platforms.cli` directly. It automatically resolves the install directory, loads `.env`, uses the project venv, and runs as the correct service user so adapter files and the registry never end up with mismatched ownership:

```bash
./platforms.sh add <GITHUB_URL>          # Add an adapter
./platforms.sh remove <NAME>             # Remove an adapter
./platforms.sh update [NAME] [--install] # Update one or all adapters
./platforms.sh list                      # List registered adapters
./platforms.sh recover                   # Rebuild registry from disk
./platforms.sh env                       # Show resolved paths and service user
./platforms.sh shell                     # Open a shell as the service user with .env loaded
```

See [Platforms Documentation](platforms/README.md) for details.

## Configuration

Edit `/opt/relaysms/relaysms-publisher/.env`:

### Server

```bash
HOST=127.0.0.1
PORT=16000

GRPC_HOST=127.0.0.1
GRPC_PORT=6000
GRPC_SSL_PORT=6001
```

### Database

**SQLite (default):**

```bash
DATABASE_DIALECT=sqlite
SQLITE_DATABASE_PATH=data/relaysms.db
```

**MySQL / MariaDB:**

```bash
DATABASE_DIALECT=mysql
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=your_user
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=relaysms_publisher
```

### Database Encryption

The installer auto-generates `DATABASE_ENCRYPTION_KEY`, `DATABASE_FIELD_ENCRYPTION_ENABLED` and `DATA_ENCRYPTION_KEY` using `openssl rand -hex 32`. To generate manually:

```bash
DATA_ENCRYPTION_KEY=<64 hex chars>

DATABASE_ENCRYPTION_ENABLED=true
DATABASE_ENCRYPTION_KEY=<64 hex chars>

DATABASE_FIELD_ENCRYPTION_ENABLED=true
DATABASE_FIELD_ENCRYPTION_KEY=<64 hex chars>
```

> [!NOTE]
>
> - The `DATA ENCRYPTION_KEY` is used to encrypt all private keys regardless of the other encryption settings.
> - The `DATABASE_ENCRYPTION_KEY` is used to encrypt the entire database at rest (SQLite only).
> - The `DATABASE_FIELD_ENCRYPTION_KEY` is used to encrypt specific sensitive fields in the database.

### Celery (Worker / Beat)

```bash
# Broker/backend type: sqlite | redis | rabbitmq
CELERY_BROKER_TYPE=sqlite

# sqlite (default)
CELERY_BROKER_DB_PATH=data/celery_broker.db
CELERY_RESULT_DB_PATH=data/celery_results.db

# redis
# CELERY_REDIS_URL=redis://localhost:6379/0

# rabbitmq
# CELERY_RABBITMQ_URL=amqp://user:pass@localhost:5672//

CELERY_BEAT_SCHEDULE_PATH=data/celerybeat-schedule
```

> [!NOTE]
> If you move any of the `sqlite`-backed Celery paths outside the default `data/` directory, remember to add the new parent directory to `ReadWritePaths` when [installing services](#install-services), since the worker and beat units run under `ProtectSystem=strict`.

### Platform Adapters

```bash
PLATFORMS_ADAPTERS_DIR=platforms/adapters
PLATFORMS_ADAPTERS_VENV_DIR=platforms/adapters_venv
PLATFORMS_ADAPTERS_ASSETS_DIR=platforms/adapters_assets
PLATFORMS_REGISTRY_FILE=platforms/registry.json
```

See [Platforms Documentation](platforms/README.md) and individual adapter READMEs for setup.

> [!NOTE]
> `PLATFORMS_REGISTRY_FILE` is written to by `platforms.cli add|remove|update` and read by the running services at startup. Always run `platforms.cli` as the service user (see [Platforms Documentation](platforms/README.md)) so the registry stays writable and readable across CLI runs and service restarts.

| Path | Description |
|---|---|
| `/opt/relaysms/relaysms-publisher/` | Installation root |
| `/opt/relaysms/relaysms-publisher/.env` | Configuration (root:relaysms, 640) |
| `/opt/relaysms/relaysms-publisher/data/` | SQLite database, Celery broker/result/beat files (relaysms, 750) |
| `/opt/relaysms/relaysms-publisher/platforms/` | Adapter data (relaysms, 750) |
| `/etc/systemd/system/relaysms-publisher*` | Service units |
