# SPDX-License-Identifier: GPL-3.0-only
"""The database session shared by the CLI commands."""

from collections.abc import Generator
from contextlib import contextmanager

import click
from sqlalchemy.orm import Session

from publisher.db import get_session
from publisher.errors import PublisherError


@contextmanager
def session() -> Generator[Session]:
    """Commit on success; show domain errors as CLI errors."""
    try:
        with get_session() as db:
            yield db
    except PublisherError as e:
        raise click.ClickException(str(e)) from e
