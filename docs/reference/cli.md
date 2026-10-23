# Command-line tools

| Tool | Runs | Documented in |
| --- | --- | --- |
| `install.sh` | Installs or updates a server install | [Install on a server](../installation/server.md) |
| `manage.sh` | Controls, updates and checks the services | [Services](../operating/services.md#managesh) |
| `publisher.sh` | The admin CLI, as the service user | [Below](#publishersh) |
| `sync-env.sh` | Adds to `.env` the settings `template.env` has and it lacks | [Upgrading](../operating/upgrading.md) |
| `scripts/setup-postgres.sh`, `scripts/setup-mysql.sh` | Sets up a database server | [Database](../installation/database.md) |
| `scripts/setup-rabbitmq.sh` | Sets up a RabbitMQ broker | [Celery broker](../installation/celery-broker.md) |
| `scripts/setup-observability.sh` | Sets up SigNoz and Uptime Kuma | [Observability](../operating/observability.md) |

Run them with `sudo`; all but `install.sh` from the install directory. Each takes `--help`.

## manage.sh

`status`, `logs`, `start`, `stop`, `restart`, `enable`, `disable`, `update`, `migrate`, `check`, `nginx`, `docs`, `uninstall`. See [Services](../operating/services.md#managesh).

## publisher.sh

Runs `python3 -m publisher` as the service user. `sudo ./publisher.sh <GROUP> <COMMAND> --help` describes each command.

| Group | Commands | Documented in |
| --- | --- | --- |
| `creds` | `create`, `list`, `scopes`, `set-scopes`, `reset-password`, `disable`, `enable`, `revoke-sessions`, `delete` | [Credentials and access](../operating/credentials.md) |
| `platforms` | `add`, `update`, `list`, `disable`, `enable`, `remove`, `config show`, `config set`, `setup`, `import`, `exec` | [Managing adapters](../platforms/manage.md) |
| `gateway-clients` | `suggest`, `create`, `list`, `update`, `disable`, `enable`, `delete`, `countries`, `operators`, `mcc-mnc list` | [Managing gateway clients](../gateway-clients/manage.md) |
| `config` | `check` | [Settings reference](../configuration/settings.md) |
| `seed` | `stats`, `creds`, `platforms`, `gateway-clients` | None; fills a development database with sample data |

It also takes `env` and `shell` ([Services](../operating/services.md#publishersh)).
