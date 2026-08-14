#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Re-runnable: an existing install or database/user is left as-is.
set -Eeuo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

INSTALL_DIR="/opt/relaysms/relaysms-publisher"
DB_EXISTING=0
DB_HOST="127.0.0.1"
DB_PORT="3306"
DB_NAME="relaysms"
DB_USER="relaysms"
DB_PASSWORD=""

usage() {
  cat <<'EOF'
Usage: setup-mysql.sh [OPTIONS]

  --install-dir DIR   Publisher install directory (default: /opt/relaysms/relaysms-publisher)
  --existing          Use an already-running MySQL server instead of installing one locally
  --db-host HOST      Database host (default: 127.0.0.1; only valid with --existing)
  --db-port PORT      Database port (default: 3306; only valid with --existing)
  --db-name NAME      Database name (default: relaysms)
  --db-user USER      Database user (default: relaysms)
  --db-password PASS  Database password (default: randomly generated; required with --existing)
  -h, --help          Show this help and exit
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
  --install-dir)
    INSTALL_DIR="$2"
    shift 2
    ;;
  --existing)
    DB_EXISTING=1
    shift
    ;;
  --db-host)
    DB_HOST="$2"
    shift 2
    ;;
  --db-port)
    DB_PORT="$2"
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
validate_identifier "--db-name" "$DB_NAME"
validate_identifier "--db-user" "$DB_USER"
if [ "$DB_EXISTING" != "1" ] && { [ "$DB_HOST" != "127.0.0.1" ] || [ "$DB_PORT" != "3306" ]; }; then
  error "--db-host/--db-port only apply with --existing; a new local install always uses 127.0.0.1:3306"
fi

if [ "$DB_EXISTING" = "1" ]; then
  [ -n "$DB_PASSWORD" ] || error "--db-password is required with --existing"
  validate_secret "--db-password" "$DB_PASSWORD"

  log "Checking connection to existing MySQL server at $DB_HOST:$DB_PORT"
  db_err=$(MYSQL_PWD="$DB_PASSWORD" mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" "$DB_NAME" -e "SELECT 1;" 2>&1) || error "Could not connect to existing MySQL database '$DB_NAME' at $DB_HOST:$DB_PORT as '$DB_USER': $db_err
Re-run without --existing (or choose 'new' at the prompt) to create a new local database instead."
  log "Connected successfully"
else
  [ -n "$DB_PASSWORD" ] || DB_PASSWORD=$(openssl rand -hex 24)
  validate_secret "--db-password" "$DB_PASSWORD"

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
fi

sed -i "s|^DATABASE_DIALECT=.*|DATABASE_DIALECT=mysql|" "$INSTALL_DIR/.env"
sed -i "s|^MYSQL_HOST=.*|MYSQL_HOST=$DB_HOST|" "$INSTALL_DIR/.env"
sed -i "s|^MYSQL_PORT=.*|MYSQL_PORT=$DB_PORT|" "$INSTALL_DIR/.env"
sed -i "s|^MYSQL_USER=.*|MYSQL_USER=$DB_USER|" "$INSTALL_DIR/.env"
sed -i "s|^MYSQL_PASSWORD=.*|MYSQL_PASSWORD=$DB_PASSWORD|" "$INSTALL_DIR/.env"
sed -i "s|^MYSQL_DATABASE=.*|MYSQL_DATABASE=$DB_NAME|" "$INSTALL_DIR/.env"

highlight \
  "MySQL ready" \
  "Host     : $DB_HOST:$DB_PORT" \
  "Database : $DB_NAME" \
  "User     : $DB_USER" \
  "Password : $DB_PASSWORD" \
  "Written to $INSTALL_DIR/.env. Not stored anywhere else, save it now."
