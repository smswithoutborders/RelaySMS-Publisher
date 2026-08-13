# RelaySMS Publisher

Publish content to online platforms (Gmail, Twitter, Telegram, etc.) using SMS when internet connectivity is unavailable.

## Table of Contents

- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Platform Adapters](#platform-adapters)
- [Gateway Clients](#gateway-clients)
- [Documentation](#documentation)
- [Testing](#testing)
- [License](#license)

## Requirements

- **Python:** >= 3.8.10
- **Database:** SQLite, MySQL (>= 8.0.28) / MariaDB, or PostgreSQL (>= 12)

**Ubuntu Dependencies:**

```bash
sudo apt install python3-dev build-essential libsqlcipher-dev libmagic1 pkg-config make git
```

## Installation

### Production

Quick install:

```bash
curl -fsSL https://raw.githubusercontent.com/smswithoutborders/RelaySMS-Publisher/main/install.sh | sudo bash
```

Defaults to SQLite. To install and provision MySQL or PostgreSQL instead, add `--setup-db`:

```bash
curl -fsSL https://raw.githubusercontent.com/smswithoutborders/RelaySMS-Publisher/main/install.sh | \
    sudo bash -s -- --setup-db postgres
```

This installs the database server if it's not already present, creates a dedicated database and user with a generated password, and writes the connection details into `.env`. See [INSTALL.md](INSTALL.md#database) for `--db-name`/`--db-user`/`--db-password` and manual configuration.

Add `--setup-broker rabbitmq` to install RabbitMQ and switch Celery's broker to it (SQLite is fine for light load, but doesn't scale under heavier throughput). See [INSTALL.md](INSTALL.md#celery-worker--beat) for `--broker-vhost`/`--broker-user`/`--broker-password` and manual configuration.

Add `--setup-observability` to also stand up self-hosted tracing/metrics/uptime monitoring (SigNoz + Uptime Kuma). See [Observability](#logging--observability) below.

Run with no flags at all and the installer walks you through each of these choices interactively instead.

Manage services:

```bash
cd /opt/relaysms/relaysms-publisher
./manage.sh {start|stop|restart|status|logs|update}
```

See [INSTALL.md](INSTALL.md) for manual installation and detailed configuration.

### Development

```bash
# Setup environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure
cp template.env .env
# Edit .env as needed

# Build
make build-setup

# Run database migrations
make migrate-up

# Start gRPC, REST API, Celery worker, and Celery beat together
./scripts/run.sh
```

### Docker

```bash
cp template.env .env
# Edit .env as needed

docker compose up -d --build
```

The container entrypoint runs pending database migrations, then starts the gRPC server, REST API, Celery worker, and Celery beat scheduler together (via `scripts/run.sh`). `docker-compose.yml` forces `HOST`/`GRPC_HOST` to `0.0.0.0` regardless of what's in `.env`, since `127.0.0.1` (the `template.env` default, meant for bare-metal) would make the container unreachable from outside.

To customize the exposed ports, set `PORT`/`GRPC_PORT` in `.env` before starting; `docker-compose.yml` reads them for its port mappings. To run without Compose:

```bash
docker build -t relaysms-publisher:latest .
docker run -d \
  --name relaysms-publisher \
  --env-file .env \
  -e HOST=0.0.0.0 -e GRPC_HOST=0.0.0.0 \
  -p 16000:16000 \
  -p 6000:6000 \
  -v $(pwd)/data:/publisher/data \
  -v $(pwd)/platforms:/publisher/platforms \
  -v $(pwd)/gateway_clients:/publisher/gateway_clients \
  relaysms-publisher:latest
```

## Configuration

Configure via environment variables in `.env` file:

### Server

```bash
MODE=production                 # development or production
HOST=127.0.0.1                  # REST API host
PORT=16000                      # REST API port
GRPC_HOST=127.0.0.1             # gRPC server host
GRPC_PORT=6000                  # gRPC server port
GRPC_SSL_PORT=6001              # gRPC SSL port
SSL_CERTIFICATE=                # SSL certificate path (optional)
SSL_KEY=                        # SSL key path (optional)
```

### Database

**SQLite (default):**

```bash
SQLITE_DATABASE_PATH=data/relaysms.db
```

**MySQL:**

```bash
DATABASE_DIALECT=mysql
MYSQL_HOST=127.0.0.1
MYSQL_USER=your_user
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=relaysms_publisher
```

**PostgreSQL:**

```bash
DATABASE_DIALECT=postgres
POSTGRES_HOST=127.0.0.1
POSTGRES_USER=your_user
POSTGRES_PASSWORD=your_password
POSTGRES_DATABASE=relaysms_publisher
```

Whole-database encryption (`DATABASE_ENCRYPTION_ENABLED`) is SQLCipher for SQLite and TDE for MySQL; Postgres has no built-in equivalent, use disk-level encryption on the server instead.

### Adapters

```bash
PLATFORMS_ADAPTERS_DIR=platforms/adapters
PLATFORMS_ADAPTERS_VENV_DIR=platforms/adapters_venv
PLATFORMS_ADAPTERS_ASSETS_DIR=platforms/adapters_assets
```

### Offline Publishing

```bash
OFFLINE_PUBLISH_ALLOWED_PROTOCOLS=      # Comma-separated allowlist of ingestion protocols allowed to publish offline payloads, e.g. smtp,sms (empty allows all)
```

Offline payloads are tagged with the protocol they came in on: `https` for [REST `/publications`](docs/rest.md#7-publish-content), `smtp` for the [SMTP transport](docs/smtp.md), `sms` for the [Twilio transport](docs/rest.md#8-twilio-incoming-sms). If `OFFLINE_PUBLISH_ALLOWED_PROTOCOLS` is set, offline payloads from any other protocol are discarded.

`https` is excluded by default since it's unauthenticated and free to spam. `smtp` and `sms` are allowed because their listeners authenticate the sender first (DKIM + allowlist for `smtp`, signature check for `sms`).

### Logging & Observability

```bash
LOG_LEVEL=info                  # debug, info, warning, error
```

Tracing, metrics, log export, and uptime monitoring are available via a self-hosted [SigNoz](https://signoz.io) + [Uptime Kuma](https://github.com/louislam/uptime-kuma) stack. Off by default (`OTEL_EXPORTER_OTLP_ENDPOINT` is blank in `template.env`), no impact on running Publisher without it. Install with `--setup-observability` (installer flag above) or `sudo ./scripts/setup-observability.sh` against an existing install. See [observability/README.md](observability/README.md) for setup.

## Platform Adapters

Supported platforms can be retrieved via the REST API: `/v1/platforms`.

> [!TIP]
> Each adapter has its own configuration requirements. See:
>
> - [Platform Adapters Documentation](platforms/README.md)
> - Individual adapter READMEs: `platforms/adapters/*/README.md`

**Available adapters:**

- [Gmail](https://github.com/smswithoutborders/gmail-oauth2-adapter)
- [X (formerly Twitter)](https://github.com/smswithoutborders/twitter-oauth2-adapter)
- [Telegram](https://github.com/smswithoutborders/telegram-pnba-adapter)
- [Slack](https://github.com/smswithoutborders/slack-oauth2-adapter)
- [Bluesky](https://github.com/smswithoutborders/bluesky-oauth2-adapter)
- [Mastodon](https://github.com/smswithoutborders/mastodon-oauth2-adapter)

## Gateway Clients

Registered gateway clients can be retrieved via the REST API: `/v1/gateway-clients`.

> [!TIP]
> See [Gateway Clients Documentation](gateway_clients/README.md) for managing the registry.

## Documentation

- [Installation Guide](INSTALL.md) - Detailed setup instructions
- [gRPC API](docs/grpc.md) - gRPC interface documentation
- [REST API](docs/rest.md) - REST API reference
- [Platform Adapters](platforms/README.md) - Extending functionality
- [Gateway Clients](gateway_clients/README.md) - Managing the gateway client registry
- [Observability](observability/README.md) - Tracing, metrics, logs, uptime monitoring

## Testing

See [Test Documentation](tests/README.md) for running tests.

## License

Licensed under the GNU General Public License (GPL) v3. See [LICENSE](LICENSE.md) for details.
