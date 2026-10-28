# Services

The Publisher runs as systemd services, grouped under `relaysms-publisher.target`:

| Service | Runs |
| --- | --- |
| `relaysms-publisher-rest` | REST API |
| `relaysms-publisher-grpc` | gRPC API |
| `relaysms-publisher-worker` | Celery worker: publishes queued payloads |
| `relaysms-publisher-beat` | Celery Beat: schedules cleanups, and the worker heartbeat with Uptime Kuma |
| `relaysms-publisher-smtp` | [Email listener](../configuration/smtp-transport.md); exits at once while `SMTP_TRANSPORT_ENABLED` is off |

The REST API listens on `HOST:PORT` (`127.0.0.1:16000`) and gRPC on `GRPC_HOST:GRPC_PORT` (`127.0.0.1:6000`).

## Is it working?

```bash
sudo ./manage.sh status
curl http://127.0.0.1:16000/health
```

You should see every service active, and `{"status":"ok"}`. To follow publications as they happen:

```bash
sudo ./manage.sh logs --unit worker
```

Each published payload logs `Published via '<PLATFORM>'.`, each failure a line starting `Failed to`, and each offline refusal `Rejected payload:` ([what each means](troubleshooting.md#a-payload-is-accepted-but-never-published)). Credentials with `stats:publications:read` can also query the counts at `GET /v1/stats/publications`.

## manage.sh

Run it from the install directory with `sudo`:

| Command | Does |
| --- | --- |
| `status` | Shows each service's state |
| `logs` | Follows the service logs |
| `start`, `stop`, `restart` | Controls every service together |
| `enable`, `disable` | Starts the services on boot, or stops doing so |
| `update [--migrate]` | Pulls the latest code, rebuilds and restarts the services ([details](upgrading.md)) |
| `migrate` | Applies database migrations |
| `check` | Reports every missing or invalid setting |
| `nginx [<DOMAIN>]` | Renders the nginx site again and reattaches or obtains its certificate ([details](../installation/reverse-proxy.md#on-an-existing-install)) |
| `docs [<DOMAIN>]` | Builds this manual and serves it on its own domain ([details](../installation/server.md#serving-the-manual)) |
| `uninstall` | Removes the services and the install directory, with `.env` and `data/` |

`uninstall` keeps the database and broker servers and the service user.

`logs` takes:

- `-u`, `--unit`: `rest`, `grpc`, `worker`, `beat` or `smtp`; repeatable
- `-n`, `--lines`: how many lines to show
- `-s`, `--since`: a time, such as `"1 hour ago"`
- `--no-follow`: print and exit

For example:

```bash
sudo ./manage.sh logs --unit rest --unit grpc --since "1 hour ago" --lines 200
```

## publisher.sh

`./publisher.sh` runs the admin CLI as the service user, with the virtualenv and `.env`:

```bash
sudo ./publisher.sh --help   # every command
sudo ./publisher.sh env      # install directory, service user and the .env values the CLI uses
sudo ./publisher.sh shell    # a shell as the service user, with .env loaded
```

Use it instead of `python3 -m publisher`: run as another user, the CLI can leave adapter files the services can't read.

## Files

| Path | Holds |
| --- | --- |
| `/opt/relaysms/relaysms-publisher/` | The install |
| `.env` | Settings (`root:<SERVICE_USER>`, mode 640) |
| `data/` | SQLite database, Celery files and adapters (owned by the service user, mode 750) |
| `/etc/systemd/system/relaysms-publisher*` | Service units |
| `/etc/nginx/sites-available/<DOMAIN>.conf` | nginx sites |
