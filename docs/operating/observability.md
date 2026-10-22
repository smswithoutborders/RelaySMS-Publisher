# Observability

Self-hosted tracing, metrics and log export (SigNoz) and uptime monitoring (Uptime Kuma) for the Publisher's five services. Both are optional; tracing stays off while `OTEL_EXPORTER_OTLP_ENDPOINT` is blank.

## Setup

```bash
sudo ./install.sh --setup-observability       # during install
sudo ./scripts/setup-observability.sh          # on an existing install
```

| `install.sh` | `setup-observability.sh` | Does |
| --- | --- | --- |
| `--observability-site-name DOMAIN` | `--site-name DOMAIN` | Puts nginx and a Let's Encrypt certificate in front of SigNoz |
| `--observability-kuma-site-name DOMAIN` | `--kuma-site-name DOMAIN` | The same for Uptime Kuma, on a different domain |
| - | `--signoz-email`, `--signoz-password` | SigNoz admin account |
| - | `--signoz-smtp-host`, `-port`, `-username`, `-password`, `-from` | SMTP relay for SigNoz's email alerts |
| - | `--skip-tracing` | Leaves tracing off |

`scripts/setup-observability.sh --help` lists every flag. The script installs Docker if it's missing.

## SigNoz

**Automated**: writes `observability/signoz/casting.yaml` from its template (Postgres credentials, ports, SMTP), binds the UI and OTLP ports to `127.0.0.1`, points the collector's opamp at SigNoz so the OTLP receiver opens, starts SigNoz and creates the admin account.

**Manual** (needs Docker Engine with the Compose plugin):

```bash
curl -fsSL https://signoz.io/foundry.sh | FOUNDRY_INSTALL_DIR=/usr/local/bin bash

sed \
  -e "s/__POSTGRES_DB__/signoz/" -e "s/__POSTGRES_USER__/signoz/" \
  -e "s/__POSTGRES_PASSWORD__/$(openssl rand -hex 24)/" \
  -e "s/__SIGNOZ_PORT__/8090/" -e "s/__OTLP_GRPC_PORT__/4317/" -e "s/__OTLP_HTTP_PORT__/4318/" \
  -e "s/__SMTP_SMARTHOST__//" -e "s/__SMTP_USERNAME__//" -e "s/__SMTP_PASSWORD__//" -e "s/__SMTP_FROM__//" \
  -e "s|__SIGNOZ_EXTERNAL_URL__|http://localhost:8090|" \
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

The template stores SigNoz's metadata in Postgres (`metastore.kind: postgres`); set `sqlite` for a single node. Set retention in the UI, under Settings > Workspace > Retention Controls.

> [!IMPORTANT]
> `casting.yaml` is generated only once. To change a running install, edit `observability/signoz/casting.yaml` and run `foundryctl cast -f observability/signoz/casting.yaml` again. It recreates only the `signoz` container; Postgres and ClickHouse keep their data.

## Uptime Kuma

**Automated**: starts the container on `127.0.0.1:3001`, or the port you choose, which it saves to `observability/uptime-kuma/.env`.

**Manual**: `docker compose -f observability/uptime-kuma/docker-compose.yml up -d`

Open it through its own domain ([below](#reverse-proxy)) or an SSH tunnel (`ssh -L 3001:127.0.0.1:3001 <user>@<host>`, then <http://localhost:3001>). Create the admin account on the first visit, then add these monitors:

- **REST**: Monitor Type "HTTP(s)", URL `https://<domain>/health`.
- **gRPC**: Monitor Type "GRPC(S) - Keyword", with:
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

- **Worker**: Monitor Type "Push", interval just over 60s. Set `UPTIME_KUMA_WORKER_PUSH_URL` in `.env` to the push URL Kuma shows, then run `sudo ./manage.sh restart`. Beat schedules this heartbeat, so the monitor also goes down when Beat stops.
- **SMTP listener**: as for the worker, with an interval just over 20s and `UPTIME_KUMA_SMTP_PUSH_URL`.

## Reverse proxy

**Automated**: `--site-name` and `--kuma-site-name` on `setup-observability.sh` write and enable the nginx sites and run Certbot.

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

## Turning tracing on and off

`setup-observability.sh` installs `requirements-observability.txt` and sets the endpoint unless given `--skip-tracing`. To do it by hand, from the install directory:

```bash
sudo venv/bin/pip install --quiet -r requirements-observability.txt
sudo sed -i 's|^OTEL_EXPORTER_OTLP_ENDPOINT=.*|OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317|' .env
sudo ./manage.sh restart
```

Blank the value and restart to turn tracing off.

## Alerts

In the SigNoz UI, go to Alerts > New Alert > Logs, paste a filter below into the search bar, set the threshold to count > 0 over a rolling window, and attach a notification channel. Keep the parentheses: `AND` binds tighter than `OR`.

- **Publish failures**, adapter errors included:

  ```
  service.name = 'relaysms-publisher-worker' AND (body CONTAINS 'Failed to process payload' OR body CONTAINS 'Failed to publish message' OR body CONTAINS 'An unexpected error occurred during task processing')
  ```

- **Key management failures**:

  ```
  body CONTAINS 'Failed to generate server identity keys' OR body CONTAINS 'Token hash missing'
  ```
