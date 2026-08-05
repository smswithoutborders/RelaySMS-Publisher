# Platforms Module

## Overview

This module handles the discovery, management, and installation of platform adapters.

Adapter files and the registry are stored under paths configurable in `.env`:

```bash
PLATFORMS_ADAPTERS_DIR=platforms/adapters
PLATFORMS_ADAPTERS_VENV_DIR=platforms/adapters_venv
PLATFORMS_ADAPTERS_ASSETS_DIR=platforms/adapters_assets
PLATFORMS_REGISTRY_FILE=platforms/registry.json
```

> [!IMPORTANT]
> Use `./platforms.sh` (from the install directory) instead of calling `python3 -m platforms.cli` directly. It automatically resolves the install directory, loads `.env`, and runs as the correct **service user** (the account systemd runs `relaysms-publisher-*` as), whether invoked directly as that user or via `sudo`. Calling the CLI module directly as the wrong user can leave the registry file or adapter directories owned incorrectly, causing the running services to fail to read/write them.

## Adding Adapters from GitHub

You can add adapters directly from a GitHub repository using the CLI.

### Steps

1. Run the following command from the project root:

```bash
./platforms.sh add <GITHUB_URL>
```

Replace `<GITHUB_URL>` with the URL of the GitHub repository containing the adapter.

### Example

```bash
./platforms.sh add https://github.com/example/adapter-repo.git
```

This will clone the repository, register the adapter, and make it available for use.

## Removing Adapters

You can remove an adapter by its name using the CLI.

### Steps

1. Run the following command from the project root:

```bash
./platforms.sh remove <ADAPTER_NAME>
```

Replace `<ADAPTER_NAME>` with the name of the adapter you want to remove.

### Example

```bash
./platforms.sh remove example-adapter
```

This will unregister the adapter and remove it from the system.

## Updating Adapters

You can update adapters by pulling the latest changes from their Git repositories using the CLI.

### Steps

1. Run the following command from the project root:

```bash
./platforms.sh update [ADAPTER_NAME] [--install]
```

- Replace `[ADAPTER_NAME]` with the name of the adapter you want to update. If omitted, all adapters will be updated.
- Use the `--install` flag to reinstall dependencies after updating.

### Examples

Update a specific adapter:

```bash
./platforms.sh update example-adapter
```

Update all adapters and reinstall dependencies:

```bash
./platforms.sh update --install
```

This will pull the latest changes for the specified adapter(s) and optionally reinstall dependencies.

## Running an Adapter's Own CLI

Some adapters ship their own `cli.py` for admin tasks that aren't part of the runtime OAuth2/PNBA interface (for example, registering an OAuth client with a provider). You can run it without locating the adapter's directory or virtualenv by hand.

### Steps

1. Run the following command from the project root:

```bash
./platforms.sh exec <ADAPTER_NAME> [--proto-id ID] [--cat-id ID] -- <ARGS...>
```

- Replace `<ADAPTER_NAME>` with the name of the adapter.
- Use `--proto-id`/`--cat-id` if the name alone matches more than one adapter.
- Put `--` before the adapter's own arguments so they aren't mistaken for `--proto-id`/`--cat-id`.
- If the adapter has no `cli.py`, this command will say so instead of running anything.

### Example

```bash
./platforms.sh exec mastodon -- register -i
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
