# Installation Guide

## Quick Install

```bash
curl -fsSL https://raw.githubusercontent.com/smswithoutborders/RelaySMS-Publisher/main/install.sh | sudo bash
```

Installs to `/opt/relaysms/relaysms-publisher` by default. Pass `--install-dir PATH` for a different location, or run without it and you'll be prompted.

### Running Multiple Instances

To run a second, independent copy of Publisher on the same host, give it its own install directory and `--instance-name`:

```bash
sudo ./install.sh --install-dir /srv/relaysms-acme --instance-name acme
```

This namespaces the systemd units (`relaysms-publisher-acme.target`, `relaysms-publisher-acme-rest.service`, ...) so they don't collide with the default instance's, and `manage.sh` inside each install directory manages only its own instance. You still need to give each instance distinct `PORT`/`GRPC_PORT` values in its `.env`: two instances can't share a port on the same host, and `install.sh` doesn't assign this for you.

Re-running `install.sh` against an existing named instance doesn't require repeating `--instance-name`; it's remembered automatically. Passing a *different* `--instance-name` than the instance was set up with is rejected.

Run `install.sh --help` for the full flag list, including `--force-deps` to reinstall system dependencies even if already marked done.

## Manual Installation

### System Dependencies

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv python3-dev \
    build-essential pkg-config libsqlcipher-dev libmagic1 git make curl
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
make build
```

Generates the gRPC code and builds the pinned payload-specs library.

### Configure

```bash
cp template.env .env
sudo chown root:relaysms .env
sudo chmod 640 .env
```

Edit `.env` (see [Configuration](#configuration) below).

### Application Directories

Create the directories referenced in `.env` and assign ownership to the service user. Replace `$SERVICE_USER` with your username (or `relaysms` if you created that account). By default, the SQLite database, Celery broker/result/beat files and the adapters with their registries all live under `data/`:

```bash
SERVICE_USER=$(whoami)

sudo mkdir -p data/platforms/adapters data/platforms/venvs data/platforms/assets data/gateway_clients
sudo chown -R "$SERVICE_USER": data && sudo chmod -R 750 data
```

If you changed any of the following path variables in `.env`, create the parent directory of each instead, and see [Install Services](#install-services) below for how to keep the systemd sandbox in sync:

- `SQLITE_DATABASE_PATH`
- `CELERY_BROKER_DB_PATH`, `CELERY_RESULT_DB_PATH` (sqlite broker only)
- `CELERY_BEAT_SCHEDULE_PATH`
- `PLATFORMS_ADAPTERS_DIR`, `PLATFORMS_ADAPTERS_VENV_DIR`, `PLATFORMS_ADAPTERS_ASSETS_DIR`

### Run Migrations

```bash
make migrate
```

### Install Services

The provided service unit files use a `__RW_PATHS__` placeholder for `ReadWritePaths=` instead of a hardcoded path, since all the paths listed above can be changed in `.env`. Substitute it with the actual, resolved directories before installing (`install.sh` does this for you automatically):

```bash
RW_PATHS="$(pwd)/data"

for unit in deploy/systemd/*; do
    sed -e "s/User=relaysms/User=$SERVICE_USER/" \
        -e "s|/opt/relaysms/relaysms-publisher|$(pwd)|g" \
        -e "s|__RW_PATHS__|$RW_PATHS|" \
        "$unit" | sudo tee "/etc/systemd/system/$(basename "$unit")" >/dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable relaysms-publisher.target
sudo systemctl start relaysms-publisher.target
```

> [!WARNING]
> All five services (`rest`, `grpc`, `worker`, `beat`, `smtp`) run with `ProtectSystem=strict` and `ProtectHome=true`, which make the entire filesystem read-only except for paths explicitly listed in `ReadWritePaths`. If you moved the SQLite database, Celery broker/result/beat files, or any adapter directory outside the installation root, add each resolved parent directory to `RW_PATHS` above. A path missing from `ReadWritePaths` will silently fail to write.

### Nginx Reverse Proxy (optional)

`install.sh` can put the REST API and gRPC server behind nginx with a Let's Encrypt certificate, using [`deploy/nginx/relaysms-publisher-nginx.conf.template`](deploy/nginx/relaysms-publisher-nginx.conf.template). It proxies `/` to `PORT` (REST) and `/publisher.v3.Publisher` to `GRPC_PORT` (gRPC), both read from `.env`, over keepalive upstream connections with the security headers and gzip settings shown in the template.

When run interactively, `install.sh` prompts for whether to configure nginx and for the domain name. For unattended installs, pass flags instead:

- `--site-name DOMAIN` - domain name (e.g. `publisher.example.com`); enables nginx setup non-interactively and skips the prompt
- `--letsencrypt-email EMAIL` - email for Certbot renewal notices (optional; omit to register without one)
- `--skip-nginx` - skip nginx setup entirely, even interactively

Piping `install.sh` through curl still works with flags: put them after `bash -s --`, which tells `bash` to read the script from stdin and treat everything past `--` as its arguments rather than its own options.

```bash
curl -fsSL https://raw.githubusercontent.com/smswithoutborders/RelaySMS-Publisher/main/install.sh | \
    sudo bash -s -- --site-name publisher.example.com --letsencrypt-email you@example.com
```

Run `install.sh --help` for the full flag list.

Re-running `install.sh` is idempotent: it leaves an existing `/etc/nginx/sites-available/<domain>.conf` untouched and skips Certbot if a certificate for the domain already exists.

To configure it manually instead:

```bash
sudo apt-get install -y nginx certbot python3-certbot-nginx

sudo sed \
    -e "s/__SERVER_NAME__/publisher.example.com/g" \
    -e "s/__REST_PORT__/16000/g" \
    -e "s/__GRPC_PORT__/6000/g" \
    deploy/nginx/relaysms-publisher-nginx.conf.template | sudo tee /etc/nginx/sites-available/publisher.example.com.conf >/dev/null

sudo ln -s /etc/nginx/sites-available/publisher.example.com.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

sudo certbot --nginx -d publisher.example.com --redirect
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
./manage.sh check       # Validate .env
./manage.sh migrate     # Run pending database migrations
./manage.sh update      # Pull latest code and restart
./manage.sh nginx       # Re-apply the nginx template and certificate
./manage.sh uninstall   # Remove installation
```

`logs` takes options for filtering: `-u/--unit` (rest|grpc|worker|beat|smtp, repeatable), `-n/--lines`, `-s/--since` (journalctl `--since` syntax), and `--no-follow` to print the selected range and exit instead of tailing. Run `./manage.sh logs --help` for details.

```bash
./manage.sh logs --unit rest --unit grpc --since "1 hour ago" --lines 200
```

`update` takes `-m`/`--migrate` to run database migrations as part of the update, after dependencies are reinstalled and before services restart:

```bash
./manage.sh update --migrate
```

`update` also validates `.env`. Services restart regardless, since each fails only on the settings it uses, but the command exits with an error if any setting is invalid.

`nginx` re-renders the site from `deploy/nginx/relaysms-publisher-nginx.conf.template`, reattaches the Let's Encrypt certificate (or obtains one), enables HTTP/2 for gRPC and reloads nginx. Run it after an update that changes the template. It detects the installed domain, or takes one: `sudo ./manage.sh nginx publisher.example.com`. The previous file is kept as `<site>.conf.bak` and restored if the new config fails.

## Managing Platform Adapters

Use `publisher.sh` instead of calling `python3 -m publisher` directly. It automatically resolves the install directory, loads `.env`, uses the project venv, and runs as the correct service user so adapter files never end up with mismatched ownership:

```bash
./publisher.sh platforms add <GITHUB_URL> [--tag T] # Add an adapter at its newest, or a given, version tag
./publisher.sh platforms remove <NAME> [--force]   # Remove an adapter; --force even with linked accounts
./publisher.sh platforms disable <NAME>            # Hide an adapter from users
./publisher.sh platforms enable <NAME>             # Offer it again
./publisher.sh platforms update [NAME] [--tag T]   # Move one or all adapters to a version tag
./publisher.sh platforms list                      # List registered adapters
./publisher.sh platforms import                    # Register adapter directories not yet in the database
./publisher.sh env                                 # Show resolved paths and service user
./publisher.sh shell                               # Open a shell as the service user with .env loaded
```

See [Platforms Documentation](platforms/README.md) for details.

## Observability (optional)

Off by default, no impact on the steps above. Self-hosted tracing, metrics, log export, and uptime monitoring (SigNoz + Uptime Kuma):

```bash
sudo ./install.sh --setup-observability
# or, against an already-installed Publisher:
sudo ./scripts/setup-observability.sh
```

Installs Docker and Foundry if missing. Add `--observability-site-name DOMAIN` (`--site-name` for the standalone script) for a reverse proxy + TLS. See [observability/README.md](observability/README.md) for the full flag list and what each step does.

## Configuration

Edit `/opt/relaysms/relaysms-publisher/.env`:

### Server

```bash
HOST=127.0.0.1
PORT=16000

GRPC_HOST=127.0.0.1
GRPC_PORT=6000
GRPC_TLS_ENABLED=false
```

### Database

To install MySQL or PostgreSQL and provision a dedicated database/user automatically (idempotent, safe to re-run), use `--setup-db` during install:

```bash
sudo ./install.sh --setup-db postgres
```

Or run the corresponding script directly against an already-installed instance:

```bash
sudo ./scripts/setup-postgres.sh --db-name relaysms --db-user relaysms
# or: sudo ./scripts/setup-mysql.sh --db-name relaysms --db-user relaysms
```

Add `--db-password PASS` to set a specific password instead of a generated one. Both scripts write the resulting `DATABASE_DIALECT` and connection details into `.env` for you; the sections below are for manual configuration instead (e.g. pointing at a database server on another host).

**Already have a database?** Add `--db-existing` (plus `--db-host`, `--db-port` if not local) to connect to it instead of installing/provisioning a new one:

```bash
sudo ./install.sh --setup-db postgres --db-existing \
    --db-host db.example.com --db-port 5432 \
    --db-name relaysms --db-user relaysms --db-password 'your-existing-password'
```

This only validates the connection and writes it to `.env`: it never creates, alters, or drops anything on that server. If the connection or credentials are wrong, the error message tells you to re-run without `--db-existing` to create a new local database instead. Run interactively (no `--setup-db`) and you'll be prompted for "existing" or "new" instead of needing the flags.

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

**PostgreSQL:**

```bash
DATABASE_DIALECT=postgres
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_USER=your_user
POSTGRES_PASSWORD=your_password
POSTGRES_DATABASE=relaysms_publisher
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

SQLite is fine for light load; under heavier throughput, move the broker to RabbitMQ. To install RabbitMQ and provision a dedicated vhost/user automatically (idempotent, safe to re-run), use `--setup-broker` during install:

```bash
sudo ./install.sh --setup-broker rabbitmq
```

Or run the script directly against an already-installed instance:

```bash
sudo ./scripts/setup-rabbitmq.sh --broker-vhost relaysms --broker-user relaysms
```

Add `--broker-password PASS` to set a specific password instead of a generated one. The script writes the resulting `CELERY_BROKER_TYPE` and `CELERY_RABBITMQ_URL` into `.env` for you; the block below is for manual configuration instead (e.g. pointing at a broker on another host).

**Already have a broker?** Add `--broker-existing` (plus `--broker-host` if not local) to connect to it instead:

```bash
sudo ./install.sh --setup-broker rabbitmq --broker-existing \
    --broker-host mq.example.com \
    --broker-vhost relaysms --broker-user relaysms --broker-password 'your-existing-password'
```

This validates the credentials against the broker's management API (default port `15672`, override with `--broker-mgmt-port`) rather than `rabbitmqctl`, since that only talks to a local node. It never creates or modifies anything on the broker. A failed check tells you to re-run without `--broker-existing` to create a new local broker instead.

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
PLATFORMS_ADAPTERS_DIR=data/platforms/adapters
PLATFORMS_ADAPTERS_VENV_DIR=data/platforms/venvs
PLATFORMS_ADAPTERS_ASSETS_DIR=data/platforms/assets
```

See [Platforms Documentation](platforms/README.md) and individual adapter READMEs for setup.

> [!NOTE]
> Adapters are registered in the `platform_adapters` database table. `manage.sh update --migrate` registers existing adapter directories with `publisher.sh platforms import`, after which the old `registry.json` and `PLATFORMS_REGISTRY_FILE` can be deleted.

| Path | Description |
|---|---|
| `/opt/relaysms/relaysms-publisher/` | Installation root |
| `/opt/relaysms/relaysms-publisher/.env` | Configuration (root:relaysms, 640) |
| `/opt/relaysms/relaysms-publisher/data/` | SQLite database, Celery files, adapters and registries (relaysms, 750) |
| `/etc/systemd/system/relaysms-publisher*` | Service units |
