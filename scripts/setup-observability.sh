#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Brings up SigNoz + Uptime Kuma and turns on OTel tracing. Re-runnable.
set -Eeuo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

INSTALL_DIR="/opt/relaysms/relaysms-publisher"
SITE_NAME=""
LETSENCRYPT_EMAIL=""
SKIP_NGINX=0
SKIP_TRACING=0
SIGNOZ_PORT=8080
KUMA_PORT=3001
OTLP_GRPC_PORT=4317
OTLP_HTTP_PORT=4318

usage() {
  cat <<'EOF'
Usage: setup-observability.sh [OPTIONS]

  --install-dir DIR         Publisher install directory (default: /opt/relaysms/relaysms-publisher)
  --site-name DOMAIN        Domain for the observability reverse proxy (optional; skips nginx/TLS if omitted)
  --letsencrypt-email EMAIL Email for Let's Encrypt renewal notices (optional)
  --skip-nginx              Skip the nginx/TLS setup even if --site-name is given
  --skip-tracing            Don't install requirements-observability.txt or turn on OTEL_EXPORTER_OTLP_ENDPOINT
  --signoz-port PORT        Host port for the SigNoz UI (default: 8080)
  --kuma-port PORT          Host port for Uptime Kuma (default: 3001)
  -h, --help                Show this help and exit
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
  --install-dir)
    INSTALL_DIR="$2"
    shift 2
    ;;
  --site-name)
    SITE_NAME="$2"
    shift 2
    ;;
  --letsencrypt-email)
    LETSENCRYPT_EMAIL="$2"
    shift 2
    ;;
  --skip-nginx)
    SKIP_NGINX=1
    shift
    ;;
  --skip-tracing)
    SKIP_TRACING=1
    shift
    ;;
  --signoz-port)
    SIGNOZ_PORT="$2"
    shift 2
    ;;
  --kuma-port)
    KUMA_PORT="$2"
    shift 2
    ;;
  -h | --help)
    usage
    exit 0
    ;;
  *)
    usage
    error "Unknown option: $1"
    ;;
  esac
done

[ "$EUID" -eq 0 ] || error "Run with sudo"
[ -d "$INSTALL_DIR/observability" ] || error "$INSTALL_DIR/observability not found, run install.sh first"
[ -z "$SITE_NAME" ] || validate_hostname "--site-name" "$SITE_NAME"
cd "$INSTALL_DIR"

if ! command -v docker &>/dev/null; then
  log "Installing Docker"
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable docker &>/dev/null || true
systemctl start docker
docker compose version &>/dev/null ||
  error "docker compose plugin not available; install docker-compose-plugin manually"

# True if a container with this exact name is currently running.
container_running() {
  docker ps --filter "name=^$1\$" --filter "status=running" -q 2>/dev/null | grep -q .
}

SIGNOZ_UI_RUNNING=0
container_running relaysms-publisher-signoz-signoz-0 && SIGNOZ_UI_RUNNING=1
KUMA_RUNNING=0
container_running uptime-kuma && KUMA_RUNNING=1
INGESTER_RUNNING=0
container_running relaysms-publisher-signoz-ingester-1 && INGESTER_RUNNING=1

# Loops until the port named by $1 is free or the user opts out (returns
# 1). Non-remappable ports just get re-checked after the user frees them.
resolve_port() {
  local __resultvar="$1" label="$2" remappable="$3" port="${!1}" ack=""
  while ! port_is_free "$port"; do
    log "Port $port ($label) is already in use."
    if [ "$remappable" = "1" ]; then
      prompt port "Enter a different port for $label, or leave blank to skip observability setup entirely: " ""
      [ -n "$port" ] || return 1
    else
      prompt ack "$label is fixed at $port and can't be moved to a different port -- free it up and press enter to retry, or type 'skip' to skip observability setup entirely: " ""
      [ "$ack" != "skip" ] || return 1
    fi
  done
  printf -v "$__resultvar" '%s' "$port"
  return 0
}

if [ "$SIGNOZ_UI_RUNNING" = "1" ]; then
  SIGNOZ_PORT=$(docker port relaysms-publisher-signoz-signoz-0 8080/tcp | head -1 | cut -d: -f2)
  log "SigNoz UI already running on port $SIGNOZ_PORT, leaving it as-is"
else
  resolve_port SIGNOZ_PORT "the SigNoz UI" 1 || {
    log "Skipping observability setup."
    exit 0
  }
fi

if [ "$KUMA_RUNNING" = "1" ]; then
  KUMA_PORT=$(docker port uptime-kuma 3001/tcp | head -1 | cut -d: -f2)
  log "Uptime Kuma already running on port $KUMA_PORT, leaving it as-is"
else
  resolve_port KUMA_PORT "Uptime Kuma" 1 || {
    log "Skipping observability setup."
    exit 0
  }
fi

if [ "$INGESTER_RUNNING" != "1" ]; then
  resolve_port OTLP_GRPC_PORT "the OTLP gRPC receiver" 0 || {
    log "Skipping observability setup."
    exit 0
  }
  resolve_port OTLP_HTTP_PORT "the OTLP HTTP receiver" 0 || {
    log "Skipping observability setup."
    exit 0
  }
fi

if ! command -v foundryctl &>/dev/null; then
  log "Installing foundryctl"
  # ~/.local/bin (foundryctl's default) isn't reliably on PATH for a
  # non-interactive root shell.
  curl -fsSL https://signoz.io/foundry.sh | FOUNDRY_INSTALL_DIR=/usr/local/bin bash
fi

# Foundry defaults the metastore Postgres credentials to the literal
# string "signoz" for all three if left as the template's placeholders.
if [ ! -f observability/signoz/casting.yaml ]; then
  log "Generating SigNoz metastore credentials"
  pg_password=$(openssl rand -hex 24)
  sed \
    -e "s/__POSTGRES_DB__/signoz/" \
    -e "s/__POSTGRES_USER__/signoz/" \
    -e "s/__POSTGRES_PASSWORD__/$pg_password/" \
    observability/signoz/casting.yaml.template >observability/signoz/casting.yaml
fi

if [ "$SIGNOZ_UI_RUNNING" = "1" ]; then
  log "SigNoz already running, skipping"
else
  log "Starting SigNoz"
  if [ "$SIGNOZ_PORT" = "8080" ]; then
    foundryctl cast -f observability/signoz/casting.yaml
  else
    # Foundry hardcodes the SigNoz UI to port 8080, no override in
    # casting.yaml -- cast fails on just that container, everything else
    # in the stack still comes up, and compose.yaml is written regardless.
    foundryctl cast -f observability/signoz/casting.yaml || true
    [ -f pours/deployment/compose.yaml ] ||
      error "foundryctl cast failed before generating pours/deployment/compose.yaml, see output above"
    sed -i "s/8080:8080/$SIGNOZ_PORT:8080/" pours/deployment/compose.yaml
    docker rm -f relaysms-publisher-signoz-signoz-0 &>/dev/null || true
  fi
  docker compose \
    -f pours/deployment/compose.yaml \
    -f observability/signoz/docker-compose.override.yml \
    up -d
fi

if [ "$KUMA_RUNNING" = "1" ]; then
  log "Uptime Kuma already running, skipping"
else
  log "Starting Uptime Kuma"
  if [ "$KUMA_PORT" != "3001" ]; then
    sed -i "s/127.0.0.1:3001:3001/127.0.0.1:$KUMA_PORT:3001/" observability/uptime-kuma/docker-compose.yml
  fi
  docker compose -f observability/uptime-kuma/docker-compose.yml up -d
fi

if [ "$SKIP_NGINX" != "1" ] && [ -n "$SITE_NAME" ]; then
  if ! command -v nginx &>/dev/null || ! command -v certbot &>/dev/null || ! command -v htpasswd &>/dev/null; then
    log "Installing nginx, certbot, and apache2-utils"
    apt-get install -y --no-install-recommends nginx certbot python3-certbot-nginx apache2-utils
  fi
  mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled

  conf_dest="/etc/nginx/sites-available/${SITE_NAME}.conf"
  if [ -f "$conf_dest" ]; then
    log "nginx site $conf_dest already exists, leaving it untouched"
  else
    sed \
      -e "s/__SERVER_NAME__/$SITE_NAME/g" \
      -e "s/127.0.0.1:8080/127.0.0.1:$SIGNOZ_PORT/" \
      -e "s/127.0.0.1:3001/127.0.0.1:$KUMA_PORT/" \
      "$INSTALL_DIR/observability/nginx-observability.conf.template" >"$conf_dest"
    log "Wrote $conf_dest"
  fi
  ln -sf "$conf_dest" "/etc/nginx/sites-enabled/${SITE_NAME}.conf"

  htpasswd_file="/etc/nginx/.htpasswd-observability"
  if [ -f "$htpasswd_file" ]; then
    log "$htpasswd_file already exists, leaving it untouched"
  else
    htpasswd_password=$(openssl rand -hex 16)
    htpasswd -cb "$htpasswd_file" admin "$htpasswd_password"
    highlight \
      "Observability reverse proxy credentials" \
      "User     : admin" \
      "Password : $htpasswd_password" \
      "Written to $htpasswd_file -- not stored anywhere else, save it now."
  fi

  nginx -t || error "nginx config test failed"
  systemctl enable nginx &>/dev/null || true
  systemctl reload nginx 2>/dev/null || systemctl restart nginx

  if [ -f "/etc/letsencrypt/live/${SITE_NAME}/fullchain.pem" ]; then
    log "Certificate for $SITE_NAME already exists, skipping certbot"
  else
    certbot_args=(--nginx -d "$SITE_NAME" --redirect --agree-tos --non-interactive)
    if [ -n "$LETSENCRYPT_EMAIL" ]; then
      certbot_args+=(-m "$LETSENCRYPT_EMAIL")
    else
      certbot_args+=(--register-unsafely-without-email)
    fi
    log "Requesting certificate for $SITE_NAME"
    certbot "${certbot_args[@]}" || error "certbot failed to obtain a certificate for $SITE_NAME"
  fi
fi

if [ "$SKIP_TRACING" != "1" ]; then
  log "Installing OTel packages"
  venv/bin/pip install --quiet -r requirements-observability.txt
  sed -i "s|^OTEL_EXPORTER_OTLP_ENDPOINT=.*|OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:$OTLP_GRPC_PORT|" .env
  log "Restarting services"
  "$INSTALL_DIR/manage.sh" restart
fi

log "SigNoz: http://localhost:$SIGNOZ_PORT  Uptime Kuma: http://localhost:$KUMA_PORT"
[ -n "$SITE_NAME" ] && [ "$SKIP_NGINX" != "1" ] && log "Reverse proxy: https://$SITE_NAME"
log "Create Uptime Kuma monitors and set retention in SigNoz, see observability/README.md"
