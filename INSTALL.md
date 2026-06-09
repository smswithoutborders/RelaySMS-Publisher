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

Create the directories referenced in `.env` and assign ownership to the service user. Replace `$SERVICE_USER` with your username (or `relaysms` if you created that account):

```bash
SERVICE_USER=$(whoami)

# SQLite database directory (default)
sudo mkdir -p data
sudo chown "$SERVICE_USER": data && sudo chmod 750 data

# Platform adapter directories
sudo mkdir -p platforms/adapters platforms/adapters_venv platforms/adapters_assets
sudo chown "$SERVICE_USER": platforms/adapters platforms/adapters_venv platforms/adapters_assets
sudo chmod 750 platforms/adapters platforms/adapters_venv platforms/adapters_assets
```

If you changed any path variables in `.env`, create those directories instead.

### Run Migrations

```bash
set -a && . .env && set +a
make migrate-up
```

### Install Services

```bash
sudo cp relaysms-publisher.target relaysms-publisher-*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable relaysms-publisher.target
sudo systemctl start relaysms-publisher.target
```

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

The installer auto-generates `DATABASE_ENCRYPTION_KEY` using `openssl rand -hex 32` and enables it by default. To generate manually:

```bash
DATABASE_ENCRYPTION_ENABLED=true
DATABASE_ENCRYPTION_KEY=<64 hex chars>
```

### Platform Adapters

```bash
PLATFORMS_ADAPTERS_DIR=platforms/adapters
PLATFORMS_ADAPTERS_VENV_DIR=platforms/adapters_venv
PLATFORMS_ADAPTERS_ASSETS_DIR=platforms/adapters_assets
```

See [Platforms Documentation](platforms/README.md) and individual adapter READMEs for setup.

| Path | Description |
|---|---|
| `/opt/relaysms/relaysms-publisher/` | Installation root |
| `/opt/relaysms/relaysms-publisher/.env` | Configuration (root:relaysms, 640) |
| `/opt/relaysms/relaysms-publisher/data/` | SQLite database (relaysms, 750) |
| `/opt/relaysms/relaysms-publisher/platforms/` | Adapter data (relaysms, 750) |
| `/etc/systemd/system/relaysms-publisher*` | Service units |
