# Observability

Self-hosted tracing, metrics, log export (SigNoz) and uptime monitoring
(Uptime Kuma) for Publisher's 5 services.

Fully optional. `OTEL_EXPORTER_OTLP_ENDPOINT` is blank by default in
`template.env`, and `scripts/otel-wrap.sh` (used by every systemd unit and
`scripts/run.sh`) only enables instrumentation when it's set. Nothing here
is required to install or run Publisher.

## Setup

Fastest path: `--setup-observability` on `install.sh` (or `scripts/setup-observability.sh` standalone against an existing install). It installs Docker and Foundry if missing, brings up SigNoz + Uptime Kuma, and turns on tracing:

```bash
sudo ./install.sh --setup-observability
# or, against an already-installed Publisher:
sudo ./scripts/setup-observability.sh
```

Add `--observability-site-name DOMAIN` (`--site-name` standalone) to front SigNoz with nginx + TLS. Kuma needs a separate domain via `--observability-kuma-site-name` (`--kuma-site-name` standalone) -- see section 3. `--skip-tracing` brings the stack up without touching `.env`. Full flags: `scripts/setup-observability.sh --help`.

The sections below are what that script automates, useful for understanding or customizing a step, or if you're doing this by hand. Manual prerequisites: Docker Engine and the Docker Compose plugin
(<https://docs.docker.com/engine/install/>, <https://docs.docker.com/compose/install/>).

### 1. SigNoz

```bash
# Default install dir (~/.local/bin) isn't reliably on PATH for a
# non-interactive root shell, so pin it.
curl -fsSL https://signoz.io/foundry.sh | FOUNDRY_INSTALL_DIR=/usr/local/bin bash

# Fills in Postgres credentials and ports. Output is gitignored (secrets).
sed \
  -e "s/__POSTGRES_DB__/signoz/" \
  -e "s/__POSTGRES_USER__/signoz/" \
  -e "s/__POSTGRES_PASSWORD__/$(openssl rand -hex 24)/" \
  -e "s/__SIGNOZ_PORT__/8090/" \
  -e "s/__OTLP_GRPC_PORT__/4317/" \
  -e "s/__OTLP_HTTP_PORT__/4318/" \
  observability/signoz/casting.yaml.template > observability/signoz/casting.yaml

# Generates pours/deployment/ and deploys. Run from the repo root.
foundryctl cast -f observability/signoz/casting.yaml

# cast doesn't know about the resource-limit override; apply it separately.
docker compose \
  -f pours/deployment/compose.yaml \
  -f observability/signoz/docker-compose.override.yml \
  up -d

# Until an org exists, SigNoz never opens its OTLP receiver.
until curl -fs http://127.0.0.1:8090/api/v1/version | grep -q setupCompleted; do sleep 2; done
curl -X POST http://127.0.0.1:8090/api/v1/register \
  -H "Content-Type: application/json" \
  -d '{"name":"Admin","orgId":"","orgName":"RelaySMS","email":"admin@relaysms.local","password":"<a password with 12+ chars, upper, lower, number, symbol>"}'
```

`casting.yaml.template` uses Postgres as the metastore (Foundry's
recommended backend). For a smaller single-node setup, change
`metastore.kind` to `sqlite` (and drop the `spec.env` block under it,
which only applies to Postgres).

`docker-compose.override.yml` and the `patches`/`ingester` blocks in
`casting.yaml.template` reference exact Foundry-generated service names,
which could drift in a future Foundry release. If `up -d` errors about an
unknown service, recheck with:

```bash
docker compose -f pours/deployment/compose.yaml config --services
```

`setup-observability.sh` asks before creating the admin account, then
prompts for email/password if `--signoz-email`/`--signoz-password` weren't
given (blank answers fall back to the defaults). Credentials are printed
once and not stored anywhere else -- use them to log into the SigNoz UI.

Trace/log retention isn't a `casting.yaml` field: set it after first
login, in the SigNoz UI under Settings > Workspace > Retention Controls,
to keep ClickHouse's disk and memory footprint bounded.

### 2. Uptime Kuma

```bash
docker compose -f observability/uptime-kuma/docker-compose.yml up -d
```

Bound to `127.0.0.1:3001`. Reach it either through its own reverse-proxy
domain (section 3) or by tunneling
(`ssh -L 3001:127.0.0.1:3001 <user>@<host>`, then open
<http://localhost:3001>). Create the admin account on first visit, then
add:

- **REST**: Monitor Type "HTTP(s)", URL `https://<domain>/health`.
- **gRPC**: Kuma has a native gRPC monitor type (look for "gRPC" in the
  Monitor Type dropdown) on the gRPC port; otherwise Monitor Type "TCP
  Port" on the same port as a weaker fallback (proves the port is open,
  not that the service is healthy).
- **Worker**: Monitor Type "Push", interval just above 60s. Kuma shows the
  push URL after saving; wire it in and restart:

  ```bash
  sudo sed -i 's|^UPTIME_KUMA_WORKER_PUSH_URL=.*|UPTIME_KUMA_WORKER_PUSH_URL=<paste-the-push-url>|' /opt/relaysms/relaysms-publisher/.env
  ./manage.sh restart
  ```

- **SMTP listener**: same as Worker, interval just above 20s, into
  `UPTIME_KUMA_SMTP_PUSH_URL`.
- **Beat**: Push monitor, optional (beat scheduling the worker heartbeat is
  already indirect proof it's alive).

### 3. Reverse proxy

Two vhosts, one per domain, separate from
`relaysms-publisher-nginx.conf.template` (the public API). Manual setup:

```bash
# SigNoz: observability/nginx-observability.conf.template -> your ops domain
sed -e "s/__SERVER_NAME__/<your-ops-domain>/g" \
    observability/nginx-observability.conf.template \
    > /etc/nginx/sites-available/<your-ops-domain>.conf
ln -s /etc/nginx/sites-available/<your-ops-domain>.conf /etc/nginx/sites-enabled/

# Uptime Kuma: observability/nginx-uptime-kuma.conf.template -> a different domain
sed -e "s/__SERVER_NAME__/<your-status-domain>/g" \
    observability/nginx-uptime-kuma.conf.template \
    > /etc/nginx/sites-available/<your-status-domain>.conf
ln -s /etc/nginx/sites-available/<your-status-domain>.conf /etc/nginx/sites-enabled/

nginx -t && systemctl reload nginx
certbot --nginx -d <your-ops-domain>
certbot --nginx -d <your-status-domain>
```

Skip either half if you only want one of the two dashboards exposed (the
other stays reachable by SSH tunnel).

## Usage

The Docker image installs everything needed by default; skip straight to setting the endpoint below. For a bare-metal/systemd install, the OTel SDK and instrumentation packages live in `requirements-observability.txt` and aren't installed by default. Install them first:

```bash
cd /opt/relaysms/relaysms-publisher
sudo venv/bin/pip install --quiet -r requirements-observability.txt
```

Then turn tracing/metrics/log export on for a service by setting `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317` in `.env` and restarting it:

```bash
sudo sed -i 's|^OTEL_EXPORTER_OTLP_ENDPOINT=.*|OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317|' /opt/relaysms/relaysms-publisher/.env
./manage.sh restart
```

To turn it back off, blank the value again and restart. Each systemd unit sets its own `OTEL_SERVICE_NAME` so traces are attributed correctly in SigNoz. Logs are correlated to traces automatically (`OTEL_PYTHON_LOG_CORRELATION=true`).
