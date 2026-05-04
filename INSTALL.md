# Installation Guide

## Automated Installation

```bash
sudo ./install.sh
```

This will:

- Install system dependencies
- Clone repository to `/opt/relaysms/relaysms-publisher`
- Setup Python virtualenv
- Compile gRPC protos
- Install and enable systemd services

## Manual Installation

### Install Dependencies

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv python3-dev \
    build-essential libmysqlclient-dev git curl make
```

### Clone Repository

```bash
sudo git clone https://github.com/smswithoutborders/RelaySMS-Publisher.git \
    /opt/relaysms/relaysms-publisher
cd /opt/relaysms/relaysms-publisher
```

### Setup Python Environment

```bash
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt
```

### Build Application

```bash
source venv/bin/activate
make build-setup
```

This will:

- Download vault proto files
- Compile gRPC protos

### Configure Environment

```bash
cp template.env .env
vim .env
```

Edit the `.env` file to configure:

- Database settings (MySQL or SQLite)
- Vault gRPC connection settings
- Server ports and hosts

### Initialize Runtime

```bash
mkdir -p data
set -a && source .env && set +a
# Database will be created automatically on first run
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
./manage.sh update      # Update installation
./manage.sh uninstall   # Remove installation
```

## Configuration

Edit `/opt/relaysms/relaysms-publisher/.env`:

### Server

Configure REST API and gRPC server hosts and ports:

```bash
# REST API
HOST=127.0.0.1
PORT=9000

# gRPC Server
GRPC_HOST=127.0.0.1
GRPC_PORT=6000
GRPC_SSL_PORT=6001
```

### Vault Connection

Configure connection to RelaySMS Vault:

```bash
VAULT_GRPC_HOST=localhost
VAULT_GRPC_PORT=8000
VAULT_GRPC_SSL_PORT=8001
VAULT_GRPC_INTERNAL_PORT=8443
VAULT_GRPC_INTERNAL_SSL_PORT=8444
```

### Database

Choose between MySQL and SQLite:

**SQLite (Default):**

```bash
SQLITE_DATABASE_PATH=data/publisher.sqlite
# Leave MySQL settings empty
```

**MySQL:**

```bash
MYSQL_HOST=127.0.0.1
MYSQL_USER=your_user
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=relaysms_publisher
# Leave SQLITE_DATABASE_PATH empty
```

### Platform Adapters

Configure platform adapter directories:

```bash
PLATFORMS_ADAPTERS_DIR=platforms/adapters
PLATFORMS_ADAPTERS_VENV_DIR=platforms/adapters_venv
PLATFORMS_ADAPTERS_ASSETS_DIR=platforms/adapters_assets
```

For setting up platform adapters and their credentials, see:

- [Platforms Documentation](platforms/README.md)
- Individual adapter READMEs in `platforms/adapters/*/README.md`

Example platform adapters:

- Gmail OAuth2: `platforms/adapters/gmail_oauth2/`
- Twitter OAuth2: `platforms/adapters/twitter_oauth2/`
- Telegram: `platforms/adapters/telegram_pnba/`
- Slack OAuth2: `platforms/adapters/slack_oauth2/`
- Bluesky OAuth2: `platforms/adapters/bluesky_oauth2/`
- Mastodon OAuth2: `platforms/adapters/mastodon_oauth2/`

## Services

- `relaysms-publisher-rest.service` - REST API (default port 16000, configurable via `PORT` env)
- `relaysms-publisher-grpc.service` - gRPC server (default port 6000, configurable via `GRPC_PORT` env)
- `relaysms-publisher.target` - Service group

## File Locations

- Installation: `/opt/relaysms/relaysms-publisher/`
- Configuration: `/opt/relaysms/relaysms-publisher/.env`
- Database: `/opt/relaysms/relaysms-publisher/data/publisher.sqlite`
- Service files: `/etc/systemd/system/relaysms-publisher*`

## External Dependencies

### RelaySMS Vault (Required)

The Publisher requires a running instance of RelaySMS Vault for authentication and token management.

**Installation:**

See [RelaySMS Vault Installation Guide](https://github.com/smswithoutborders/RelaySMS-Vault/blob/main/INSTALL.md)

Quick install:

```bash
curl -fsSL https://raw.githubusercontent.com/smswithoutborders/RelaySMS-Vault/main/install.sh | sudo bash
```

**Configuration:**

Ensure the Vault gRPC server is accessible and update the `VAULT_GRPC_*` variables in the Publisher's `.env` file accordingly.
