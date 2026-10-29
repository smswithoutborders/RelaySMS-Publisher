# Upgrading

A server install follows the branch it was installed from, `main` by default.

## Before you upgrade

1. [Back up](backup-restore.md). Migrations can't be undone, so going back to older code needs the backup.
2. From the install directory, note the current commit, to roll back to:

   ```bash
   sudo git rev-parse HEAD
   ```

## Update a server install

From the install directory:

```bash
sudo ./manage.sh update --migrate
sudo ./sync-env.sh
sudo ./manage.sh check
sudo ./manage.sh restart
```

1. `update --migrate` stops the services, pulls the code, reinstalls the dependencies, rebuilds, applies pending migrations and starts the services again. When the install serves this manual, it rebuilds it too.
2. `sync-env.sh` adds the settings the new `template.env` has and `.env` lacks, showing the change before writing it.
3. `check` reports any setting still missing or invalid. Fill it in `.env`.
4. `restart` loads the new settings.

When `.env` has an invalid setting, `update` still restarts every service, then exits with an error ([fix](troubleshooting.md#update-ends-with-env-has-errors)).

If the update changed the nginx template, which `sudo git diff --stat ORIG_HEAD HEAD -- deploy/nginx` lists, render the site again:

```bash
sudo ./manage.sh nginx
```

If you edited tracked files that the update changes, `update` refuses to pull. Discard the edits or `git stash` them, then run `update` again.

## Roll back

1. Take the commit you noted [before upgrading](#before-you-upgrade).
2. If the update applied migrations, [restore the backup](backup-restore.md#restore) taken before it.
3. Check out that commit and rebuild. `--pulled` skips the pull that would undo the checkout:

   ```bash
   sudo git checkout <COMMIT>
   sudo ./manage.sh update --pulled
   ```

To follow the branch again later, run `sudo git checkout <BRANCH>`, then `sudo ./manage.sh update --migrate`.

## Update with Docker

```bash
git pull --recurse-submodules
docker compose up -d --build
```

The container applies new migrations when it starts.

## Update adapters

Adapters update separately, by version tag:

```bash
sudo ./publisher.sh platforms update
```

See [Versions](../platforms/manage.md#versions).
