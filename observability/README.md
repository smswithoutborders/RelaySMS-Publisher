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

Add `--observability-site-name DOMAIN` (`--site-name` for the standalone script) to also front both dashboards with nginx + TLS, e.g. `--observability-site-name ops.example.com`. `--skip-tracing` brings the stack up without touching `.env`. Run `scripts/setup-observability.sh --help` for the full flag list.

The sections below are what that script automates, useful for understanding or customizing a step, or if you're doing this by hand. Manual prerequisites: Docker Engine and the Docker Compose plugin
(<https://docs.docker.com/engine/install/>, <https://docs.docker.com/compose/install/>).

### 1. SigNoz

```bash
# Install foundryctl (one-time). Pin the install dir: the default
# (~/.local/bin) isn't reliably on PATH for a non-interactive root shell.
curl -fsSL https://signoz.io/foundry.sh | FOUNDRY_INSTALL_DIR=/usr/local/bin bash

# Fill in real Postgres credentials (Foundry defaults all three to the
# literal string "signoz" if left unset). Contains secrets; gitignored.
sed \
  -e "s/__POSTGRES_DB__/signoz/" \
  -e "s/__POSTGRES_USER__/signoz/" \
  -e "s/__POSTGRES_PASSWORD__/$(openssl rand -hex 24)/" \
  observability/signoz/casting.yaml.template > observability/signoz/casting.yaml

# Generates pours/deployment/ and deploys directly, not a dry run.
# Run from the repo root.
foundryctl cast -f observability/signoz/casting.yaml

# cast doesn't know about the resource-limit override; apply it separately.
docker compose \
  -f pours/deployment/compose.yaml \
  -f observability/signoz/docker-compose.override.yml \
  up -d
```

`casting.yaml.template` uses Postgres as the metastore (Foundry's
recommended backend). For a smaller single-node setup, change
`metastore.kind` to `sqlite` (and drop the `spec.env` block under it,
which only applies to Postgres) before generating `casting.yaml`.

`docker-compose.override.yml`'s service names are specific to this
`casting.yaml` and could drift if Foundry changes its naming scheme in a
future release. If the `up -d` above errors about an unknown service,
recheck with:

```bash
docker compose -f pours/deployment/compose.yaml config --services
```

Set trace/log retention to a short window to keep ClickHouse's disk and
memory footprint bounded: this isn't a `casting.yaml` field, it's
configured after first login, in the SigNoz UI under Settings > Workspace
tab > Retention Controls. Logs and traces offer 15/30/90/180 days or 1
year; click Save on each signal you change.

### 2. Uptime Kuma

```bash
docker compose -f observability/uptime-kuma/docker-compose.yml up -d
```

Open <http://localhost:3001> (or through the reverse proxy) and create the
admin account on first visit. Then add:

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

`observability/nginx-observability.conf.template` is a separate vhost from
`relaysms-publisher-nginx.conf.template`, since these are internal
dashboards and shouldn't share a domain with the public API. Not wired into
`install.sh`; install it manually:

```bash
sed -e "s/__SERVER_NAME__/<your-ops-domain>/g" \
    observability/nginx-observability.conf.template \
    > /etc/nginx/sites-available/<your-ops-domain>.conf
ln -s /etc/nginx/sites-available/<your-ops-domain>.conf /etc/nginx/sites-enabled/
htpasswd -c /etc/nginx/.htpasswd-observability <username>
nginx -t && systemctl reload nginx
certbot --nginx -d <your-ops-domain>
```

The template enables `auth_basic` by default, on top of each tool's own
login. It fronts SigNoz at `/` and Uptime Kuma at `/kuma/`.

## Security checklist

Before exposing anything beyond localhost, confirm:

- `pours/deployment/compose.yaml`: the SigNoz UI (8080) and OTLP receiver
  (4317, 4318) publish on `127.0.0.1`, not `0.0.0.0` (they publish on all
  interfaces by default).
- `observability/signoz/casting.yaml` actually has real Postgres
  credentials, not leftover placeholders from the template
  (`grep POSTGRES_ observability/signoz/casting.yaml` should show real
  values, not `__POSTGRES_DB__`/`__POSTGRES_USER__`/`__POSTGRES_PASSWORD__`).
- `/etc/nginx/.htpasswd-observability` exists and `auth_basic` is active in
  the vhost.
- Both stacks are reachable only via the reverse proxy and TLS, never
  directly on their container ports from outside the host.

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
