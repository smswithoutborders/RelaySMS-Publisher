# SPDX-License-Identifier: GPL-3.0-only
"""Each dialect test runs on SQLite, SQLCipher and real servers in rootless podman."""

import dataclasses
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import psycopg2
import pymysql
import pytest
from alembic import command
from alembic.config import Config

from publisher import db
from publisher.config import DatabaseConfig, ServerDatabaseConfig
from publisher.db import Base

REPO = Path(__file__).resolve().parents[2]
PASSWORD = "relaysms-test"
DATABASE = "relaysms_test"
READY_TIMEOUT_SECONDS = 180


@dataclass(frozen=True)
class Server:
    image: str
    dialect: str
    port: int
    user: str
    # podman run options, then the server's own flags.
    options: tuple[str, ...]
    flags: tuple[str, ...]


POSTGRES_FLAGS = ("fsync=off", "synchronous_commit=off", "full_page_writes=off")
MYSQL_FLAGS = ("--innodb-flush-log-at-trx-commit=0", "--innodb-doublewrite=0")
# What Ubuntu 24.04 installs. The data is thrown away, so it lives in memory and
# nothing waits for the disk.
SERVERS = {
    "postgres": Server(
        "docker.io/library/postgres:16",
        "postgres",
        5432,
        "postgres",
        ("-e", f"POSTGRES_PASSWORD={PASSWORD}", "--tmpfs", "/var/lib/postgresql/data"),
        tuple(arg for flag in POSTGRES_FLAGS for arg in ("-c", flag)),
    ),
    "mysql": Server(
        "docker.io/library/mysql:8.0",
        "mysql",
        3306,
        "root",
        ("-e", f"MYSQL_ROOT_PASSWORD={PASSWORD}", "--tmpfs", "/var/lib/mysql"),
        ("--skip-log-bin", *MYSQL_FLAGS),
    ),
    "mariadb": Server(
        "docker.io/library/mariadb:10.11",
        "mysql",
        3306,
        "root",
        ("-e", f"MARIADB_ROOT_PASSWORD={PASSWORD}", "--tmpfs", "/var/lib/mysql"),
        MYSQL_FLAGS,
    ),
}
# A host with MariaDB installed confines every mariadbd, even in a container,
# and the profile blocks the signals that stop it.
MARIADB_HOST_PROFILE = Path("/etc/apparmor.d/mariadbd")
DIALECTS = ["sqlite", "sqlcipher", *SERVERS]


def podman(*args: str) -> str:
    result = subprocess.run(
        ["podman", *args], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        pytest.fail(f"podman {' '.join(args)}\n{result.stderr}")
    return result.stdout


def _connect(name: str, port: int) -> None:
    server = SERVERS[name]
    common = {
        "host": "127.0.0.1",
        "port": port,
        "user": server.user,
        "password": PASSWORD,
    }
    if server.dialect == "postgres":
        conn = psycopg2.connect(**common, dbname="postgres", connect_timeout=3)
    else:
        conn = pymysql.connect(**common, connect_timeout=3)
    conn.close()


def _wait_ready(name: str, container: str, port: int) -> None:
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    while True:
        try:
            _connect(name, port)
            return
        except Exception:
            if time.monotonic() > deadline:
                logs = podman("logs", "--tail", "40", container)
                pytest.fail(f"{SERVERS[name].image} didn't accept connections\n{logs}")
            time.sleep(1)


@pytest.fixture(scope="session")
def server_port():
    """Starts a server on first use and returns its port on the host."""
    if not shutil.which("podman"):
        pytest.skip("podman is not installed")
    if podman("info", "--format", "{{.Host.Security.Rootless}}").strip() != "true":
        pytest.skip("needs rootless podman")

    containers, ports = [], {}

    def start(name: str) -> int:
        if name == "mariadb" and MARIADB_HOST_PROFILE.exists():
            pytest.skip(f"{MARIADB_HOST_PROFILE} stops MariaDB running in podman")
        if name not in ports:
            server = SERVERS[name]
            container = f"relaysms-dialect-{name}-{uuid.uuid4().hex[:8]}"
            podman(
                "run", "-d", "--name", container,
                "-p", f"127.0.0.1::{server.port}",
                *server.options, server.image, *server.flags,
            )  # fmt: skip
            containers.append(container)
            port = int(podman("port", container, str(server.port)).rsplit(":", 1)[1])
            _wait_ready(name, container, port)
            ports[name] = port
        return ports[name]

    yield start
    for container in containers:
        subprocess.run(["podman", "rm", "-f", container], capture_output=True)


@pytest.fixture(scope="session")
def alembic_config():
    return Config(str(REPO / "alembic.ini"))


@pytest.fixture(scope="module", params=DIALECTS)
def dialect(request, tmp_path_factory, alembic_config):
    """Points the app at the dialect's migrated database, with field encryption on."""
    name = request.param
    config = dataclasses.replace(
        DatabaseConfig.get(),
        field_encryption_enabled=True,
        field_encryption_key=bytes.fromhex("33" * 32),
    )
    if name in SERVERS:
        port = request.getfixturevalue("server_port")(name)
        database = ServerDatabaseConfig(
            "127.0.0.1", port, SERVERS[name].user, PASSWORD, DATABASE
        )
        dialect = SERVERS[name].dialect
        config = dataclasses.replace(config, dialect=dialect, **{dialect: database})
    else:
        encrypted = name == "sqlcipher"
        config = dataclasses.replace(
            config,
            dialect="sqlite",
            sqlite_path=str(tmp_path_factory.mktemp(name) / "relaysms.db"),
            encryption_enabled=encrypted,
            encryption_key=bytes.fromhex("22" * 32) if encrypted else None,
        )

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(DatabaseConfig, "get", classmethod(lambda cls: config))
        db.dispose_engine()
        command.upgrade(alembic_config, "head")
        yield name
        db.dispose_engine()


@pytest.fixture(autouse=True)
def empty_tables(dialect):
    yield
    with db.get_engine().begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
