#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Installs PostgreSQL if missing, creates a dedicated database/role, and
# writes the connection details into .env. Re-runnable: an existing install
# or database/role is left as-is; only missing pieces are created.
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
Usage: setup-postgres.sh [OPTIONS]

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

if ! command -v psql &>/dev/null; then
  log "Installing PostgreSQL server"
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends postgresql
fi
systemctl enable postgresql &>/dev/null || true
systemctl start postgresql

log "Creating role '$DB_USER'"
sudo -u postgres psql -v ON_ERROR_STOP=1 -c "
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$DB_USER') THEN
    CREATE ROLE \"$DB_USER\" WITH LOGIN PASSWORD '$DB_PASSWORD';
  ELSE
    ALTER ROLE \"$DB_USER\" WITH PASSWORD '$DB_PASSWORD';
  END IF;
END
\$\$;
"

log "Creating database '$DB_NAME'"
db_exists=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'")
if [ "$db_exists" != "1" ]; then
  sudo -u postgres psql -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$DB_NAME\" OWNER \"$DB_USER\";"
else
  sudo -u postgres psql -v ON_ERROR_STOP=1 -c "ALTER DATABASE \"$DB_NAME\" OWNER TO \"$DB_USER\";"
fi

# Belt-and-suspenders for pre-15 PostgreSQL: since 15, the database owner
# already gets CREATE on the public schema via pg_database_owner, but
# older versions need it granted explicitly or migrations fail with
# "permission denied for schema public".
sudo -u postgres psql -v ON_ERROR_STOP=1 -d "$DB_NAME" -c "GRANT ALL ON SCHEMA public TO \"$DB_USER\";"

sed -i "s|^DATABASE_DIALECT=.*|DATABASE_DIALECT=postgres|" "$INSTALL_DIR/.env"
sed -i "s|^POSTGRES_HOST=.*|POSTGRES_HOST=127.0.0.1|" "$INSTALL_DIR/.env"
sed -i "s|^POSTGRES_PORT=.*|POSTGRES_PORT=5432|" "$INSTALL_DIR/.env"
sed -i "s|^POSTGRES_USER=.*|POSTGRES_USER=$DB_USER|" "$INSTALL_DIR/.env"
sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$DB_PASSWORD|" "$INSTALL_DIR/.env"
sed -i "s|^POSTGRES_DATABASE=.*|POSTGRES_DATABASE=$DB_NAME|" "$INSTALL_DIR/.env"

log "Postgres ready. Database: $DB_NAME, user: $DB_USER, password: $DB_PASSWORD"
log "Credentials are written to $INSTALL_DIR/.env, record the password now if you need it elsewhere"
