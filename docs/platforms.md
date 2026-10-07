# Platform Adapters

Each platform (Gmail, X, Telegram, ...) is served by an adapter installed from its own GitHub repository. Adapters are registered in the `platform_adapters` table; their files live under `data/platforms/` (`PLATFORMS_ADAPTERS_*` in `.env`).

> [!IMPORTANT]
> Run these commands with `./publisher.sh` from the install directory, not `python3 -m publisher`. It runs as the service user, so the services can still read the adapter files.

## Commands

```bash
./publisher.sh platforms add <GITHUB_URL> [--tag TAG]       # install the newest, or a given, version tag
./publisher.sh platforms update [NAME] [--tag TAG]          # move one adapter, or all, to a version tag
./publisher.sh platforms list                               # every adapter, disabled ones included
./publisher.sh platforms disable <NAME>                     # hide it from users; it still revokes tokens
./publisher.sh platforms enable <NAME>                      # offer it again
./publisher.sh platforms remove <NAME> [--force]            # uninstall
./publisher.sh platforms import                             # register adapter directories not yet in the database
./publisher.sh platforms exec <NAME> -- <ARGS...>           # run the adapter's own cli.py
```

Commands taking a name also take `--proto-id` and `--cat-id`, for when a name matches more than one adapter. Administrators can do the same over the [REST API](rest.md#managing-platform-adapters), installing only from orgs in `PLATFORMS_GITHUB_ORGS`.

## Versions

Adapters are installed and updated by version tag, such as `v1.2.0`. For a repository without tags yet, pass `--branch` to use its default branch.

An update builds the new version and its virtualenv beside the running one, then switches over, so a failed update leaves the running version in place.

> [!NOTE]
> An update is refused if the installed tag now points to a different commit. Release tags shouldn't move.

## Removing

> [!WARNING]
> `remove` is refused while accounts are linked through the adapter, since their tokens can only be revoked through it. Disable it instead. `--force` removes it anyway and leaves those tokens unrevocable.

## An Adapter's Own CLI

Some adapters ship a `cli.py` for admin tasks, such as registering an OAuth client. `exec` runs it in the adapter's virtualenv; put `--` before its arguments:

```bash
./publisher.sh platforms exec mastodon -- register -i
```

## Writing an Adapter

Start from the [adapter template](https://github.com/smswithoutborders/platform-adapter-template) and follow its README, then tag a release and `add` it.
