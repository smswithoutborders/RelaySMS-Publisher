#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Re-runnable: an existing install or vhost/user is left as-is.
set -Eeuo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

INSTALL_DIR="/opt/relaysms/relaysms-publisher"
BROKER_EXISTING=0
BROKER_HOST="127.0.0.1"
BROKER_PORT="5672"
BROKER_MGMT_PORT="15672"
BROKER_VHOST="relaysms"
BROKER_USER="relaysms"
BROKER_PASSWORD=""

usage() {
  cat <<'EOF'
Usage: setup-rabbitmq.sh [OPTIONS]

  --install-dir DIR       Publisher install directory (default: /opt/relaysms/relaysms-publisher)
  --existing              Use an already-running RabbitMQ server instead of installing one locally
  --broker-host HOST      Broker host (default: 127.0.0.1; only valid with --existing)
  --broker-port PORT      Broker AMQP port (default: 5672; only valid with --existing)
  --broker-mgmt-port PORT Broker management API port, used to verify --existing credentials (default: 15672)
  --broker-vhost NAME     RabbitMQ vhost (default: relaysms)
  --broker-user USER      RabbitMQ user (default: relaysms)
  --broker-password PASS  RabbitMQ password (default: randomly generated; required with --existing)
  -h, --help              Show this help and exit
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
  --install-dir)
    INSTALL_DIR="$2"
    shift 2
    ;;
  --existing)
    BROKER_EXISTING=1
    shift
    ;;
  --broker-host)
    BROKER_HOST="$2"
    shift 2
    ;;
  --broker-port)
    BROKER_PORT="$2"
    shift 2
    ;;
  --broker-mgmt-port)
    BROKER_MGMT_PORT="$2"
    shift 2
    ;;
  --broker-vhost)
    BROKER_VHOST="$2"
    shift 2
    ;;
  --broker-user)
    BROKER_USER="$2"
    shift 2
    ;;
  --broker-password)
    BROKER_PASSWORD="$2"
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
[ -f "$INSTALL_DIR/.env" ] || error "$INSTALL_DIR/.env not found, run install.sh first"
validate_identifier "--broker-vhost" "$BROKER_VHOST"
validate_identifier "--broker-user" "$BROKER_USER"
if [ "$BROKER_EXISTING" != "1" ] && { [ "$BROKER_HOST" != "127.0.0.1" ] || [ "$BROKER_PORT" != "5672" ]; }; then
  error "--broker-host/--broker-port only apply with --existing; a new local install always uses 127.0.0.1:5672"
fi

if [ "$BROKER_EXISTING" = "1" ]; then
  [ -n "$BROKER_PASSWORD" ] || error "--broker-password is required with --existing"
  validate_secret "--broker-password" "$BROKER_PASSWORD"

  # rabbitmqctl only works locally, so this checks the management HTTP API
  # instead. /api/vhosts/<vhost> 401s for anyone without the administrator
  # tag, so /api/exchanges/<vhost> is used to work for a plain vhost user.
  log "Checking connection to existing RabbitMQ server at $BROKER_HOST:$BROKER_MGMT_PORT"
  http_code=$(curl -s -o /dev/null -w '%{http_code}' -u "$BROKER_USER:$BROKER_PASSWORD" \
    "http://$BROKER_HOST:$BROKER_MGMT_PORT/api/exchanges/$BROKER_VHOST") || http_code="000"
  case "$http_code" in
  200)
    log "Connected successfully"
    ;;
  401 | 403)
    error "Authentication failed for RabbitMQ user '$BROKER_USER' at $BROKER_HOST.
Re-run without --existing (or choose 'new' at the prompt) to create a new local broker instead."
    ;;
  404)
    error "Vhost '$BROKER_VHOST' not found on $BROKER_HOST.
Check --broker-vhost, or re-run without --existing to create a new local broker instead."
    ;;
  *)
    error "Could not reach the RabbitMQ management API at $BROKER_HOST:$BROKER_MGMT_PORT (HTTP $http_code).
Check --broker-host/--broker-mgmt-port and that the management plugin is enabled, or re-run without --existing to create a new local broker instead."
    ;;
  esac
else
  [ -n "$BROKER_PASSWORD" ] || BROKER_PASSWORD=$(openssl rand -hex 24)
  validate_secret "--broker-password" "$BROKER_PASSWORD"

  if ! command -v rabbitmqctl &>/dev/null; then
    log "Installing RabbitMQ server"
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends rabbitmq-server
  fi
  systemctl enable rabbitmq-server &>/dev/null || true
  systemctl start rabbitmq-server

  log "Creating vhost '$BROKER_VHOST'"
  if ! rabbitmqctl -q list_vhosts | grep -qx "$BROKER_VHOST"; then
    rabbitmqctl add_vhost "$BROKER_VHOST"
  fi

  log "Creating user '$BROKER_USER'"
  if rabbitmqctl -q list_users | awk '{print $1}' | grep -qx "$BROKER_USER"; then
    rabbitmqctl change_password "$BROKER_USER" "$BROKER_PASSWORD"
  else
    rabbitmqctl add_user "$BROKER_USER" "$BROKER_PASSWORD"
  fi
  rabbitmqctl set_permissions -p "$BROKER_VHOST" "$BROKER_USER" ".*" ".*" ".*"
fi

sed -i "s|^CELERY_BROKER_TYPE=.*|CELERY_BROKER_TYPE=rabbitmq|" "$INSTALL_DIR/.env"
sed -i "s|^#\?[[:space:]]*CELERY_RABBITMQ_URL=.*|CELERY_RABBITMQ_URL=amqp://$BROKER_USER:$BROKER_PASSWORD@$BROKER_HOST:$BROKER_PORT/$BROKER_VHOST|" "$INSTALL_DIR/.env"

highlight \
  "RabbitMQ ready" \
  "Host     : $BROKER_HOST:$BROKER_PORT" \
  "Vhost    : $BROKER_VHOST" \
  "User     : $BROKER_USER" \
  "Password : $BROKER_PASSWORD" \
  "Written to $INSTALL_DIR/.env -- not stored anywhere else, save it now."
