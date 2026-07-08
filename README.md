# RelaySMS Publisher

Publish content to online platforms (Gmail, Twitter, Telegram, etc.) using SMS when internet connectivity is unavailable.

## Table of Contents

- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Platform Adapters](#platform-adapters)
- [Documentation](#documentation)
- [Testing](#testing)
- [License](#license)

## Requirements

- **Python:** >= 3.8.10
- **Database:** MySQL (>= 8.0.28), MariaDB, or SQLite

**Ubuntu Dependencies:**

```bash
sudo apt install python3-dev build-essential libsqlcipher-dev pkg-config make git
```

## Installation

### Production

Quick install:

```bash
curl -fsSL https://raw.githubusercontent.com/smswithoutborders/RelaySMS-Publisher/main/install.sh | sudo bash
```

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
# Build
docker build -t relaysms-publisher:latest .

# Configure
cp template.env .env
# Edit .env as needed

# Run
docker run -d \
  --name relaysms-publisher \
  --env-file .env \
  -p 16000:16000 \
  -p 6000:6000 \
  -v $(pwd)/data:/publisher/data \
  -v $(pwd)/platforms:/publisher/platforms \
  relaysms-publisher:latest
```

The container entrypoint runs pending database migrations, then starts the gRPC server, REST API, Celery worker, and Celery beat scheduler together (via `scripts/run.sh`).

> [!TIP]
> `HOST` and `GRPC_HOST` default to `0.0.0.0` inside the container so it's reachable from outside. If your `.env` file explicitly sets `HOST=127.0.0.1` or `GRPC_HOST=127.0.0.1` (e.g. copied unedited from `template.env`), it will override the container default and the services won't be reachable - remove or update those lines in `.env` for Docker deployments.

## Configuration

Configure via environment variables in `.env` file:

### Server

```bash
MODE=production                 # development or production
HOST=127.0.0.1                  # REST API host
PORT=9000                       # REST API port
GRPC_HOST=127.0.0.1            # gRPC server host
GRPC_PORT=6000                  # gRPC server port
GRPC_SSL_PORT=6001             # gRPC SSL port
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
MYSQL_HOST=127.0.0.1
MYSQL_USER=your_user
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=relaysms_publisher
```

### Adapters

```bash
PLATFORMS_ADAPTERS_DIR=platforms/adapters
PLATFORMS_ADAPTERS_VENV_DIR=platforms/adapters_venv
PLATFORMS_ADAPTERS_ASSETS_DIR=platforms/adapters_assets
```

### Logging & Monitoring

```bash
LOG_LEVEL=info                  # debug, info, warning, error
```

**Error Tracking (Optional):**

Publisher supports Sentry-compatible error tracking:

```bash
SENTRY_DSN=https://your-dsn@sentry.io/project-id
SENTRY_TRACES_SAMPLE_RATE=1.0
SENTRY_PROFILES_SAMPLE_RATE=1.0
```

> [!NOTE]
> **Using GlitchTip:** GlitchTip is a Sentry-compatible open-source error tracker. The `SENTRY_DSN` variable works with both Sentry and GlitchTip.
>
> See [GlitchTip Installation Guide](https://glitchtip.com/documentation/install) to set up your own instance.

## Platform Adapters

Supported platforms can be retrieved via the REST API: [/v1/platforms](https://publisher.smswithoutborders.com/v1/platforms). Server identity keys are available at [/v1/server-keys](https://publisher.smswithoutborders.com/v1/server-keys).

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

## Documentation

- [Installation Guide](INSTALL.md) - Detailed setup instructions
- [gRPC API](docs/grpc.md) - gRPC interface documentation
- [REST API](docs/rest.md) - REST API reference
- [Platform Adapters](platforms/README.md) - Extending functionality

## Testing

See [Test Documentation](tests/README.md) for running tests.

## License

Licensed under the GNU General Public License (GPL) v3. See [LICENSE](LICENSE.md) for details.
