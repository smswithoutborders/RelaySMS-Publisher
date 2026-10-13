# Installation Guide

The [README](README.md#install-on-a-server) covers the one-line installer. This guide covers running several instances, installing by hand, nginx, and every setting.

## Contents

- [Running multiple instances](#running-multiple-instances)
- [Manual installation](#manual-installation)
- [Nginx reverse proxy](#nginx-reverse-proxy)
- [Service management](#service-management)
- [The publisher.sh CLI](#the-publishersh-cli)
- [Configuration](#configuration)

## Running Multiple Instances

Give each copy its own install directory and instance name:

```bash
sudo ./install.sh --install-dir /srv/relaysms-acme --instance-name acme
```

Its units are namespaced (`relaysms-publisher-acme.target`, `relaysms-publisher-acme-rest.service`, ...), and the `manage.sh` in each install directory manages only its own instance. Re-running `install.sh` remembers the name; a different `--instance-name` is rejected.

> [!IMPORTANT]
> Set distinct `PORT` and `GRPC_PORT` values in each instance's `.env`. The installer doesn't assign them.

## Manual Installation

1. Install the system packages:

   ```bash
   sudo apt-get update
   sudo apt-get install -y python3 python3-pip python3-venv python3-dev \
       build-essential pkg-config libsqlcipher-dev libmagic1 git make curl
   ```

2. Install Rust, which builds the payload-specs library:

   ```bash
   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
   source "$HOME/.cargo/env"
   ```

3. Choose the service user. The installer uses the user running `sudo`; run as root, it creates `relaysms`. To create it yourself:

   ```bash
   sudo useradd --system --no-create-home --shell /usr/sbin/nologin relaysms
   ```

4. Clone the repository with its submodule. The `insteadOf` line fetches the submodule over HTTPS, so no SSH key is needed:

   ```bash
   git config --global url."https://github.com/".insteadOf "git@github.com:"
   sudo git clone --recurse-submodules \
       https://github.com/smswithoutborders/RelaySMS-Publisher.git \
       /opt/relaysms/relaysms-publisher
   cd /opt/relaysms/relaysms-publisher
   ```

5. Create the virtualenv and build the gRPC code and payload-specs library:

   ```bash
   python3 -m venv venv
   venv/bin/pip install --upgrade pip
   venv/bin/pip install -r requirements.txt
   make build
   ```

6. Create `.env`, then fill it in (see [Configuration](#configuration)):

   ```bash
   cp template.env .env
   sudo chown root:relaysms .env
   sudo chmod 640 .env
   ```

7. Create the data directories. By default the SQLite database, Celery files and adapters all live under `data/`:

   ```bash
   SERVICE_USER=relaysms   # or your own user
   sudo mkdir -p data/platforms/adapters data/platforms/venvs data/platforms/config data/platforms/state
   sudo chown -R "$SERVICE_USER": data && sudo chmod -R 750 data
   ```

   If `.env` moves any of these paths elsewhere, create their parent directories instead: `SQLITE_DATABASE_PATH`, `CELERY_BROKER_DB_PATH`, `CELERY_RESULT_DB_PATH`, `CELERY_BEAT_SCHEDULE_PATH`, `PLATFORMS_ADAPTERS_DIR`, `PLATFORMS_ADAPTERS_VENV_DIR`, `PLATFORMS_ADAPTERS_CONFIG_DIR`, `PLATFORMS_ADAPTERS_STATE_DIR`.

8. Apply the database migrations:

   ```bash
   make migrate
   ```

9. Install and start the systemd units. They have a `__RW_PATHS__` placeholder for the directories the services may write to:

   ```bash
   RW_PATHS="$(pwd)/data"
   for unit in deploy/systemd/*; do
       sed -e "s/User=relaysms/User=$SERVICE_USER/" \
           -e "s|/opt/relaysms/relaysms-publisher|$(pwd)|g" \
           -e "s|__RW_PATHS__|$RW_PATHS|" \
           "$unit" | sudo tee "/etc/systemd/system/$(basename "$unit")" >/dev/null
   done
   sudo systemctl daemon-reload
   sudo systemctl enable --now relaysms-publisher.target
   ```

> [!WARNING]
> The services run with `ProtectSystem=strict` and `ProtectHome=true`, so everything outside `ReadWritePaths` is read-only. If `.env` moves a path out of `data/`, add its parent directory to `RW_PATHS`, or writes to it fail.

## Nginx Reverse Proxy

`install.sh` can put nginx with a Let's Encrypt certificate in front, using [the template](deploy/nginx/relaysms-publisher-nginx.conf.template). It proxies `/` to `PORT` (REST) and `/publisher.v3.Publisher` to `GRPC_PORT` (gRPC).

| Flag | Does |
| --- | --- |
| `--site-name DOMAIN` | Sets up nginx for this domain without asking |
| `--letsencrypt-email EMAIL` | Email for Certbot renewal notices (optional) |
| `--skip-nginx` | Skips nginx, even when run interactively |

```bash
curl -fsSL https://raw.githubusercontent.com/smswithoutborders/RelaySMS-Publisher/main/install.sh | \
    sudo bash -s -- --site-name publisher.example.com --letsencrypt-email you@example.com
```

Re-running it leaves an existing site file alone and skips Certbot when the domain already has a certificate. To set it up by hand:

```bash
sudo apt-get install -y nginx certbot python3-certbot-nginx
sudo sed -e "s/__SERVER_NAME__/publisher.example.com/g" \
    -e "s/__REST_PORT__/16000/g" -e "s/__GRPC_PORT__/6000/g" \
    deploy/nginx/relaysms-publisher-nginx.conf.template |
    sudo tee /etc/nginx/sites-available/publisher.example.com.conf >/dev/null
sudo ln -s /etc/nginx/sites-available/publisher.example.com.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d publisher.example.com --redirect
```

## Service Management

The [README](README.md#manage-the-services) lists the `manage.sh` commands. Run them from the install directory with `sudo`.

`logs` filters with `-u/--unit` (rest, grpc, worker, beat or smtp; repeatable), `-n/--lines` and `-s/--since`, and `--no-follow` prints and exits:

```bash
./manage.sh logs --unit rest --unit grpc --since "1 hour ago" --lines 200
```

> [!IMPORTANT]
> Add `--migrate` to `update` when a release has migrations. They run after the dependencies are reinstalled and before the services restart.

`update` also checks `.env`. Services restart either way, since each fails only on the settings it uses, but the command exits with an error when a setting is invalid.

`nginx` keeps the previous site file as `<site>.conf.bak` and restores it if the new one fails. Run it after an update that changes the template.

## The publisher.sh CLI

`./publisher.sh` runs the admin CLI (`creds`, `platforms`, `gateway-clients`, `config`) from the install directory, with the venv and `.env`, as the service user.

> [!IMPORTANT]
> Use it instead of `python3 -m publisher`. Run as another user, the CLI can leave adapter files the services can't read.

```bash
./publisher.sh --help   # every command
./publisher.sh env      # resolved paths and service user
./publisher.sh shell    # a shell as the service user with .env loaded
```

[Platform adapters](docs/platforms.md), [gateway clients](docs/gateway-clients.md) and [credentials](README.md#credentials) each have their own guide. Observability is optional; see [observability/README.md](observability/README.md).

## Configuration

Settings live in `.env`; `template.env` documents each one. The common ones:

### Server

```bash
HOST=127.0.0.1
PORT=16000
GRPC_HOST=127.0.0.1
GRPC_PORT=6000
GRPC_TLS_ENABLED=false
```

### Database

SQLite is the default:

```bash
DATABASE_DIALECT=sqlite
SQLITE_DATABASE_PATH=data/relaysms.db
```

For MySQL, MariaDB or PostgreSQL, let a script install the server and create a database and user. Both are safe to re-run and write the connection details to `.env`:

```bash
sudo ./install.sh --setup-db postgres                                   # during install
sudo ./scripts/setup-postgres.sh --db-name relaysms --db-user relaysms  # afterwards
sudo ./scripts/setup-mysql.sh --db-name relaysms --db-user relaysms
```

`--db-password PASS` sets the password instead of generating one. To use a database server you already have, add `--db-existing` with its details. That only checks the connection and writes `.env`; it never changes the server:

```bash
sudo ./install.sh --setup-db postgres --db-existing \
    --db-host db.example.com --db-port 5432 \
    --db-name relaysms --db-user relaysms --db-password 'your-password'
```

Or set it by hand:

```bash
DATABASE_DIALECT=mysql          # or postgres
MYSQL_HOST=127.0.0.1            # POSTGRES_HOST, POSTGRES_PORT, ... for postgres
MYSQL_PORT=3306
MYSQL_USER=your_user
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=relaysms_publisher
```

### Encryption

The installer generates these with `openssl rand -hex 32`:

| Setting | Encrypts |
| --- | --- |
| `DATA_ENCRYPTION_KEY` | Every private key, always |
| `DATABASE_ENCRYPTION_KEY` | The whole database at rest, when `DATABASE_ENCRYPTION_ENABLED=true` (SQLite only) |
| `DATABASE_FIELD_ENCRYPTION_KEY` | Sensitive fields, when `DATABASE_FIELD_ENCRYPTION_ENABLED=true` |

> [!CAUTION]
> Back the keys up with the database. Data encrypted with a lost or changed key can't be read again.

### Celery (Worker and Beat)

The SQLite broker suits light load. For more, use RabbitMQ:

```bash
sudo ./install.sh --setup-broker rabbitmq                                          # during install
sudo ./scripts/setup-rabbitmq.sh --broker-vhost relaysms --broker-user relaysms    # afterwards
```

`--broker-password PASS` sets the password. `--broker-existing` (with `--broker-host`) uses a broker you already have: it checks the credentials against the management API (port `15672`, or `--broker-mgmt-port`) and changes nothing. By hand:

```bash
CELERY_BROKER_TYPE=sqlite        # sqlite | redis | rabbitmq
CELERY_BROKER_DB_PATH=data/celery_broker.db
CELERY_RESULT_DB_PATH=data/celery_results.db
# CELERY_REDIS_URL=redis://localhost:6379/0
# CELERY_RABBITMQ_URL=amqp://user:pass@localhost:5672//
CELERY_BEAT_SCHEDULE_PATH=data/celerybeat-schedule
```

### Platform Adapters

```bash
PLATFORMS_ADAPTERS_DIR=data/platforms/adapters
PLATFORMS_ADAPTERS_VENV_DIR=data/platforms/venvs
PLATFORMS_ADAPTERS_CONFIG_DIR=data/platforms/config   # per-adapter credentials.json
PLATFORMS_ADAPTERS_STATE_DIR=data/platforms/state     # per-adapter databases and other files
PLATFORMS_GITHUB_ORGS=           # orgs administrators may install from over the API
```

### Files

| Path | Holds |
| --- | --- |
| `/opt/relaysms/relaysms-publisher/` | The install |
| `.env` | Configuration (`root:relaysms`, 640) |
| `data/` | SQLite database, Celery files and adapters (service user, 750) |
| `/etc/systemd/system/relaysms-publisher*` | Service units |
