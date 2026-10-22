# Services

The Publisher runs as five systemd services, grouped under `relaysms-publisher.target`:

| Service | Runs | Listens on |
| --- | --- | --- |
| `relaysms-publisher-rest` | REST API | `HOST:PORT` (`127.0.0.1:16000`) |
| `relaysms-publisher-grpc` | gRPC API | `GRPC_HOST:GRPC_PORT` (`127.0.0.1:6000`) |
| `relaysms-publisher-worker` | Celery worker: publishes queued payloads | - |
| `relaysms-publisher-beat` | Celery Beat: schedules cleanups, and the worker heartbeat with Uptime Kuma | - |
| `relaysms-publisher-smtp` | [Email listener](../configuration/smtp-transport.md); exits at once while `SMTP_TRANSPORT_ENABLED` is off | - |

## manage.sh

Run it from the install directory with `sudo`:

| Command | Does |
| --- | --- |
| `status` | Shows each service's state |
| `logs` | Follows the service logs |
| `start`, `stop`, `restart` | Controls every service together |
| `enable`, `disable` | Starts the services on boot, or stops doing so |
| `update` | Pulls the latest code, rebuilds and restarts the services |
| `migrate` | Applies database migrations |
| `check` | Reports every missing or invalid setting |
| `nginx [DOMAIN]` | Renders the nginx site again and reattaches or obtains its certificate ([details](../installation/reverse-proxy.md#on-an-existing-install)) |
| `uninstall` | Removes the services and the install directory, with `.env` and `data/`. nginx sites, certificates, database and broker servers, and the service user stay. |

`logs` takes `-u/--unit` (`rest`, `grpc`, `worker`, `beat` or `smtp`; repeatable), `-n/--lines` and `-s/--since`, and `--no-follow` prints and exits:

```bash
sudo ./manage.sh logs --unit rest --unit grpc --since "1 hour ago" --lines 200
```

> [!IMPORTANT]
> Run `update --migrate` to apply the release's database migrations; with none pending it changes nothing. They run after the dependencies are reinstalled and before the services restart.

`update` also checks `.env`. When a setting is invalid, it still restarts every service, then exits with an error; services that use that setting fail to start.

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
| `.env` | Settings (`root:<service user>`, mode 640) |
| `data/` | SQLite database, Celery files and adapters (owned by the service user, mode 750) |
| `/etc/systemd/system/relaysms-publisher*` | Service units |
| `/etc/nginx/sites-available/<domain>.conf` | nginx sites |
