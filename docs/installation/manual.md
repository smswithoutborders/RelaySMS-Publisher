# Install by hand

These are the steps the [installer](server.md) runs, for when you need to change one. Run them in a root shell (`sudo -i`).

1. Install the system packages:

   ```bash
   apt-get update
   apt-get install -y python3 python3-pip python3-venv python3-dev \
       build-essential pkg-config libsqlcipher-dev libmagic1 openssl git make curl
   ```

2. Install Rust, which builds the payload library:

   ```bash
   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
   source "$HOME/.cargo/env"
   ```

3. Create the service user:

   ```bash
   useradd --system --no-create-home --shell /usr/sbin/nologin relaysms
   ```

4. Clone the repository with its submodule:

   ```bash
   git clone --recurse-submodules \
       https://github.com/smswithoutborders/RelaySMS-Publisher.git \
       /opt/relaysms/relaysms-publisher
   cd /opt/relaysms/relaysms-publisher
   ```

5. Create the virtualenv and build the gRPC code and payload library:

   ```bash
   python3 -m venv venv
   venv/bin/pip install --upgrade pip
   venv/bin/pip install -r requirements.txt
   make build
   ```

6. Create `.env` with fresh encryption keys, then set what you need (see the [settings reference](../configuration/settings.md)):

   ```bash
   make .env
   chown root:relaysms .env
   chmod 640 .env
   ```

7. Create the data directories. By default the SQLite database, Celery files and adapters all live under `data/`:

   ```bash
   mkdir -p data/platforms/{adapters,venvs,config,state}
   chown -R relaysms: data
   chmod -R 750 data
   ```

   If `.env` moves any of these paths out of `data/` (`SQLITE_DATABASE_PATH`, `CELERY_BROKER_DB_PATH`, `CELERY_RESULT_DB_PATH`, `CELERY_BEAT_SCHEDULE_PATH` and the four `PLATFORMS_ADAPTERS_*` directories), create its parent directory and add it to `RW_PATHS` in step 9. Everything else is read-only to the services.

   For MySQL, PostgreSQL or RabbitMQ, run its setup script now ([Database](database.md), [Celery broker](celery-broker.md)).

8. Check the configuration and apply the database migrations, as the service user:

   ```bash
   sudo -u relaysms venv/bin/python -m publisher config check
   sudo -u relaysms venv/bin/python -m alembic upgrade head
   ```

9. Install and start the systemd units. `RW_PATHS` lists the directories the services may write to:

   ```bash
   RW_PATHS="$(pwd)/data"
   for unit in deploy/systemd/*; do
       sed -e "s|/opt/relaysms/relaysms-publisher|$(pwd)|g" \
           -e "s|__RW_PATHS__|$RW_PATHS|" \
           "$unit" > "/etc/systemd/system/$(basename "$unit")"
   done
   systemctl daemon-reload
   systemctl enable --now relaysms-publisher.target
   ```

## Next steps

Set up [nginx and TLS](reverse-proxy.md#by-hand), then continue with [After installing](server.md#after-installing).
