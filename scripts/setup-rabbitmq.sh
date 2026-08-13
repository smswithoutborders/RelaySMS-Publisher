#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Installs RabbitMQ if missing, creates a dedicated vhost/user, and writes
# the connection details into .env. Re-runnable: an existing install or
# vhost/user is left as-is; only missing pieces are created.
set -Eeuo pipefail

INSTALL_DIR="/opt/relaysms/relaysms-publisher"
BROKER_VHOST="relaysms"
BROKER_USER="relaysms"
BROKER_PASSWORD=""

log() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"; }
error() {
  echo "[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2
  exit 1
}
on_err() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: aborted at line $1 (last command: $2)" >&2; }
trap 'on_err "$LINENO" "$BASH_COMMAND"' ERR

usage() {
  cat <<'EOF'
Usage: setup-rabbitmq.sh [OPTIONS]

  --install-dir DIR    Publisher install directory (default: /opt/relaysms/relaysms-publisher)
  --broker-vhost NAME   RabbitMQ vhost (default: relaysms)
  --broker-user USER    RabbitMQ user (default: relaysms)
  --broker-password PASS  RabbitMQ password (default: randomly generated)
  -h, --help            Show this help and exit
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
  --install-dir)
    INSTALL_DIR="$2"
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
[ -n "$BROKER_PASSWORD" ] || BROKER_PASSWORD=$(openssl rand -hex 24)

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

sed -i "s|^CELERY_BROKER_TYPE=.*|CELERY_BROKER_TYPE=rabbitmq|" "$INSTALL_DIR/.env"
sed -i "s|^#\?[[:space:]]*CELERY_RABBITMQ_URL=.*|CELERY_RABBITMQ_URL=amqp://$BROKER_USER:$BROKER_PASSWORD@localhost:5672/$BROKER_VHOST|" "$INSTALL_DIR/.env"

log "RabbitMQ ready. Vhost: $BROKER_VHOST, user: $BROKER_USER, password: $BROKER_PASSWORD"
log "Credentials are written to $INSTALL_DIR/.env, record the password now if you need it elsewhere"
