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
./publisher.sh platforms import                             # register adapter directories, move their files out of the code
./publisher.sh platforms exec <NAME> -- <COMMAND> [ARGS]    # run a command the adapter installs
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

## Files

| Directory | Holds |
|---|---|
| `PLATFORMS_ADAPTERS_DIR/<id>` | The adapter's code at its tag, replaced on every update |
| `PLATFORMS_ADAPTERS_VENV_DIR/<id>` | Its virtualenv |
| `PLATFORMS_ADAPTERS_CONFIG_DIR/<id>` | Its `credentials.json` |
| `PLATFORMS_ADAPTERS_STATE_DIR/<id>` | What it writes, such as databases |

`<id>` is the ID column of `platforms list`.

## An Adapter's Own Commands

Some adapters install admin commands, such as one that registers an OAuth client. `exec` runs one from the adapter's virtualenv with its config and state directories; put `--` before it:

```bash
./publisher.sh platforms exec mastodon -- mastodon-register --name RelaySMS --redirect-uri https://example.com/callback
```

## Writing an Adapter

Build it with the [adapter SDK](../sdk/README.md), then tag a release and `add` it.
