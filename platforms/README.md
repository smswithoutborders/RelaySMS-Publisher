# Platforms Module

## Overview

This module handles the discovery, management, and installation of platform adapters.

## Adding Adapters from GitHub

You can add adapters directly from a GitHub repository using the CLI.

### Steps:

1. Run the following command from the project root:

```bash
python3 -m platforms.cli add <GITHUB_URL>
```

Replace `<GITHUB_URL>` with the URL of the GitHub repository containing the adapter.

### Example:

```bash
python3 -m platforms.cli add https://github.com/example/adapter-repo.git
```

This will clone the repository, register the adapter, and make it available for use.

## Removing Adapters

You can remove an adapter by its name using the CLI.

### Steps:

1. Run the following command from the project root:

```bash
python3 -m platforms.cli remove <ADAPTER_NAME>
```

Replace `<ADAPTER_NAME>` with the name of the adapter you want to remove.

### Example:

```bash
python3 -m platforms.cli remove example-adapter
```

This will unregister the adapter and remove it from the system.

## Developing New Adapters

You can develop new adapters by cloning the [template repository](https://github.com/smswithoutborders/platform-adapter-template) and following its instructions.

### Steps:

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
