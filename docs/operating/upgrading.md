# Upgrading

A server install follows the branch it was installed from, `main` by default. An update pulls that branch, rebuilds, and restarts the services.

## Before you upgrade

1. [Back up](backup-restore.md). Migrations can't be undone, so going back to older code needs the backup.
2. Note the current commit, to roll back to:

   ```bash
   git rev-parse HEAD
   ```

## Update a server install

From the install directory:

```bash
sudo ./manage.sh update --migrate
sudo ./sync-env.sh
sudo ./manage.sh check
sudo ./manage.sh restart
```

1. `update --migrate` stops the services, pulls the code, reinstalls the dependencies, rebuilds, applies pending migrations and starts the services again. With no migrations pending, `--migrate` changes nothing. When the install serves this manual, it rebuilds it too.
2. `sync-env.sh` adds the settings the new `template.env` has and `.env` lacks, showing the change before writing it.
3. `check` reports any setting still missing or invalid; fill it in `.env`.
4. `restart` loads the new settings.

If `git diff --stat ORIG_HEAD HEAD -- deploy/nginx` lists changes, render the site again:

```bash
sudo ./manage.sh nginx
```

If you edited tracked files that the update changes, `update` stops before pulling and leaves the services stopped. Discard the edits or `git stash` them, then run `update` again.

## Roll back

1. Take the commit you noted [before upgrading](#before-you-upgrade).
2. If the update applied migrations, [restore the backup](backup-restore.md#restore) taken before it; older code can't use the migrated database.
3. Check out that commit and rebuild. `--pulled` skips the pull that would undo the checkout:

   ```bash
   sudo git checkout <COMMIT>
   sudo ./manage.sh update --pulled
   ```

To follow the branch again later, run `sudo git checkout main`, then `sudo ./manage.sh update --migrate`.

## Update with Docker

```bash
git pull --recurse-submodules
docker compose up -d --build
```

The container applies new migrations and runs `platforms import` when it starts.

## Update adapters

Adapters update separately, by version tag:

```bash
sudo ./publisher.sh platforms update
```

See [Versions](../platforms/manage.md#versions).

## Upgrade notes

Steps a particular upgrade needs once, newest first.

### Gateway clients moved to the database

`update --migrate` applies migration 019, which imports `data/gateway_clients/registry.json` (or `GATEWAY_CLIENTS_REGISTRY_FILE`, if `.env` sets it). It logs the entries in `mcc_mnc_overrides.json` without importing them. Delete both files afterwards.

### Adapters moved to the database

`update --migrate` and `manage.sh migrate` register adapters installed before the adapter registry moved to the database, and move their settings and files out of the code. The Docker container does it at every start.
