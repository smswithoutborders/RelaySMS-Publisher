# Celery broker

The REST API and the email listener queue publications for the Celery worker through a broker.

| `CELERY_BROKER_TYPE` | Use it for | Worker concurrency by default |
| --- | --- | --- |
| `sqlite` (default) | Light load. Needs no server. | 1 |
| `rabbitmq` | Heavier load | 4 |
| `redis` | Heavier load, with a Redis server you already run | 4 |

`CELERY_WORKER_CONCURRENCY` overrides the concurrency.

## RabbitMQ

A setup script installs RabbitMQ, creates a vhost and user, and writes the broker settings to `.env`:

During install:

```bash
sudo ./install.sh --setup-broker rabbitmq
```

On an existing install, from the install directory:

```bash
sudo ./scripts/setup-rabbitmq.sh --broker-vhost relaysms --broker-user relaysms
```

`--broker-password <PASSWORD>` sets the password instead of generating one. To use a broker you already have, add `--existing` (`--broker-existing` on `install.sh`) with `--broker-host`. The script checks the credentials against the management API (port `15672`, or `--broker-mgmt-port`) and changes nothing on the broker.

## By hand

For RabbitMQ, in `.env`:

```bash
CELERY_BROKER_TYPE=rabbitmq
CELERY_RABBITMQ_URL=amqp://relaysms:<PASSWORD>@localhost:5672/relaysms
```

For Redis:

```bash
CELERY_BROKER_TYPE=redis
CELERY_REDIS_URL=redis://localhost:6379/0
```

Then restart the services with `sudo ./manage.sh restart`.
