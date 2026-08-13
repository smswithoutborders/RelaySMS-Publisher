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

usage() {
  cat <<'EOF'
Usage: setup-observability.sh [OPTIONS]

  --install-dir DIR         Publisher install directory (default: /opt/relaysms/relaysms-publisher)
  --site-name DOMAIN        Domain for the observability reverse proxy (optional; skips nginx/TLS if omitted)
  --letsencrypt-email EMAIL Email for Let's Encrypt renewal notices (optional)
  --skip-nginx              Skip the nginx/TLS setup even if --site-name is given
  --skip-tracing            Don't install requirements-observability.txt or turn on OTEL_EXPORTER_OTLP_ENDPOINT
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

if ! command -v foundryctl &>/dev/null; then
  log "Installing foundryctl"
  # Default install dir (~/.local/bin) isn't reliably on PATH for a
  # non-interactive root shell; pin it to somewhere that always is.
  curl -fsSL https://signoz.io/foundry.sh | FOUNDRY_INSTALL_DIR=/usr/local/bin bash
fi

# Left as placeholders in the template, Foundry defaults the metastore
# Postgres credentials to the literal string "signoz" for all three.
if [ ! -f observability/signoz/casting.yaml ]; then
  log "Generating SigNoz metastore credentials"
  pg_password=$(openssl rand -hex 24)
  sed \
    -e "s/__POSTGRES_DB__/signoz/" \
    -e "s/__POSTGRES_USER__/signoz/" \
    -e "s/__POSTGRES_PASSWORD__/$pg_password/" \
    observability/signoz/casting.yaml.template >observability/signoz/casting.yaml
fi

log "Starting SigNoz"
foundryctl cast -f observability/signoz/casting.yaml
docker compose \
  -f pours/deployment/compose.yaml \
  -f observability/signoz/docker-compose.override.yml \
  up -d

log "Starting Uptime Kuma"
docker compose -f observability/uptime-kuma/docker-compose.yml up -d

if [ "$SKIP_NGINX" != "1" ] && [ -n "$SITE_NAME" ]; then
  if ! command -v nginx &>/dev/null || ! command -v certbot &>/dev/null; then
    log "Installing nginx and certbot"
    apt-get install -y --no-install-recommends nginx certbot python3-certbot-nginx
  fi
  mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled

  conf_dest="/etc/nginx/sites-available/${SITE_NAME}.conf"
  if [ -f "$conf_dest" ]; then
    log "nginx site $conf_dest already exists, leaving it untouched"
  else
    sed "s/__SERVER_NAME__/$SITE_NAME/g" \
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
  sed -i 's|^OTEL_EXPORTER_OTLP_ENDPOINT=.*|OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317|' .env
  log "Restarting services"
  "$INSTALL_DIR/manage.sh" restart
fi

log "SigNoz: http://localhost:8080  Uptime Kuma: http://localhost:3001"
[ -n "$SITE_NAME" ] && [ "$SKIP_NGINX" != "1" ] && log "Reverse proxy: https://$SITE_NAME"
log "Create Uptime Kuma monitors and set retention in SigNoz, see observability/README.md"
