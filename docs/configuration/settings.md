# Settings reference

Settings live in `.env` in the install directory. `template.env` lists each one with its default.

- `sudo ./manage.sh check` reports missing or invalid settings; each service refuses to start on an error in the settings it uses.
- Restart the services after a change: `sudo ./manage.sh restart`.
- After an update, `sudo ./sync-env.sh` adds the settings from `template.env` that `.env` is missing, and shows the change before writing it.
- On Docker, check with `docker compose exec publisher python -m publisher config check` and apply a change with `docker compose up -d`.

## Server

| Setting | Default | Description |
| --- | --- | --- |
| `HOST` | `127.0.0.1` | REST API address. Docker always binds `0.0.0.0`. |
| `PORT` | `16000` | REST API port |
| `WORKERS` | - | REST API worker processes: `1` by default under `scripts/run.sh`, `4` on Docker. The server install always runs `4`. |
| `GRPC_HOST` | `127.0.0.1` | gRPC address. Docker always binds `0.0.0.0`. |
| `GRPC_PORT` | `6000` | gRPC port |
| `GRPC_MAX_WORKERS` | `10` | gRPC worker threads |
| `GRPC_TLS_ENABLED` | `false` | Serves TLS on `GRPC_PORT` itself; leave off behind nginx ([details](../installation/reverse-proxy.md#grpc-tls-without-nginx)) |
| `GRPC_TLS_CERT_FILE`, `GRPC_TLS_KEY_FILE` | - | Certificate and key. Required when `GRPC_TLS_ENABLED=true`. |
| `NONCE_TTL_SECONDS` | `600` | How far a gRPC request's timestamp may be from the server's clock; nonces are remembered this long to refuse replays |

## Database

See [Database](../installation/database.md). Keys are 64 hex characters; see [Encryption keys](encryption-keys.md).

| Setting | Default | Description |
| --- | --- | --- |
| `DATABASE_DIALECT` | `sqlite` | `sqlite`, `mysql` (MySQL and MariaDB) or `postgres` |
| `SQLITE_DATABASE_PATH` | `data/relaysms.db` | SQLite database file |
| `MYSQL_HOST`, `MYSQL_PORT` | `127.0.0.1`, `3306` | MySQL server |
| `MYSQL_USER`, `MYSQL_PASSWORD` | - | Required for `mysql` |
| `MYSQL_DATABASE` | `relaysms` | Required for `mysql`; created if it doesn't exist |
| `POSTGRES_HOST`, `POSTGRES_PORT` | `127.0.0.1`, `5432` | PostgreSQL server |
| `POSTGRES_USER`, `POSTGRES_PASSWORD` | - | Required for `postgres` |
| `POSTGRES_DATABASE` | `relaysms` | Required for `postgres`; created if it doesn't exist |
| `DATABASE_ENCRYPTION_ENABLED` | `true` (`false` if unset) | Encrypts the SQLite file with SQLCipher. No effect on MySQL or PostgreSQL. |
| `DATABASE_ENCRYPTION_KEY` | - | Required for SQLite when encryption is on |
| `DATABASE_FIELD_ENCRYPTION_ENABLED` | `true` (`false` if unset) | Encrypts linked accounts' platform tokens |
| `DATABASE_FIELD_ENCRYPTION_KEY` | - | Required when field encryption is on |
| `DATA_ENCRYPTION_KEY` | - | Required. Encrypts the server's private keys, and keys the hash that replaces each sender's address. |

## Celery

See [Celery broker](../installation/celery-broker.md).

| Setting | Default | Description |
| --- | --- | --- |
| `CELERY_BROKER_TYPE` | `sqlite` | `sqlite`, `redis` or `rabbitmq` |
| `CELERY_WORKER_CONCURRENCY` | `1` for `sqlite`, else `4` | Tasks the worker runs at once |
| `CELERY_BROKER_DB_PATH`, `CELERY_RESULT_DB_PATH` | `data/celery_broker.db`, `data/celery_results.db` | Broker and result files when `CELERY_BROKER_TYPE=sqlite` |
| `CELERY_REDIS_URL` | `redis://localhost:6379/0` | Broker and result backend when `CELERY_BROKER_TYPE=redis` |
| `CELERY_RABBITMQ_URL` | `amqp://guest:guest@localhost:5672//` | Broker when `CELERY_BROKER_TYPE=rabbitmq` |
| `CELERY_BEAT_SCHEDULE_PATH` | `data/celerybeat-schedule` | Beat's schedule file |
| `CELERY_CLEANUP_CRON` | `0 */3 * * *` | Cron schedule (5 fields, UTC) for deleting incomplete payloads, ended web sessions, and audit events and adapter jobs past retention, and failing abandoned adapter jobs |
| `CELERY_TOKEN_CLEANUP_CRON` | `0 3 * * *` | Cron schedule (5 fields, UTC) for deleting tokens idle past `TOKEN_IDLE_MAX_AGE_DAYS` and revoking them on their platform |

## Retention

| Setting | Default | Description |
| --- | --- | --- |
| `PAYLOAD_SESSION_MAX_AGE_HOURS` | `3` | Hours before an incomplete multi-part payload is discarded |
| `TOKEN_IDLE_MAX_AGE_DAYS` | `90` | Days without use before a linked account's token is deleted and revoked on its platform |
| `AUDIT_RETENTION_DAYS` | `365` | Days to keep audit events and adapter install and update jobs |

## Offline publishing

See [Offline publishing](offline-publishing.md).

| Setting | Default | Description |
| --- | --- | --- |
| `OFFLINE_PUBLISH_ALLOWED_PROTOCOLS` | `smtp` (empty if unset) | Comma-separated protocols whose offline payloads publish: `https`, `smtp`. Empty allows both. |
| `OFFLINE_PUBLISH_SHARED_SECRET` | - | 64 hex characters. Required when `https` is allowed. |

## SMTP transport

See [SMTP transport](smtp-transport.md).

| Setting | Default | Description |
| --- | --- | --- |
| `SMTP_TRANSPORT_ENABLED` | `false` | Runs the email listener |
| `SMTP_IMAP_SERVER`, `SMTP_IMAP_USERNAME`, `SMTP_IMAP_PASSWORD` | - | IMAP host and login. Required when the transport is enabled. |
| `SMTP_IMAP_PORT` | `993` | IMAP port |
| `SMTP_IMAP_MAIL_FOLDER` | `INBOX` | Comma-separated folders to watch, e.g. `INBOX,Spam` |
| `SMTP_TLS_CLIENT_CERTIFICATE`, `SMTP_TLS_CLIENT_KEY` | - | mTLS client certificate and key, if the provider requires one. Set both or neither. |
| `SMTP_ALLOWED_SENDERS` | - | Comma-separated addresses and domains allowed to send. Empty allows nothing. |
| `SMTP_TRUSTED_AUTHSERV_ID` | - | `authserv-id` whose `Authentication-Results` verdicts are trusted, e.g. `mx.google.com`. Required when the transport is enabled. |
| `SMTP_REQUIRE_DKIM`, `SMTP_REQUIRE_SPF` | `true` | Require `dkim=pass` and `spf=pass` |
| `SMTP_VERIFY_DKIM_INDEPENDENTLY` | `false` | Also re-verifies the DKIM signature against DNS |

## Platform adapters

See [Managing adapters](../platforms/manage.md#files). Relative paths are from the install directory.

| Setting | Default | Description |
| --- | --- | --- |
| `PLATFORMS_ADAPTERS_DIR` | `data/platforms/adapters` | Directory for adapters' code |
| `PLATFORMS_ADAPTERS_VENV_DIR` | `data/platforms/venvs` | Directory for adapters' virtualenvs |
| `PLATFORMS_ADAPTERS_CONFIG_DIR` | `data/platforms/config` | Directory for adapters' `credentials.json` files |
| `PLATFORMS_ADAPTERS_STATE_DIR` | `data/platforms/state` | Directory for files adapters write, such as databases |
| `PLATFORMS_GITHUB_ORGS` | - | Comma-separated GitHub orgs administrators may install and update adapters from over the REST API. Empty refuses both; `publisher.sh platforms` is unaffected. |

## REST API access

See [REST API](../reference/rest-api.md#authentication).

| Setting | Default | Description |
| --- | --- | --- |
| `AUTH_WEB_ORIGINS` | - | Comma-separated web client origins allowed to call the API from a browser with a session cookie, e.g. `https://console.example.org`. Must be the same site as the API. Empty when the web client is served from the API's own origin. |
| `AUTH_SESSION_COOKIE_SECURE` | `true` | Sends the session cookie over HTTPS only. Set `false` only for local HTTP development. |
| `AUTH_SESSION_IDLE_MINUTES` | `30` | Minutes of inactivity that end a web session |
| `AUTH_SESSION_MAX_HOURS` | `12` | Hours after login when a web session ends, even if it's active |
| `API_DOCS_ENABLED` | `false` | Serves interactive API docs at `/docs` and the schema at `/openapi.json`. For development. |

## Logging and monitoring

See [Observability](../operating/observability.md).

| Setting | Default | Description |
| --- | --- | --- |
| `LOG_LEVEL` | `info` | `debug`, `info`, `warning`, `error` or `critical` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | - | OTLP collector URL for traces, metrics and logs, e.g. `http://localhost:4317`. Needs `requirements-observability.txt`. Blank turns all three off. |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `grpc` | `grpc` or `http/protobuf` |
| `OTEL_TRACES_SAMPLER`, `OTEL_TRACES_SAMPLER_ARG` | `parentbased_traceidratio`, `1.0` | Which traces to keep, and the fraction kept (`0` to `1`) |
| `OTEL_LOGS_EXPORTER` | `otlp` | `otlp` sends logs to the collector; `none` doesn't |
| `OTEL_PYTHON_LOG_CORRELATION` | `true` | Adds trace and span IDs to log records |
| `UPTIME_KUMA_WORKER_PUSH_URL`, `UPTIME_KUMA_SMTP_PUSH_URL` | - | Uptime Kuma push URLs for the worker and email listener heartbeats. Blank turns them off. |
