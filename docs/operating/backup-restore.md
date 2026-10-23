# Backup and restore

A backup is:

- **`.env`**: its [encryption keys](../configuration/encryption-keys.md) are the only way to read the data.
- **`data/`**: the SQLite database, Celery files, and the adapters with their settings, state and virtualenvs.
- **A dump of the database**, with MySQL or PostgreSQL.
- **Any file `.env` points to outside `data/`**, such as `GRPC_TLS_CERT_FILE` or `SMTP_TLS_CLIENT_KEY`.

The installer recreates the nginx sites, certificates and service units, so `/etc` needs no backup.

> [!CAUTION]
> Store the `.env` archive apart from the data. Anyone with both can read the linked accounts' tokens.

## Back up

From the install directory, stop the services so the data is consistent, then archive `.env` and `data/` separately:

```bash
sudo ./manage.sh stop
sudo tar -czf /root/relaysms-env-$(date +%F).tar.gz .env
sudo tar -czf /root/relaysms-data-$(date +%F).tar.gz data
```

With PostgreSQL, dump the database before starting the services again:

```bash
sudo sh -c 'sudo -u postgres pg_dump relaysms > /root/relaysms-db-$(date +%F).sql'
```

With MySQL or MariaDB:

```bash
sudo sh -c 'mysqldump relaysms > /root/relaysms-db-$(date +%F).sql'
```

Then start the services:

```bash
sudo ./manage.sh start
```

For a database on another host, or named differently in `.env`, connect with the details from `.env`, such as `pg_dump -h <DB_HOST> -U <DB_USER> <DB_NAME>`. With Docker, use `docker compose stop` and `docker compose start` in place of `manage.sh`.

## Restore

1. [Install](../installation/server.md) the Publisher in the same directory, with the same `--instance-name`. With MySQL or PostgreSQL, pass `--setup-db`, `--db-name`, `--db-user` and `--db-password` with the values from the backed-up `.env` (`MYSQL_*` or `POSTGRES_*`); with RabbitMQ, the same for `--broker-password`. Otherwise the servers refuse the restored `.env`'s logins.
2. Stop the services:

   ```bash
   sudo ./manage.sh stop
   ```

3. From the install directory, replace the new `data/` and `.env` with the backed-up ones:

   ```bash
   sudo rm -rf data
   sudo tar -xzf /root/relaysms-env-<DATE>.tar.gz
   sudo tar -xzf /root/relaysms-data-<DATE>.tar.gz
   ```

4. With PostgreSQL, replace the new database with the dump:

   ```bash
   sudo -u postgres dropdb relaysms
   sudo -u postgres createdb -O relaysms relaysms
   sudo sh -c 'sudo -u postgres psql -v ON_ERROR_STOP=1 relaysms < /root/relaysms-db-<DATE>.sql'
   ```

   With MySQL or MariaDB:

   ```bash
   sudo mysql -e 'DROP DATABASE relaysms; CREATE DATABASE relaysms CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci'
   sudo sh -c 'mysql relaysms < /root/relaysms-db-<DATE>.sql'
   ```

5. Apply any migrations newer than the backup, then start the services and check them:

   ```bash
   sudo ./manage.sh migrate
   sudo ./manage.sh start
   sudo ./manage.sh check
   ```

`tar` keeps the files' owners. If the service user's name or ID differs on the new host, give the files back to it: `sudo chown -R <SERVICE_USER>: data` and `sudo chown root:<SERVICE_USER> .env`.

## Next steps

[Check that the services are up](services.md#is-it-working).
