# Platforms Module

## Overview

This module handles the discovery, management, and installation of platform adapters.

## Adding Adapters from GitHub

You can add adapters directly from a GitHub repository using the CLI.

### Steps:

1. Navigate to the `platforms` directory.
2. Run the following command:

```bash
python cli.py add <GITHUB_URL>
```

Replace `<GITHUB_URL>` with the URL of the GitHub repository containing the adapter.

### Example:

```bash
python cli.py add https://github.com/example/adapter-repo.git
```

This will clone the repository, register the adapter, and make it available for use.
