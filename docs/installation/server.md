# Install on a server

The installer sets up the Publisher on Ubuntu 24.04 or Debian 13 under systemd, in `/opt/relaysms/relaysms-publisher`. Check the [requirements](requirements.md) first.

## Run the installer

> [!TIP]
> For a dedicated service user with no login, run the installer from a root shell (`sudo -i`). The service user can't be changed later without reinstalling.

```bash
curl -fsSL https://raw.githubusercontent.com/smswithoutborders/RelaySMS-Publisher/main/install.sh \
  | sudo bash
```

To read the script before running it:

```bash
curl -fsSLO https://raw.githubusercontent.com/smswithoutborders/RelaySMS-Publisher/main/install.sh
less install.sh
sudo bash install.sh
```

It asks about each option you don't pass as a flag. To choose up front, pass flags after `bash -s --`:

```bash
curl -fsSL https://raw.githubusercontent.com/smswithoutborders/RelaySMS-Publisher/main/install.sh \
  | sudo bash -s -- --site-name publisher.example.com --setup-db postgres
```

| Flag | Does |
| --- | --- |
| `--site-name <DOMAIN>` | Puts nginx with a Let's Encrypt certificate in front ([details](reverse-proxy.md)) |
| `--letsencrypt-email <EMAIL>` | Email for Let's Encrypt renewal notices |
| `--docs-site-name <DOMAIN>` | Serves this manual on its own domain ([details](#serving-the-manual)) |
| `--skip-nginx` | Skips nginx and certificates entirely |
| `--setup-db mysql\|postgres` | Uses MySQL or PostgreSQL instead of SQLite ([details](database.md)) |
| `--setup-broker rabbitmq` | Uses RabbitMQ instead of SQLite as the Celery broker ([details](celery-broker.md)) |
| `--setup-observability` | Adds SigNoz and Uptime Kuma ([details](../operating/observability.md)) |
| `--install-dir <PATH>`, `--instance-name <NAME>` | Installs elsewhere, or a second copy on the same host ([details](multiple-instances.md)) |
| `--branch <BRANCH>` | Installs another branch than `main` |

`install.sh --help` lists every flag, including those for an existing database or broker.

The installer:

1. installs the system packages and Rust;
2. picks the service user: the user who ran `sudo`, or a new `relaysms` user when run from a root shell;
3. clones the repository, builds it and creates `.env` with fresh encryption keys;
4. sets up the database and broker you chose, and applies the database migrations;
5. installs and starts the systemd services;
6. sets up nginx and the certificate, if you gave a domain.

Running it again updates the install in place and keeps its `.env`. Run it as the same user as the first time; it refuses another service user.

## After installing

1. Go to the install directory and check that the services are up:

   ```bash
   cd /opt/relaysms/relaysms-publisher
   sudo ./manage.sh status
   curl http://127.0.0.1:16000/health
   ```

   You should see `{"status":"ok"}`, also at `https://<DOMAIN>/health` once nginx is set up.

2. The defaults suit one server behind nginx. Change `.env` only for what they don't cover, such as a MySQL or PostgreSQL database ([settings reference](../configuration/settings.md)), then check it and restart:

   ```bash
   sudo ./manage.sh check
   sudo ./manage.sh restart
   ```

3. Create an administrator credential:

   ```bash
   sudo ./publisher.sh creds create --username ops --administrator
   ```

   > [!IMPORTANT]
   > The password is printed only once.

4. [Back up](../operating/backup-restore.md) `.env`: its [encryption keys](../configuration/encryption-keys.md) are the only way to read the data.

## Serving the manual

`--docs-site-name` builds this manual into `book/` and serves it with nginx on its own domain and certificate. `manage.sh update` rebuilds it.

```bash
curl -fsSL https://raw.githubusercontent.com/smswithoutborders/RelaySMS-Publisher/main/install.sh \
  | sudo bash -s -- --site-name publisher.example.com --docs-site-name docs.publisher.example.com
```

On an install that's already running, add it from the install directory:

```bash
sudo ./manage.sh docs docs.publisher.example.com
```

## Next steps

- [Add a platform adapter](../platforms/manage.md), then follow its [provider guide](../platforms/manage.md#provider-guides).
- [Register a gateway client](../gateway-clients/manage.md) and [connect its relay](../gateway-clients/connect-a-relay.md).
