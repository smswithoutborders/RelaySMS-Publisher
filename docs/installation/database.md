# Database

| Dialect | Use it for | Encryption at rest |
| --- | --- | --- |
| SQLite (default) | One server with light load | SQLCipher, with `DATABASE_ENCRYPTION_KEY` |
| MySQL 8.0.28+ or MariaDB | Heavier load, or a database on another host | The server's own (TDE) |
| PostgreSQL 12+ | Heavier load, or a database on another host | The disk's |

Sensitive fields are also encrypted in every dialect; see [Encryption keys](../configuration/encryption-keys.md).

## MySQL, MariaDB or PostgreSQL

A setup script installs the server, creates the database and user, and writes the connection details to `.env`. Running it again without `--db-password` sets a new password. The MySQL script installs `mysql-server`, which only Ubuntu ships; on Debian, set up MariaDB yourself and pass `--db-existing`.

```bash
sudo ./install.sh --setup-db postgres                                    # during install
sudo ./scripts/setup-postgres.sh --db-name relaysms --db-user relaysms   # afterwards
sudo ./scripts/setup-mysql.sh --db-name relaysms --db-user relaysms
```

`--db-password PASS` sets the password instead of generating one.

To use a server you already have, pass its details. The script only checks the connection and writes `.env`; it never changes the server:

```bash
sudo ./install.sh --setup-db postgres --db-existing \
    --db-host db.example.com --db-port 5432 \
    --db-name relaysms --db-user relaysms --db-password 'your-password'

sudo ./scripts/setup-postgres.sh --existing \
    --db-host db.example.com --db-name relaysms --db-user relaysms --db-password 'your-password'
```

Or set it by hand:

```bash
DATABASE_DIALECT=postgres       # or mysql, for MySQL and MariaDB
POSTGRES_HOST=127.0.0.1         # MYSQL_HOST, MYSQL_PORT, ... for mysql
POSTGRES_PORT=5432
POSTGRES_USER=relaysms
POSTGRES_PASSWORD=your-password
POSTGRES_DATABASE=relaysms
```

Then apply the migrations and restart:

```bash
sudo ./manage.sh migrate
sudo ./manage.sh restart
```

> [!WARNING]
> The new database starts empty. Switching doesn't copy data from SQLite.
