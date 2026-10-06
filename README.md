# RelaySMS Publisher

Publish content to online platforms (Gmail, Twitter, Telegram, etc.) using SMS when internet connectivity is unavailable.

## Table of Contents

- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Platform Adapters](#platform-adapters)
- [Gateway Clients](#gateway-clients)
- [Credentials](#credentials)
- [Documentation](#documentation)
- [Testing](#testing)
- [License](#license)

## Requirements

- **Python:** >= 3.12
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

Add `--install-dir PATH` to install somewhere other than `/opt/relaysms/relaysms-publisher`, and `--instance-name NAME` to run a second, independent copy on the same host. See [Running Multiple Instances](INSTALL.md#running-multiple-instances).

Manage services:

```bash
cd /opt/relaysms/relaysms-publisher
./manage.sh {start|stop|restart|status|logs|check|update|nginx}
```

See [INSTALL.md](INSTALL.md) for manual installation and detailed configuration.

### Development

```bash
# Setup environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt
pre-commit install

# Configure
cp template.env .env
# Edit .env as needed

# Build
make build

# Run database migrations
make migrate

# Start gRPC, REST API, Celery worker, and Celery beat together
make run
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for code conventions.

Seed random data:

```bash
python3 -m publisher seed stats --count 5000 --days 90   # publication stats
python3 -m publisher seed creds --count 5                # non-administrator credentials, prints passwords
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
  relaysms-publisher:latest
```

## Configuration

Configure via environment variables in `.env` file:

### Server

```bash
HOST=127.0.0.1                  # REST API host
PORT=16000                      # REST API port
GRPC_HOST=127.0.0.1             # gRPC server host
GRPC_PORT=6000                  # gRPC server port
GRPC_TLS_ENABLED=false          # off behind a TLS-terminating reverse proxy
GRPC_TLS_CERT_FILE=             # certificate file, when TLS is on
GRPC_TLS_KEY_FILE=              # key file, when TLS is on
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
PLATFORMS_ADAPTERS_DIR=data/platforms/adapters
PLATFORMS_ADAPTERS_VENV_DIR=data/platforms/venvs
PLATFORMS_ADAPTERS_ASSETS_DIR=data/platforms/assets
PLATFORMS_GITHUB_ORGS=                # Orgs administrators may install adapters from over the API
```

### Offline Publishing

```bash
OFFLINE_PUBLISH_ALLOWED_PROTOCOLS=      # Comma-separated allowlist of ingestion protocols allowed to publish offline payloads, e.g. smtp,sms (empty allows all)
OFFLINE_PUBLISH_SHARED_SECRET=          # Shared secret required in the "tag" field for offline payloads over https (empty disables the check). 64-char hex (32 bytes).
```

Offline payloads are tagged with the protocol they came in on: `https` for [REST `/publications`](docs/rest.md#publishing), `smtp` for the [SMTP transport](docs/smtp.md), `sms` for the [Twilio transport](docs/rest.md#publishing). If `OFFLINE_PUBLISH_ALLOWED_PROTOCOLS` is set, offline payloads from any other protocol are discarded.

`https` is excluded by default since it's unauthenticated and free to spam. `smtp` and `sms` are allowed because their listeners authenticate the sender first (DKIM + allowlist for `smtp`, signature check for `sms`).

If `OFFLINE_PUBLISH_SHARED_SECRET` is set, offline payloads submitted over `https` must also carry a matching `tag` value in the request body (`PublishContentRequest.tag`).

### Auth

```bash
AUTH_WEB_ORIGINS=                     # Web client origins, comma-separated. Empty if same origin.
AUTH_SESSION_COOKIE_SECURE=true       # false only for local http
AUTH_SESSION_IDLE_MINUTES=30
AUTH_SESSION_MAX_HOURS=12
```

See [Authentication](docs/rest.md#authentication).

### API Docs

```bash
API_DOCS_ENABLED=false                # true on dev servers to serve /docs
```

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
> - Individual adapter READMEs: `data/platforms/adapters/*/README.md`

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

## Credentials

Logins for the REST API, each with scopes. One holding every scope is an administrator. Also manageable over the [REST API](docs/rest.md#managing-credentials).

```bash
./publisher.sh creds scopes                                          # list scopes
./publisher.sh creds create --username ops --administrator           # prints the password once
./publisher.sh creds create --username analyst --scope stats:publications:read
./publisher.sh creds set-scopes --username analyst --scope stats:publications:read --scope stats:publications:reasons
./publisher.sh creds list
./publisher.sh creds reset-password --username analyst
./publisher.sh creds disable --username analyst
./publisher.sh creds enable --username analyst
./publisher.sh creds revoke-sessions --username analyst
./publisher.sh creds delete --username analyst
```

## Documentation

- [Installation Guide](INSTALL.md) - Detailed setup instructions
- [gRPC API](docs/grpc.md) - gRPC interface documentation
- [REST API](docs/rest.md) - REST API guide, with the [OpenAPI reference](docs/openapi.json)
- [SMTP Transport](docs/smtp.md) - Publishing payloads sent by email
- [Platform Adapters](platforms/README.md) - Extending functionality
- [Gateway Clients](gateway_clients/README.md) - Managing the gateway client registry
- [Observability](observability/README.md) - Tracing, metrics, logs, uptime monitoring
- [Reference Client](tools/README.md) - Exercising the gRPC and REST flows by hand
- [Contributing](CONTRIBUTING.md) - Setup, workflow, conventions and testing

## Testing

```bash
make test     # test suite, also run by the pre-push hook
make check    # formatting, lint, types and shell checks
```

CI runs both on every pull request.

## License

Licensed under the GNU General Public License (GPL) v3. See [LICENSE](LICENSE.md) for details.
