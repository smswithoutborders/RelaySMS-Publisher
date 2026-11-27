# Observability

Self-hosted tracing, metrics and log export (SigNoz) and uptime monitoring (Uptime Kuma) for the Publisher's services. Both are optional; tracing, metrics and log export stay off while `OTEL_EXPORTER_OTLP_ENDPOINT` is blank.

## Set up

During install:

```bash
sudo ./install.sh --setup-observability
```

On an existing install, from the install directory:

```bash
sudo ./scripts/setup-observability.sh
```

| `install.sh` | `setup-observability.sh` | Does |
| --- | --- | --- |
| `--observability-site-name <DOMAIN>` | `--site-name <DOMAIN>` | Puts nginx and a Let's Encrypt certificate in front of SigNoz |
| `--observability-kuma-site-name <DOMAIN>` | `--kuma-site-name <DOMAIN>` | The same for Uptime Kuma, on a different domain |
| None | `--signoz-email`, `--signoz-password` | SigNoz admin account |
| None | `--signoz-smtp-host`, `--signoz-smtp-port`, `--signoz-smtp-username`, `--signoz-smtp-password`, `--signoz-smtp-from` | SMTP relay for SigNoz's email alerts |
| None | `--skip-tracing` | Leaves tracing off |

`scripts/setup-observability.sh --help` lists every flag. The script:

- installs Docker if it's missing;
- writes `observability/signoz/casting.yaml` from its template, binds the SigNoz UI and OTLP ports to `127.0.0.1`, starts SigNoz and creates the admin account;
- starts Uptime Kuma on `127.0.0.1:3001`, or the port you choose;
- installs `requirements-observability.txt` and sets `OTEL_EXPORTER_OTLP_ENDPOINT`, unless given `--skip-tracing`;
- with `--site-name` or `--kuma-site-name`, writes and enables the nginx sites and runs Certbot.

Set retention in the SigNoz UI, under Settings > Workspace > Retention Controls.

## Uptime Kuma monitors

Open Uptime Kuma through its domain, or through an SSH tunnel at <http://localhost:3001>:

```bash
ssh -L 3001:127.0.0.1:3001 <USER>@<HOST>
```

Then add a monitor for each service. Health checks are left out of traces. Passing ones are also left out of the REST access log, and the gRPC API logs them only when `LOG_LEVEL` is `debug`.

### REST

Monitor Type "HTTP(s)", URL `https://<DOMAIN>/health`.

### gRPC

1. Choose Monitor Type "GRPC(S) - Keyword".
2. Set gRPC URL to `<DOMAIN>:443` and turn on Enable TLS.
3. Set Service Name to `grpc.health.v1.Health` and Method to `check`.
4. Set gRPC Body to `{"service":"publisher.v3.Publisher"}` and Keyword to `SERVING`.
5. Paste this into Protobuf:

<details>
<summary>Health check protobuf</summary>

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

</details>

### Worker

Monitor Type "Push", interval just over 60s. Set `UPTIME_KUMA_WORKER_PUSH_URL` in `.env` to the push URL Kuma shows, then restart the services. Beat schedules this heartbeat, so the monitor also goes down when Beat stops.

### SMTP listener

As for the worker, with an interval just over 20s and `UPTIME_KUMA_SMTP_PUSH_URL`.

## Alerts

In the SigNoz UI, go to Alerts > New Alert > Logs, paste a filter below into the search bar, set the threshold to count > 0 over a rolling window, and attach a notification channel. Keep the parentheses: `AND` binds tighter than `OR`.

Publish failures, adapter errors included:

```
service.name = 'relaysms-publisher-worker' AND (body CONTAINS 'Failed to process payload' OR body CONTAINS 'Failed to publish message' OR body CONTAINS 'An unexpected error occurred during task processing')
```

Key management failures:

```
body CONTAINS 'Failed to generate server identity keys' OR body CONTAINS 'Token hash missing'
```

## Turning tracing on and off

To turn tracing on by hand, from the install directory:

```bash
sudo venv/bin/pip install --quiet -r requirements-observability.txt
sudo sed -i 's|^OTEL_EXPORTER_OTLP_ENDPOINT=.*|OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317|' .env
sudo ./manage.sh restart
```

To turn it off, blank `OTEL_EXPORTER_OTLP_ENDPOINT` and restart.

## Linking stats to traces

Each publish attempt's stat keeps its trace ID, if the trace was sampled. `GET /v1/stats/publications` returns it as `trace_id` and filters by it with `?trace_id=<ID>`. Both need the `stats:publications:reasons` [scope](credentials.md#scopes).

To return links with it, set either or both of these in `.env`, in single quotes, then restart the services:

- `TRACE_URL_TEMPLATE`, returned as `trace_url`, such as `https://<OPS_DOMAIN>/trace/{trace_id}`, where `<OPS_DOMAIN>` serves SigNoz.
- `TRACE_LOGS_URL_TEMPLATE`, returned as `trace_logs_url`. For SigNoz, this opens the logs explorer filtered on the trace ID:

  ```text
  https://<OPS_DOMAIN>/logs/logs-explorer?relativeTime=1month&compositeQuery=%257B%2522queryType%2522%253A%2522builder%2522%252C%2522builder%2522%253A%257B%2522queryData%2522%253A%255B%257B%2522dataSource%2522%253A%2522logs%2522%252C%2522queryName%2522%253A%2522A%2522%252C%2522expression%2522%253A%2522A%2522%252C%2522filter%2522%253A%257B%2522expression%2522%253A%2522trace_id%2520%253D%2520%2527{trace_id}%2527%2522%257D%257D%255D%257D%257D
  ```

  Logs older than `relativeTime` don't show. Set it to your log retention, such as `2w` or `30d`.

SigNoz keeps traces and logs for 15 days by default. Links on older stats open an empty page.

## Changing the SigNoz configuration

`observability/signoz/casting.yaml` is generated only once, so updating the Publisher doesn't change a running SigNoz install. To change it, edit `casting.yaml`, then apply it from the install directory:

```bash
sudo foundryctl cast -f observability/signoz/casting.yaml
sudo docker compose \
  -f pours/deployment/compose.yaml \
  -f observability/signoz/docker-compose.override.yml \
  up -d --force-recreate
```

`cast` alone starts the containers without the override's memory limits and hardening. `--force-recreate` also reloads the config files `cast` rewrote, which Compose doesn't detect. Postgres and ClickHouse keep their data.

## Upgrading SigNoz

1. Check the [upgrade path](https://signoz.io/upgrade-path/) for versions you must upgrade through first, and read the migration notes for each release you cross.
2. Back up the metastore: `sudo sh -c 'docker exec relaysms-publisher-signoz-metastore-postgres-0 pg_dump -U signoz signoz > /root/signoz-metastore-$(date +%F).sql'`.
3. Install the foundryctl version that `scripts/setup-observability.sh` sets in `FOUNDRY_VERSION`: `curl -fsSL https://signoz.io/foundry.sh | sudo FOUNDRY_VERSION=<VERSION> FOUNDRY_INSTALL_DIR=/usr/local/bin bash`.
4. Copy the `image:` lines under `signoz` and `ingester` from `observability/signoz/casting.yaml.template` into `casting.yaml`, adding them if they're missing.
5. Apply it as in [Changing the SigNoz configuration](#changing-the-signoz-configuration), then check the version under Settings.

## Setting up by hand

### SigNoz

Needs Docker Engine with the Compose plugin. Set `<VERSION>` to the `FOUNDRY_VERSION` in `scripts/setup-observability.sh`, and `<PASSWORD>` to 12 or more characters, with upper and lower case, a number and a symbol.

```bash
curl -fsSL https://signoz.io/foundry.sh | sudo FOUNDRY_VERSION=<VERSION> FOUNDRY_INSTALL_DIR=/usr/local/bin bash

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
  -d '{"name":"Admin","orgId":"","orgName":"RelaySMS","email":"admin@example.com","password":"<PASSWORD>"}'
```

The template stores SigNoz's metadata in Postgres (`metastore.kind: postgres`). Set `sqlite` for a single node.

### Uptime Kuma

```bash
docker compose -f observability/uptime-kuma/docker-compose.yml up -d
```

### Reverse proxy

```bash
sed -e "s/__SERVER_NAME__/<OPS_DOMAIN>/g" \
    observability/nginx-observability.conf.template |
    sudo tee /etc/nginx/sites-available/<OPS_DOMAIN>.conf >/dev/null
sudo ln -s /etc/nginx/sites-available/<OPS_DOMAIN>.conf /etc/nginx/sites-enabled/

sed -e "s/__SERVER_NAME__/<STATUS_DOMAIN>/g" \
    observability/nginx-uptime-kuma.conf.template |
    sudo tee /etc/nginx/sites-available/<STATUS_DOMAIN>.conf >/dev/null
sudo ln -s /etc/nginx/sites-available/<STATUS_DOMAIN>.conf /etc/nginx/sites-enabled/

sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d <OPS_DOMAIN>
sudo certbot --nginx -d <STATUS_DOMAIN>
```

`<OPS_DOMAIN>` serves SigNoz and `<STATUS_DOMAIN>` serves Uptime Kuma.
