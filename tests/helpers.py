# SPDX-License-Identifier: GPL-3.0-only
"""Helpers for tests that create credentials and log in."""

import base64
from collections.abc import Iterable
from pathlib import Path

from fastapi.testclient import TestClient
from git import Repo

from publisher import credentials, db
from publisher.models.credential import ALL_SCOPES, Scope
from publisher.models.platform_adapter import PROTOCOL_NAMES, PlatformAdapter
from publisher.models.token import create as create_token
from publisher.models.token_hash import create as create_token_hash

USERNAME = "ops"


def create_credential(username: str, scopes: Iterable[str] = ALL_SCOPES) -> str:
    with db.get_session() as session:
        _, password = credentials.create(
            session, username, frozenset(Scope(s) for s in scopes)
        )
    return password


def add_adapter(name: str, proto_id: int, cat_id: int = 0) -> PlatformAdapter:
    """Register an adapter row; its id is "<name>-<proto_id>"."""
    with db.get_session() as session:
        adapter = PlatformAdapter(
            id=f"{name}-{proto_id}",
            source_url=f"https://github.com/smswithoutborders/{name}",
            commit="0" * 40,
            name=name,
            display_name=name.title(),
            proto_id=proto_id,
            cat_id=cat_id,
        )
        session.add(adapter)
    return adapter


def link_account(platform: str, proto_id: int) -> int:
    """Store a token as linking an account would; return its row id."""
    with db.get_session() as session:
        token = create_token(
            session,
            platform=platform,
            cat_id=0,
            proto_id=proto_id,
            token_data={"account_id": "user@example.org", "token": {"t": "1"}},
        )
        create_token_hash(session, token.id)
        return token.id


def basic_auth(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def get_etag(client: TestClient, headers: dict[str, str], url: str) -> str:
    response = client.get(url, headers=headers)
    assert response.status_code == 200, response.text
    return response.headers["etag"]


def login(client: TestClient, password: str, username: str = USERNAME):
    return client.post(
        "/v1/auth/login", json={"username": username, "password": password}
    )


def can_log_in(username: str, password: str) -> bool:
    with db.get_session() as session:
        return credentials.authenticate(session, username, password) is not None


MANIFEST = """entry = "adapter:Adapter"
name = "{name}"
display_name = "{name}"
protocol = "{protocol}"
category = "email"
"""


def adapter_repo(
    path: Path,
    name: str = "gmail",
    proto_id: int = 0,
    tag: str | None = "v1.0.0",
) -> Repo:
    """A local git repo laid out like an adapter."""
    path.mkdir(parents=True)
    repo = Repo.init(path)
    (path / "pyproject.toml").write_text(f'[project]\nname = "{name}-adapter"\n')
    commit_manifest(repo, name, proto_id, tag)
    return repo


def commit_manifest(
    repo: Repo, name: str, proto_id: int, tag: str | None = None
) -> str:
    """Write and commit adapter.toml, tagged if tag; return the commit's sha."""
    path = repo.working_tree_dir
    protocol = PROTOCOL_NAMES[proto_id]
    with open(f"{path}/adapter.toml", "w") as f:
        f.write(MANIFEST.format(name=name, protocol=protocol))
    repo.index.add(["pyproject.toml", "adapter.toml"])
    commit = repo.index.commit(f"{name} {proto_id}")
    if tag:
        repo.create_tag(tag, ref=commit.hexsha, force=True)
    return commit.hexsha
