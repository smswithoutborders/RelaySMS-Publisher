# SPDX-License-Identifier: GPL-3.0-only

import pytest
from git import Repo
from sqlalchemy import select

from publisher import db
from publisher.models import platform_adapter as platform_adapters
from publisher.models.audit_event import AuditEvent
from publisher.models.platform_adapter import OAUTH2, PNBA, PlatformAdapter
from publisher.platforms import manager
from tests.helpers import add_adapter


@pytest.fixture(autouse=True)
def _platforms_config(platforms_config):
    platforms_config(github_orgs=["smswithoutborders"])


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/smswithoutborders/gmail-oauth2-adapter",
        "https://github.com/SMSWithoutBorders/gmail-oauth2-adapter.git",
        "https://github.com/smswithoutborders/gmail-oauth2-adapter/",
    ],
)
def test_allowed_github_urls(url):
    assert manager.is_allowed_github_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/someone-else/gmail-oauth2-adapter",
        "http://github.com/smswithoutborders/gmail-oauth2-adapter",
        "https://gitlab.com/smswithoutborders/gmail-oauth2-adapter",
        "https://github.com.evil.example/smswithoutborders/repo",
        "https://user@github.com/smswithoutborders/repo",
        "https://github.com:8443/smswithoutborders/repo",
        "https://github.com/smswithoutborders/repo/tree/main",
        "https://github.com/smswithoutborders/..",
        "https://github.com/smswithoutborders/repo?ref=x",
        "git@github.com:smswithoutborders/repo.git",
        "file:///etc/passwd",
    ],
)
def test_rejected_github_urls(url):
    assert not manager.is_allowed_github_url(url)


def test_empty_allowlist_rejects_everything(platforms_config):
    platforms_config(github_orgs=[])

    assert not manager.is_allowed_github_url(
        "https://github.com/smswithoutborders/gmail-oauth2-adapter"
    )


MANIFEST = """[platform]
name = {name}
display_name = {name}
proto_id = {proto_id}
cat_id = 0
"""


def _source_repo(path, name="gmail", proto_id=OAUTH2):
    """A local git repo laid out like an adapter, with no requirements.txt."""
    path.mkdir(parents=True)
    repo = Repo.init(path)
    for file in ("main.py", "config.ini"):
        (path / file).write_text("")
    _commit_manifest(repo, name, proto_id)
    return repo


def _commit_manifest(repo, name, proto_id):
    path = repo.working_tree_dir
    with open(f"{path}/manifest.ini", "w") as f:
        f.write(MANIFEST.format(name=name, proto_id=proto_id))
    repo.index.add(["main.py", "config.ini", "manifest.ini"])
    return repo.index.commit(f"{name} {proto_id}").hexsha


def _rows():
    with db.get_session() as session:
        return [(a.name, a.proto_id) for a in platform_adapters.find(session)]


def _actions():
    with db.get_session() as session:
        return list(session.scalars(select(AuditEvent.action).order_by(AuditEvent.id)))


@pytest.mark.usefixtures("test_db")
def test_adapters_resolve_by_platform_and_protocol():
    add_adapter("gmail", OAUTH2)
    add_adapter("telegram", PNBA)

    with db.get_session() as session:
        found = platform_adapters.get_for_protocol(session, "Gmail", OAUTH2)
        assert found.name == "gmail"
        with pytest.raises(NotImplementedError):
            platform_adapters.get_for_protocol(session, "gmail", PNBA)


@pytest.mark.usefixtures("test_db")
def test_add_update_and_remove(tmp_path):
    source = _source_repo(tmp_path / "src")
    url = str(source.working_tree_dir)

    with db.get_session() as session:
        adapter = manager.add_from_github(session, url)
        adapter_id = adapter.id
    assert _rows() == [("gmail", OAUTH2)]
    assert (tmp_path / "adapters" / adapter_id / "manifest.ini").is_file()

    second_commit = _commit_manifest(source, "gmail", PNBA)
    with db.get_session() as session:
        manager.update(session, session.get(PlatformAdapter, adapter_id))
    with db.get_session() as session:
        assert session.get(PlatformAdapter, adapter_id).commit == second_commit
    assert _rows() == [("gmail", PNBA)]

    with db.get_session() as session:
        manager.remove(session, session.get(PlatformAdapter, adapter_id))
    assert _rows() == []
    assert not (tmp_path / "adapters" / adapter_id).exists()
    assert _actions() == ["platforms.add", "platforms.update", "platforms.remove"]


@pytest.mark.usefixtures("test_db")
def test_add_rejects_a_second_adapter_for_the_same_platform(tmp_path):
    add_adapter("gmail", OAUTH2)
    url = str(_source_repo(tmp_path / "src").working_tree_dir)

    with (
        pytest.raises(manager.AdapterError, match="already installed"),
        db.get_session() as session,
    ):
        manager.add_from_github(session, url)

    assert list((tmp_path / "adapters").iterdir()) == []


@pytest.mark.usefixtures("test_db")
def test_import_registers_unregistered_clones_only(tmp_path):
    adapters_dir = tmp_path / "adapters"
    for name, proto_id in (("gmail", OAUTH2), ("telegram", PNBA), ("twin", OAUTH2)):
        source = _source_repo(tmp_path / "src" / name, name, proto_id)
        Repo.clone_from(str(source.working_tree_dir), adapters_dir / f"{name}-id")
    # Same platform and protocol as gmail, so it's skipped.
    twin = Repo(adapters_dir / "twin-id")
    _commit_manifest(twin, "gmail", OAUTH2)
    (adapters_dir / "not-an-adapter").mkdir()
    add_adapter("telegram", PNBA)

    with db.get_session() as session:
        imported = manager.import_from_disk(session)
        assert [a.name for a in imported] == ["gmail"]
        assert imported[0].source_url.endswith("src/gmail")
        assert imported[0].commit

    assert _rows() == [("gmail", OAUTH2), ("telegram", PNBA)]


@pytest.mark.usefixtures("test_db")
def test_a_concurrent_change_is_a_conflict():
    add_adapter("gmail", OAUTH2)
    with (
        pytest.raises(manager.AdapterConflictError),
        db.get_session() as stale,
    ):
        adapter = stale.get(PlatformAdapter, "gmail-0")
        with db.get_session() as other:
            manager.set_enabled(other, other.get(PlatformAdapter, "gmail-0"), False)
        manager.set_enabled(stale, adapter, False)
