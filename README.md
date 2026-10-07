# RelaySMS Publisher

Publishes to online platforms (Gmail, X, Telegram and more) from content sent by SMS, so people can post without an internet connection.

## Contents

- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Install on a server](#install-on-a-server)
- [Manage the services](#manage-the-services)
- [Run with Docker](#run-with-docker)
- [Development](#development)
- [Configuration](#configuration)
- [Platform adapters](#platform-adapters)
- [Gateway clients](#gateway-clients)
- [Credentials](#credentials)
- [Documentation](#documentation)
- [License](#license)

## How it works

1. A user links an account (Gmail, X, ...) through the gRPC API, which stores its token encrypted.
2. Offline, the user's app encrypts the content and sends it by SMS to a gateway client: a phone number that relays SMS to this server.
3. The payload arrives over REST, the Twilio webhook or SMTP and is queued.
4. A Celery worker decrypts it and publishes it through the platform's adapter.

## Requirements

- Ubuntu 24.04 or Debian 13
- Python 3.12 or newer
- A database: SQLite (the default), MySQL 8.0.28 or newer, MariaDB, or PostgreSQL 12 or newer

The installer sets up everything else, including the system packages and Rust.

## Install on a server

1. Run the installer. It installs to `/opt/relaysms/relaysms-publisher`, generates the encryption keys and starts the services under systemd:

   ```bash
   curl -fsSL https://raw.githubusercontent.com/smswithoutborders/RelaySMS-Publisher/main/install.sh | sudo bash
   ```

   With no flags it asks about each option. To choose up front, pass flags after `bash -s --`:

   ```bash
   curl -fsSL https://raw.githubusercontent.com/smswithoutborders/RelaySMS-Publisher/main/install.sh | \
     sudo bash -s -- --site-name publisher.example.com --setup-db postgres
   ```

   | Flag | Does |
   | --- | --- |
   | `--site-name DOMAIN` | Puts nginx with a Let's Encrypt certificate in front; `--skip-nginx` skips it |
   | `--setup-db mysql\|postgres` | Installs the database server and writes its details to `.env` ([details](INSTALL.md#database)) |
   | `--setup-broker rabbitmq` | Uses RabbitMQ instead of SQLite as the Celery broker, for heavier load ([details](INSTALL.md#celery-worker--beat)) |
   | `--setup-observability` | Adds SigNoz and Uptime Kuma ([details](observability/README.md)) |
   | `--install-dir PATH`, `--instance-name NAME` | Installs elsewhere, or a second copy on the same host ([details](INSTALL.md#running-multiple-instances)) |

   `install.sh --help` lists every flag.

2. Go to the install directory and check the configuration:

   ```bash
   cd /opt/relaysms/relaysms-publisher
   sudo ./manage.sh check
   ```

3. Create an administrator credential for the REST API. The password is printed once:

   ```bash
   ./publisher.sh creds create --username ops --administrator
   ```

4. Add the platform adapters you want to offer, then follow each adapter's README to configure it:

   ```bash
   ./publisher.sh platforms add https://github.com/smswithoutborders/gmail-oauth2-adapter
   ```

5. Register the gateway clients that relay SMS to this server:

   ```bash
   ./publisher.sh gateway-clients create --msisdn +237123456789 --protocols https
   ```

6. Check that the services are up:

   ```bash
   sudo ./manage.sh status
   curl http://127.0.0.1:16000/health
   ```

[INSTALL.md](INSTALL.md) covers installing by hand and every setting.

## Manage the services

From the install directory:

| Command | Does |
| --- | --- |
| `sudo ./manage.sh status` | Show each service's state |
| `sudo ./manage.sh logs` | Follow the service logs |
| `sudo ./manage.sh start`, `stop`, `restart` | Control every service together |
| `sudo ./manage.sh update` | Pull the latest code, rebuild and restart; add `--migrate` when the release has migrations |
| `sudo ./manage.sh migrate` | Apply database migrations |
| `sudo ./manage.sh check` | Report every missing or invalid setting |
| `sudo ./manage.sh nginx` | Re-render the nginx site and reattach or obtain its certificate |
| `sudo ./manage.sh uninstall` | Remove the services and the install directory |

See [Service Management](INSTALL.md#service-management) for more.

## Run with Docker

1. Clone the repository with its submodule:

   ```bash
   git clone --recurse-submodules https://github.com/smswithoutborders/RelaySMS-Publisher.git
   cd RelaySMS-Publisher
   ```

2. Create `.env` with fresh encryption keys:

   ```bash
   cp template.env .env
   for key in DATABASE_ENCRYPTION_KEY DATABASE_FIELD_ENCRYPTION_KEY DATA_ENCRYPTION_KEY; do
     sed -i "s/^$key=$/$key=$(openssl rand -hex 32)/" .env
   done
   ```

3. Build and start:

   ```bash
   docker compose up -d --build
   ```

The container applies pending migrations, then starts every service. It listens on `PORT` (16000) and `GRPC_PORT` (6000) from `.env`, and keeps its data in `./data`.

## Development

[CONTRIBUTING.md](CONTRIBUTING.md) walks through setting up, running the services locally, testing and making common changes. In short:

```bash
git clone --recurse-submodules https://github.com/smswithoutborders/RelaySMS-Publisher.git
cd RelaySMS-Publisher
python3 -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt
pre-commit install --install-hooks
make build
```

Then follow [Run locally](CONTRIBUTING.md#run-locally). To fill a local database with sample data:

```bash
python -m publisher seed stats --count 5000 --days 90   # publication stats
python -m publisher seed creds --count 5                # credentials; prints their passwords
```

## Configuration

Settings live in `.env`. `template.env` lists every setting with its default and what it does, and `python -m publisher config check` (or `sudo ./manage.sh check` on a server) reports any that are missing or invalid.

| Settings | Documented in |
| --- | --- |
| Server, database, encryption, Celery, adapters | [INSTALL.md](INSTALL.md#configuration) |
| REST API login and sessions (`AUTH_*`) | [REST API](docs/rest.md#authentication) |
| SMTP transport (`SMTP_*`) | [SMTP Transport](docs/smtp.md#configuration) |
| Twilio SMS transport (`TWILIO_*`) | The comments in `template.env` |
| Tracing, metrics and logs (`OTEL_*`) | [Observability](observability/README.md) |
| Offline publishing (`OFFLINE_PUBLISH_*`) | [Below](#offline-publishing) |

### Offline Publishing

Offline payloads are tagged with the protocol they arrived on: `https` for [REST `/publications`](docs/rest.md#publishing), `smtp` for the [SMTP transport](docs/smtp.md) and `sms` for the [Twilio webhook](docs/rest.md#publishing).

```bash
OFFLINE_PUBLISH_ALLOWED_PROTOCOLS=smtp   # comma-separated; empty allows every protocol
OFFLINE_PUBLISH_SHARED_SECRET=           # 64-char hex; empty disables the check
```

- Offline payloads from a protocol missing from `OFFLINE_PUBLISH_ALLOWED_PROTOCOLS` are discarded. `template.env` allows only `smtp`. `https` is unauthenticated and free to spam, while the SMTP and Twilio listeners authenticate the sender (DKIM and an allowlist for `smtp`, Twilio's signature for `sms`).
- When `OFFLINE_PUBLISH_SHARED_SECRET` is set, offline payloads over `https` must carry it in the request's `tag` field.

## Platform adapters

Each platform is served by an adapter installed from its own repository. `GET /v1/platforms` lists the enabled ones.

- [Gmail](https://github.com/smswithoutborders/gmail-oauth2-adapter)
- [X (formerly Twitter)](https://github.com/smswithoutborders/twitter-oauth2-adapter)
- [Telegram](https://github.com/smswithoutborders/telegram-pnba-adapter)
- [Slack](https://github.com/smswithoutborders/slack-oauth2-adapter)
- [Bluesky](https://github.com/smswithoutborders/bluesky-oauth2-adapter)
- [Mastodon](https://github.com/smswithoutborders/mastodon-oauth2-adapter)

[platforms/README.md](platforms/README.md) covers adding, updating, disabling and removing adapters. Each adapter's README covers its own settings.

## Gateway clients

Gateway clients are the phone numbers that relay SMS to this server. `GET /v1/gateway-clients` lists the enabled ones, and [gateway_clients/README.md](gateway_clients/README.md) covers managing them.

## Credentials

Credentials log in to the REST API, each with its own scopes. One holding every scope is an administrator. They can also be managed over the [REST API](docs/rest.md#managing-credentials).

```bash
./publisher.sh creds scopes                                        # list scopes
./publisher.sh creds create --username ops --administrator         # prints the password once
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

- [Installation Guide](INSTALL.md): installing by hand and every setting
- [REST API](docs/rest.md): publishing, authentication and the [OpenAPI reference](docs/openapi.json)
- [gRPC API](docs/grpc.md): linking accounts and syncing keys
- [SMTP Transport](docs/smtp.md): publishing payloads sent by email
- [Platform Adapters](platforms/README.md): installing and managing adapters
- [Gateway Clients](gateway_clients/README.md): managing gateway clients
- [Observability](observability/README.md): tracing, metrics, logs and uptime monitoring
- [Reference Client](tools/README.md): exercising the gRPC and REST flows by hand
- [Contributing](CONTRIBUTING.md): setup, workflow, conventions and testing

## License

Licensed under the GNU General Public License v3. See [LICENSE](LICENSE.md).
