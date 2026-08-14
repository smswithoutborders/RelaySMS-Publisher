# Observability

Self-hosted tracing, metrics, log export (SigNoz) and uptime monitoring
(Uptime Kuma) for Publisher's 5 services. Optional:
`OTEL_EXPORTER_OTLP_ENDPOINT` is blank by default.

## Setup

```bash
sudo ./install.sh --setup-observability
# or, against an already-installed Publisher:
sudo ./scripts/setup-observability.sh
```

Flags (full list: `scripts/setup-observability.sh --help`):

| Flag | Does |
| --- | --- |
| `--observability-site-name` (`--site-name`) | Fronts SigNoz with nginx + TLS |
| `--observability-kuma-site-name` (`--kuma-site-name`) | Fronts Kuma with nginx + TLS, different domain from the above |
| `--signoz-email` / `--signoz-password` | SigNoz admin account |
| `--signoz-smtp-host/-port/-username/-password/-from` | SMTP relay for SigNoz's email alert channel |

Prerequisites: Docker Engine + Compose plugin.

## SigNoz

**Automated**: generates `observability/signoz/casting.yaml` from
`casting.yaml.template` (Postgres credentials, ports, SMTP), casts it,
binds the UI/OTLP ports to `127.0.0.1`, fixes the opamp
misconfiguration that keeps the OTLP receiver closed, creates the admin
account.

**Manual**:

```bash
curl -fsSL https://signoz.io/foundry.sh | FOUNDRY_INSTALL_DIR=/usr/local/bin bash

sed \
  -e "s/__POSTGRES_DB__/signoz/" -e "s/__POSTGRES_USER__/signoz/" \
  -e "s/__POSTGRES_PASSWORD__/$(openssl rand -hex 24)/" \
  -e "s/__SIGNOZ_PORT__/8090/" -e "s/__OTLP_GRPC_PORT__/4317/" -e "s/__OTLP_HTTP_PORT__/4318/" \
  -e "s/__SMTP_SMARTHOST__//" -e "s/__SMTP_USERNAME__//" -e "s/__SMTP_PASSWORD__//" -e "s/__SMTP_FROM__//" \
  observability/signoz/casting.yaml.template > observability/signoz/casting.yaml

foundryctl cast -f observability/signoz/casting.yaml
docker compose \
  -f pours/deployment/compose.yaml \
  -f observability/signoz/docker-compose.override.yml \
  up -d

until curl -fs http://127.0.0.1:8090/api/v1/version | grep -q setupCompleted; do sleep 2; done
curl -X POST http://127.0.0.1:8090/api/v1/register \
  -H "Content-Type: application/json" \
  -d '{"name":"Admin","orgId":"","orgName":"RelaySMS","email":"admin@relaysms.local","password":"<12+ chars, upper, lower, number, symbol>"}'
```

`metastore.kind: postgres` is the default in the template; set it to
`sqlite` for a single-node setup. Retention isn't a `casting.yaml` field:
set it in the UI, under Settings > Workspace > Retention Controls.

`casting.yaml` is only generated once: any `--signoz-*` flag (port, SMTP,
etc.) on a rerun is ignored once the file already exists. To change
something on an already-running install, edit the matching line in
`observability/signoz/casting.yaml` directly, then re-run
`foundryctl cast -f observability/signoz/casting.yaml`. This only
recreates the `signoz` container; Postgres and ClickHouse are untouched.

## Uptime Kuma

**Automated**: brings up the container, bound to `127.0.0.1:3001`.

**Manual**: `docker compose -f observability/uptime-kuma/docker-compose.yml up -d`

Reach it through its own reverse-proxy domain (below) or
`ssh -L 3001:127.0.0.1:3001 <user>@<host>`, then
<http://localhost:3001>. Create the admin account on first visit, then add
monitors:

- **REST**: Monitor Type "HTTP(s)", URL `https://<domain>/health`.
- **gRPC**: Monitor Type "GRPC(S) - Keyword". Fields:
  - gRPC URL: `<domain>:443`
  - Enable TLS: on
  - Service Name: `grpc.health.v1.Health`
  - Method: `check`
  - gRPC Body: `{"service":"publisher.v3.Publisher"}`
  - Keyword: `SERVING`
  - Protobuf:

    ```proto
    syntax = "proto3";
    package grpc.health.v1;

    message HealthCheckRequest {
      string service = 1;
    }

    message HealthCheckResponse {
      enum ServingStatus {
        UNKNOWN = 0;
        SERVING = 1;
        NOT_SERVING = 2;
        SERVICE_UNKNOWN = 3;
      }
      ServingStatus status = 1;
    }

    service Health {
      rpc Check(HealthCheckRequest) returns (HealthCheckResponse);
    }
    ```

- **Worker**: Monitor Type "Push", interval just above 60s. Wire the push
  URL Kuma shows into `UPTIME_KUMA_WORKER_PUSH_URL` and
  `./manage.sh restart`.
- **SMTP listener**: same as Worker, interval just above 20s, into
  `UPTIME_KUMA_SMTP_PUSH_URL`.
- **Beat**: Push monitor, optional.

## Reverse proxy

**Automated**: `--site-name`/`--kuma-site-name` on `setup-observability.sh`
write the site files, symlink them, run `certbot`.

**Manual**:

```bash
sed -e "s/__SERVER_NAME__/<your-ops-domain>/g" \
    observability/nginx-observability.conf.template \
    > /etc/nginx/sites-available/<your-ops-domain>.conf
ln -s /etc/nginx/sites-available/<your-ops-domain>.conf /etc/nginx/sites-enabled/

sed -e "s/__SERVER_NAME__/<your-status-domain>/g" \
    observability/nginx-uptime-kuma.conf.template \
    > /etc/nginx/sites-available/<your-status-domain>.conf
ln -s /etc/nginx/sites-available/<your-status-domain>.conf /etc/nginx/sites-enabled/

nginx -t && systemctl reload nginx
certbot --nginx -d <your-ops-domain>
certbot --nginx -d <your-status-domain>
```

## Turning tracing on/off per service

Bare-metal/systemd installs don't have `requirements-observability.txt`
installed by default:

```bash
cd /opt/relaysms/relaysms-publisher
sudo venv/bin/pip install --quiet -r requirements-observability.txt
```

```bash
sudo sed -i 's|^OTEL_EXPORTER_OTLP_ENDPOINT=.*|OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317|' /opt/relaysms/relaysms-publisher/.env
./manage.sh restart
```

Blank the value and restart to turn it back off.

## Alerts

SigNoz UI, Alerts > New Alert > Logs signal, paste the filter, set the threshold
to count > 0 over a rolling window, attach a notification channel.

- **Publish failures**: `service.name=relaysms-publisher-worker`, body
  contains `Failed to process payload`, `Failed to publish message`, or
  `An unexpected error occurred during task processing`
  (`tasks/publication_task.py`).
- **Platform adapter failures**: `service.name=relaysms-publisher-worker`,
  body contains `Subprocess failed`, `Malformed JSON response`,
  `Subprocess execution timed out`, or `Unexpected failure during IPC
  invocation` (`platforms/adapter_ipc_handler.py`).
- **Key management failures**: body contains `Failed to generate server
  identity keys` or `Token hash missing` (`keys.py`).
