# Platforms Module

## Overview

This module handles the discovery, management, and installation of platform adapters.

Adapters are registered in the `platform_adapters` database table. Their files are stored under paths configurable in `.env`:

```bash
PLATFORMS_ADAPTERS_DIR=data/platforms/adapters
PLATFORMS_ADAPTERS_VENV_DIR=data/platforms/venvs
PLATFORMS_ADAPTERS_ASSETS_DIR=data/platforms/assets
```

> [!IMPORTANT]
> Use `./publisher.sh platforms` (from the install directory) instead of calling `python3 -m publisher platforms` directly. It automatically resolves the install directory, loads `.env`, and runs as the correct **service user** (the account systemd runs `relaysms-publisher-*` as), whether invoked directly as that user or via `sudo`. Calling the CLI module directly as the wrong user can leave adapter directories owned incorrectly, causing the running services to fail to read/write them.

## Adding Adapters from GitHub

Adapters are installed at a version tag such as `v1.2.0`, the newest one unless you name it:

```bash
./publisher.sh platforms add <GITHUB_URL> [--tag TAG]
./publisher.sh platforms add https://github.com/example/adapter-repo --tag v1.2.0
```

For a repository without version tags yet, add `--branch` to use its default branch instead.

## Removing Adapters

You can remove an adapter by its name using the CLI.

### Steps

1. Run the following command from the project root:

```bash
./publisher.sh platforms remove <ADAPTER_NAME>
```

Replace `<ADAPTER_NAME>` with the name of the adapter you want to remove.

### Example

```bash
./publisher.sh platforms remove example-adapter
```

This will unregister the adapter and remove it from the system. It's refused while accounts are linked through the adapter: disable it with `./publisher.sh platforms disable <ADAPTER_NAME>` instead, or use `--force`.

## Updating Adapters

Moves one adapter, or all of them, to the newest version tag, or to the tag you name:

```bash
./publisher.sh platforms update [ADAPTER_NAME] [--tag TAG | --branch]
```

Each update clones the version and builds its virtualenv next to the running one, then switches over, so a failed update leaves the running version untouched. An update is refused if the installed tag now points to a different commit, since a release tag shouldn't move. `--branch` works as it does for `add`.

## Running an Adapter's Own CLI

Some adapters ship their own `cli.py` for admin tasks that aren't part of the runtime OAuth2/PNBA interface (for example, registering an OAuth client with a provider). You can run it without locating the adapter's directory or virtualenv by hand.

### Steps

1. Run the following command from the project root:

```bash
./publisher.sh platforms exec <ADAPTER_NAME> [--proto-id ID] [--cat-id ID] -- <ARGS...>
```

- Replace `<ADAPTER_NAME>` with the name of the adapter.
- Use `--proto-id`/`--cat-id` if the name alone matches more than one adapter.
- Put `--` before the adapter's own arguments so they aren't mistaken for `--proto-id`/`--cat-id`.
- If the adapter has no `cli.py`, this command will say so instead of running anything.

### Example

```bash
./publisher.sh platforms exec mastodon -- register -i
```

This runs the `mastodon` adapter's `cli.py` inside its own virtualenv with `register -i` as its arguments.

## Developing New Adapters

You can develop new adapters by cloning the [template repository](https://github.com/smswithoutborders/platform-adapter-template) and following its instructions.

### Steps

1. Clone the template repository:

```bash
git clone https://github.com/smswithoutborders/platform-adapter-template.git
```

2. Navigate to the cloned repository:

```bash
cd platform-adapter-template
```

3. Follow the instructions in the repository's README to implement your custom adapter.

4. Once your adapter is ready, you can add it to the system using the CLI as described in the [Adding Adapters from GitHub](#adding-adapters-from-github) section.
