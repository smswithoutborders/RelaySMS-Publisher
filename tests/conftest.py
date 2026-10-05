# SPDX-License-Identifier: GPL-3.0-only

import dataclasses
import os

import pytest

# Set before config is imported, so tests ignore the local .env and use fixed values.
os.environ.update(
    LOAD_DOTENV="false",
    DATABASE_DIALECT="sqlite",
    SQLITE_DATABASE_PATH=":memory:",
    DATA_ENCRYPTION_KEY="11" * 32,
)

pytest_plugins = ["tests.fixtures"]


@pytest.fixture
def set_config(monkeypatch):
    """Change fields of a section bound in a module, for the current test only."""

    def apply(module, name: str, **changes):
        updated = dataclasses.replace(getattr(module, name), **changes)
        monkeypatch.setattr(module, name, updated)

    return apply
