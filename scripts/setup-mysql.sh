#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Installs MySQL if missing, creates a dedicated database/user, and writes
# the connection details into .env. Re-runnable: an existing install or
# database/user is left as-is; only missing pieces are created.
set -Eeuo pipefail

INSTALL_DIR="/opt/relaysms/relaysms-publisher"
DB_NAME="relaysms"
DB_USER="relaysms"
DB_PASSWORD=""

log() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"; }
error() {
  echo "[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2
  exit 1
}
on_err() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: aborted at line $1 (last command: $2)" >&2; }
trap 'on_err "$LINENO" "$BASH_COMMAND"' ERR

usage() {
  cat <<'EOF'
Usage: setup-mysql.sh [OPTIONS]

  --install-dir DIR   Publisher install directory (default: /opt/relaysms/relaysms-publisher)
  --db-name NAME      Database name (default: relaysms)
  --db-user USER      Database user (default: relaysms)
  --db-password PASS  Database password (default: randomly generated)
  -h, --help          Show this help and exit
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
  --install-dir)
    INSTALL_DIR="$2"
    shift 2
    ;;
  --db-name)
    DB_NAME="$2"
    shift 2
    ;;
  --db-user)
    DB_USER="$2"
    shift 2
    ;;
  --db-password)
    DB_PASSWORD="$2"
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
[ -n "$DB_PASSWORD" ] || DB_PASSWORD=$(openssl rand -hex 24)

if ! command -v mysql &>/dev/null; then
  log "Installing MySQL server"
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends mysql-server
fi
systemctl enable mysql &>/dev/null || true
systemctl start mysql

log "Creating database '$DB_NAME' and user '$DB_USER'"
mysql -u root <<SQL
CREATE DATABASE IF NOT EXISTS \`$DB_NAME\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '$DB_USER'@'localhost' IDENTIFIED BY '$DB_PASSWORD';
CREATE USER IF NOT EXISTS '$DB_USER'@'127.0.0.1' IDENTIFIED BY '$DB_PASSWORD';
ALTER USER '$DB_USER'@'localhost' IDENTIFIED BY '$DB_PASSWORD';
ALTER USER '$DB_USER'@'127.0.0.1' IDENTIFIED BY '$DB_PASSWORD';
GRANT ALL PRIVILEGES ON \`$DB_NAME\`.* TO '$DB_USER'@'localhost';
GRANT ALL PRIVILEGES ON \`$DB_NAME\`.* TO '$DB_USER'@'127.0.0.1';
FLUSH PRIVILEGES;
SQL

sed -i "s|^DATABASE_DIALECT=.*|DATABASE_DIALECT=mysql|" "$INSTALL_DIR/.env"
sed -i "s|^MYSQL_HOST=.*|MYSQL_HOST=127.0.0.1|" "$INSTALL_DIR/.env"
sed -i "s|^MYSQL_PORT=.*|MYSQL_PORT=3306|" "$INSTALL_DIR/.env"
sed -i "s|^MYSQL_USER=.*|MYSQL_USER=$DB_USER|" "$INSTALL_DIR/.env"
sed -i "s|^MYSQL_PASSWORD=.*|MYSQL_PASSWORD=$DB_PASSWORD|" "$INSTALL_DIR/.env"
sed -i "s|^MYSQL_DATABASE=.*|MYSQL_DATABASE=$DB_NAME|" "$INSTALL_DIR/.env"

log "MySQL ready. Database: $DB_NAME, user: $DB_USER, password: $DB_PASSWORD"
log "Credentials are written to $INSTALL_DIR/.env, record the password now if you need it elsewhere"
