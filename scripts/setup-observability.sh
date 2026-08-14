#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Brings up SigNoz + Uptime Kuma and turns on OTel tracing. Re-runnable.
set -Eeuo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

INSTALL_DIR="/opt/relaysms/relaysms-publisher"
SITE_NAME=""
KUMA_SITE_NAME=""
LETSENCRYPT_EMAIL=""
SKIP_NGINX=0
SKIP_TRACING=0
SIGNOZ_PORT=8090
KUMA_PORT=3001
OTLP_GRPC_PORT=4317
OTLP_HTTP_PORT=4318
SIGNOZ_EMAIL="admin@relaysms.local"
SIGNOZ_EMAIL_SET=0
SIGNOZ_PASSWORD=""
SIGNOZ_SMTP_HOST=""
SIGNOZ_SMTP_PORT="587"
SIGNOZ_SMTP_USERNAME=""
SIGNOZ_SMTP_PASSWORD=""
SIGNOZ_SMTP_FROM=""

usage() {
  cat <<'EOF'
Usage: setup-observability.sh [OPTIONS]

  --install-dir DIR         Publisher install directory (default: /opt/relaysms/relaysms-publisher)
  --site-name DOMAIN        Domain for the SigNoz reverse proxy (optional; skips nginx/TLS if omitted)
  --kuma-site-name DOMAIN   Domain for the Uptime Kuma reverse proxy (optional; must differ from --site-name)
  --letsencrypt-email EMAIL Email for Let's Encrypt renewal notices (optional)
  --skip-nginx              Skip the nginx/TLS setup even if --site-name is given
  --skip-tracing            Don't install requirements-observability.txt or turn on OTEL_EXPORTER_OTLP_ENDPOINT
  --signoz-port PORT        Host port for the SigNoz UI (default: 8090)
  --kuma-port PORT          Host port for Uptime Kuma (default: 3001)
  --signoz-email EMAIL      Admin account email for SigNoz's first-run setup (default: admin@relaysms.local)
  --signoz-password PASS    Admin account password (default: randomly generated)
  --signoz-smtp-host HOST   SMTP relay host for SigNoz email alerts (optional; Email channel won't work without it)
  --signoz-smtp-port PORT   SMTP relay port (default: 587)
  --signoz-smtp-username U  SMTP relay username
  --signoz-smtp-password P  SMTP relay password
  --signoz-smtp-from EMAIL  From address for SigNoz email alerts
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
  --kuma-site-name)
    KUMA_SITE_NAME="$2"
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
  --signoz-email)
    SIGNOZ_EMAIL="$2"
    SIGNOZ_EMAIL_SET=1
    shift 2
    ;;
  --signoz-password)
    SIGNOZ_PASSWORD="$2"
    shift 2
    ;;
  --signoz-smtp-host)
    SIGNOZ_SMTP_HOST="$2"
    shift 2
    ;;
  --signoz-smtp-port)
    SIGNOZ_SMTP_PORT="$2"
    shift 2
    ;;
  --signoz-smtp-username)
    SIGNOZ_SMTP_USERNAME="$2"
    shift 2
    ;;
  --signoz-smtp-password)
    SIGNOZ_SMTP_PASSWORD="$2"
    shift 2
    ;;
  --signoz-smtp-from)
    SIGNOZ_SMTP_FROM="$2"
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
[ -z "$KUMA_SITE_NAME" ] || validate_hostname "--kuma-site-name" "$KUMA_SITE_NAME"
[ -n "$SITE_NAME" ] && [ -n "$KUMA_SITE_NAME" ] && [ "$SITE_NAME" = "$KUMA_SITE_NAME" ] &&
  error "--site-name and --kuma-site-name must be different domains"
[ -z "$SIGNOZ_SMTP_HOST" ] || validate_hostname "--signoz-smtp-host" "$SIGNOZ_SMTP_HOST"
[[ "$SIGNOZ_SMTP_PORT" =~ ^[0-9]+$ ]] || error "--signoz-smtp-port must be a number"
[ -z "$SIGNOZ_SMTP_PASSWORD" ] || validate_secret "--signoz-smtp-password" "$SIGNOZ_SMTP_PASSWORD"
[ -z "$SIGNOZ_SMTP_USERNAME" ] || [[ "$SIGNOZ_SMTP_USERNAME" =~ ^[A-Za-z0-9@_.,!?+=~^-]+$ ]] ||
  error "--signoz-smtp-username contains unsupported characters"
[ -z "$SIGNOZ_SMTP_FROM" ] || [[ "$SIGNOZ_SMTP_FROM" =~ ^[A-Za-z0-9@_.,!?+=~^-]+$ ]] ||
  error "--signoz-smtp-from contains unsupported characters"
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
      prompt ack "$label is fixed at $port and can't be moved to a different port. Free it up and press enter to retry, or type 'skip' to skip observability setup entirely: " ""
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

# Generated once; a rerun with a different --signoz-port after this file
# exists won't change it, same as the Postgres credentials.
if [ ! -f observability/signoz/casting.yaml ]; then
  log "Generating SigNoz configuration"
  pg_password=$(openssl rand -hex 24)
  smtp_smarthost=""
  [ -n "$SIGNOZ_SMTP_HOST" ] && smtp_smarthost="$SIGNOZ_SMTP_HOST:$SIGNOZ_SMTP_PORT"
  sed \
    -e "s/__POSTGRES_DB__/signoz/" \
    -e "s/__POSTGRES_USER__/signoz/" \
    -e "s/__POSTGRES_PASSWORD__/$pg_password/" \
    -e "s/__SIGNOZ_PORT__/$SIGNOZ_PORT/" \
    -e "s/__OTLP_GRPC_PORT__/$OTLP_GRPC_PORT/" \
    -e "s/__OTLP_HTTP_PORT__/$OTLP_HTTP_PORT/" \
    -e "s/__SMTP_SMARTHOST__/$smtp_smarthost/" \
    -e "s/__SMTP_USERNAME__/$SIGNOZ_SMTP_USERNAME/" \
    -e "s/__SMTP_PASSWORD__/$SIGNOZ_SMTP_PASSWORD/" \
    -e "s/__SMTP_FROM__/$SIGNOZ_SMTP_FROM/" \
    observability/signoz/casting.yaml.template >observability/signoz/casting.yaml
fi

if [ "$SIGNOZ_UI_RUNNING" = "1" ]; then
  log "SigNoz already running, skipping"
else
  log "Starting SigNoz"
  foundryctl cast -f observability/signoz/casting.yaml
  docker compose \
    -f pours/deployment/compose.yaml \
    -f observability/signoz/docker-compose.override.yml \
    up -d
fi

# Until an org exists, SigNoz's opamp bug (casting.yaml.template) keeps
# the OTLP receiver closed. Safe to call every run: setupCompleted flips
# permanently once an org exists, and a second registration is rejected.
log "Waiting for the SigNoz API"
signoz_version=""
for _ in $(seq 1 60); do
  signoz_version=$(curl -fs "http://127.0.0.1:$SIGNOZ_PORT/api/v1/version" 2>/dev/null) && break
  sleep 2
done
[ -n "$signoz_version" ] || error "SigNoz API never came up on port $SIGNOZ_PORT, see docker logs relaysms-publisher-signoz-signoz-0"

if [[ "$signoz_version" == *'"setupCompleted":false'* ]]; then
  create_admin="y"
  if [ "$SIGNOZ_EMAIL_SET" != "1" ] && [ -z "$SIGNOZ_PASSWORD" ]; then
    prompt create_admin "Create the SigNoz admin account now? Required for tracing/log ingestion. [Y/n] " "y"
  fi
  case "$create_admin" in
  n | N | no | NO)
    log "Skipping SigNoz admin account. OTLP ingestion stays blocked until one is created, see observability/README.md"
    ;;
  *)
    [ "$SIGNOZ_EMAIL_SET" = "1" ] || prompt SIGNOZ_EMAIL "SigNoz admin email [$SIGNOZ_EMAIL]: " "$SIGNOZ_EMAIL"
    if [ -z "$SIGNOZ_PASSWORD" ]; then
      prompt_secret SIGNOZ_PASSWORD "SigNoz admin password (blank to auto-generate): "
      [ -n "$SIGNOZ_PASSWORD" ] || SIGNOZ_PASSWORD="$(openssl rand -hex 16)Aa1!"
    fi
    log "Creating SigNoz admin account"
    register_response=$(curl -s -X POST "http://127.0.0.1:$SIGNOZ_PORT/api/v1/register" \
      -H "Content-Type: application/json" \
      -d "{\"name\":\"Admin\",\"orgId\":\"\",\"orgName\":\"RelaySMS\",\"email\":\"$SIGNOZ_EMAIL\",\"password\":\"$SIGNOZ_PASSWORD\"}")
    [[ "$register_response" == *'"status":"success"'* ]] ||
      error "SigNoz admin account creation failed: $register_response"
    highlight \
      "SigNoz admin account" \
      "Email    : $SIGNOZ_EMAIL" \
      "Password : $SIGNOZ_PASSWORD" \
      "Not stored anywhere else, save it now."
    ;;
  esac
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

# Renders $2 for $1, symlinks it, and issues a cert. $3/$4 are the
# 127.0.0.1:PORT anchor in the template and the port to replace it with.
setup_reverse_proxy() {
  local site="$1" template="$2" port_from="$3" port_to="$4"
  local conf_dest="/etc/nginx/sites-available/${site}.conf"
  if [ -f "$conf_dest" ]; then
    log "nginx site $conf_dest already exists, leaving it untouched"
  else
    sed \
      -e "s/__SERVER_NAME__/$site/g" \
      -e "s/127.0.0.1:$port_from/127.0.0.1:$port_to/" \
      "$INSTALL_DIR/observability/$template" >"$conf_dest"
    log "Wrote $conf_dest"
  fi
  ln -sf "$conf_dest" "/etc/nginx/sites-enabled/${site}.conf"

  nginx -t || error "nginx config test failed"
  systemctl enable nginx &>/dev/null || true
  systemctl reload nginx 2>/dev/null || systemctl restart nginx

  if [ -f "/etc/letsencrypt/live/${site}/fullchain.pem" ]; then
    log "Certificate for $site already exists, skipping certbot"
  else
    local certbot_args=(--nginx -d "$site" --redirect --agree-tos --non-interactive)
    if [ -n "$LETSENCRYPT_EMAIL" ]; then
      certbot_args+=(-m "$LETSENCRYPT_EMAIL")
    else
      certbot_args+=(--register-unsafely-without-email)
    fi
    log "Requesting certificate for $site"
    certbot "${certbot_args[@]}" || error "certbot failed to obtain a certificate for $site"
  fi
}

if [ "$SKIP_NGINX" != "1" ] && { [ -n "$SITE_NAME" ] || [ -n "$KUMA_SITE_NAME" ]; }; then
  if ! command -v nginx &>/dev/null || ! command -v certbot &>/dev/null; then
    log "Installing nginx and certbot"
    apt-get install -y --no-install-recommends nginx certbot python3-certbot-nginx
  fi
  mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled

  [ -n "$SITE_NAME" ] &&
    setup_reverse_proxy "$SITE_NAME" "nginx-observability.conf.template" "8080" "$SIGNOZ_PORT"
  [ -n "$KUMA_SITE_NAME" ] &&
    setup_reverse_proxy "$KUMA_SITE_NAME" "nginx-uptime-kuma.conf.template" "3001" "$KUMA_PORT"
fi

if [ "$SKIP_TRACING" != "1" ]; then
  log "Installing OTel packages"
  venv/bin/pip install --quiet -r requirements-observability.txt
  sed -i "s|^OTEL_EXPORTER_OTLP_ENDPOINT=.*|OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:$OTLP_GRPC_PORT|" .env
  log "Restarting services"
  "$INSTALL_DIR/manage.sh" restart
fi

log "SigNoz: http://localhost:$SIGNOZ_PORT  Uptime Kuma: http://localhost:$KUMA_PORT"
[ -n "$SITE_NAME" ] && [ "$SKIP_NGINX" != "1" ] && log "SigNoz reverse proxy: https://$SITE_NAME"
[ -n "$KUMA_SITE_NAME" ] && [ "$SKIP_NGINX" != "1" ] && log "Uptime Kuma reverse proxy: https://$KUMA_SITE_NAME"
log "Create Uptime Kuma monitors and set retention in SigNoz, see observability/README.md"
