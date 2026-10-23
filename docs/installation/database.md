# Database

| Dialect | Use it for | Encryption at rest |
| --- | --- | --- |
| SQLite (default) | One server with light load | SQLCipher, with `DATABASE_ENCRYPTION_KEY` |
| MySQL 8.0.28+ or MariaDB | Heavier load, or a database on another host | The server's own (TDE) |
| PostgreSQL 12+ | Heavier load, or a database on another host | The disk's |

In every dialect, the server's private keys are encrypted, and so are platform tokens while field encryption is on; see [Encryption keys](../configuration/encryption-keys.md).

## Database servers

A setup script installs the server, creates the database and user, and writes the connection details to `.env`. Running it again without `--db-password` gives the user a new password. On Debian, install MariaDB yourself and pass `--db-existing`.

During install:

```bash
sudo ./install.sh --setup-db postgres
```

On an existing install, from the install directory:

```bash
sudo ./scripts/setup-postgres.sh --db-name relaysms --db-user relaysms
```

For MySQL or MariaDB, use `--setup-db mysql` or `scripts/setup-mysql.sh` the same way.

`--db-password <PASSWORD>` sets the password instead of generating one.

To use a server you already have, pass its details. The script only checks the connection and writes `.env`; it never changes the server:

```bash
sudo ./install.sh --setup-db postgres --db-existing \
    --db-host db.example.com --db-port 5432 \
    --db-name relaysms --db-user relaysms --db-password '<PASSWORD>'
```

On an existing install:

```bash
sudo ./scripts/setup-postgres.sh --existing \
    --db-host db.example.com --db-name relaysms --db-user relaysms --db-password '<PASSWORD>'
```

Or set it by hand in `.env`. For PostgreSQL:

```bash
DATABASE_DIALECT=postgres
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_USER=relaysms
POSTGRES_PASSWORD=<PASSWORD>
POSTGRES_DATABASE=relaysms
```

For MySQL or MariaDB:

```bash
DATABASE_DIALECT=mysql
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=relaysms
MYSQL_PASSWORD=<PASSWORD>
MYSQL_DATABASE=relaysms
```

Then apply the migrations and restart:

```bash
sudo ./manage.sh migrate
sudo ./manage.sh restart
```

The new database starts empty: switching doesn't copy the data from SQLite.
