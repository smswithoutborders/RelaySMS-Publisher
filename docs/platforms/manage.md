# Managing adapters

Each platform (Gmail, Telegram, Mastodon, ...) is served by an adapter installed from its own GitHub repository. Its files live under `data/platforms/` (see [Files](#files)).

Run these commands from the install directory with [`publisher.sh`](../operating/services.md#publishersh), which runs them as the service user.

## Commands

```bash
sudo ./publisher.sh platforms add <GITHUB_URL> [--tag TAG]       # install the newest, or a given, version tag
sudo ./publisher.sh platforms update [NAME] [--tag TAG]          # move one adapter, or all, to a version tag
sudo ./publisher.sh platforms list                               # every adapter, disabled ones included
sudo ./publisher.sh platforms disable <NAME>                     # hide it from users; it still revokes tokens
sudo ./publisher.sh platforms enable <NAME>                      # offer it again
sudo ./publisher.sh platforms remove <NAME> [--force]            # uninstall
sudo ./publisher.sh platforms config show <NAME>                 # its settings, without secret values
sudo ./publisher.sh platforms config set <NAME> KEY=VALUE|KEY    # change settings; a bare KEY asks for the value
sudo ./publisher.sh platforms setup <NAME> [--input KEY=VALUE]   # run the adapter's setup and save its settings
sudo ./publisher.sh platforms import                             # register adapter directories, move their files out of the code
sudo ./publisher.sh platforms exec <NAME> -- <COMMAND> [ARGS]    # run a command the adapter installs
```

Commands taking a name also take `--proto-id` and `--cat-id`, for when a name matches more than one adapter. Administrators can do the same over the [REST API](../reference/rest-api.md#managing-platform-adapters), but only from GitHub orgs listed in `PLATFORMS_GITHUB_ORGS`.

## Versions

Adapters are installed and updated by version tag, such as `v1.2.0`, so a repository needs one before it can be added.

An update builds the new version and its virtualenv beside the running one, then switches over, so a failed update leaves the running version in place.

> [!NOTE]
> An update is refused if the installed tag now points to a different commit. Publish a new tag instead of moving one.

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

## Settings

An adapter reads its settings, such as API keys, from `credentials.json` in its config directory. Its `adapter.toml` declares each one. Lists are comma-separated.

```bash
sudo ./publisher.sh platforms config set rmail smtp_host=smtp.example.com smtp_port=465
sudo ./publisher.sh platforms config set rmail smtp_password
sudo ./publisher.sh platforms config set rmail --unset alias_prefix
```

`config set` changes only the keys given. `setup` is for adapters whose settings come from the platform (e.g. a registered app for Mastodon, a downloaded client file for Gmail) and replaces all of them. `--input KEY=@PATH` reads a file:

```bash
sudo ./publisher.sh platforms setup gmail --input client_file=@client_secret.json
```

## An adapter's own commands

An adapter may install admin commands. `exec` runs one from the adapter's virtualenv with its config and state directories; put `--` before it:

```bash
sudo ./publisher.sh platforms exec <NAME> -- <COMMAND> --help
```

## Writing an adapter

Build it with the [adapter SDK](https://github.com/smswithoutborders/RelaySMS-Publisher/tree/main/sdk), then tag a release and `add` it.
