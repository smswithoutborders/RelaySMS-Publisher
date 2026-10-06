# SPDX-License-Identifier: GPL-3.0-only

import shutil

import pytest
from git import Repo
from sqlalchemy import select

from publisher import db
from publisher.models import platform_adapter as platform_adapters
from publisher.models.audit_event import AuditEvent
from publisher.models.platform_adapter import OAUTH2, PNBA, PlatformAdapter
from publisher.platforms import manager
from tests.helpers import MANIFEST, adapter_repo, add_adapter, commit_manifest


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
    source = adapter_repo(tmp_path / "src")
    url = str(source.working_tree_dir)

    with db.get_session() as session:
        adapter = manager.add_from_github(session, url)
        adapter_id = adapter.id
    assert _rows() == [("gmail", OAUTH2)]
    assert (tmp_path / "adapters" / adapter_id / "manifest.ini").is_file()

    second_commit = commit_manifest(source, "gmail", PNBA)
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
    url = str(adapter_repo(tmp_path / "src").working_tree_dir)

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
        source = adapter_repo(tmp_path / "src" / name, name, proto_id)
        Repo.clone_from(str(source.working_tree_dir), adapters_dir / f"{name}-id")
    # Same platform and protocol as gmail, so it's skipped.
    twin = Repo(adapters_dir / "twin-id")
    commit_manifest(twin, "gmail", OAUTH2)
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


def _repo_with_requirements(tmp_path):
    repo = adapter_repo(tmp_path / "src")
    (tmp_path / "src" / "requirements.txt").write_text("requests\n")
    repo.index.add(["requirements.txt"])
    repo.index.commit("add requirements")
    return str(repo.working_tree_dir)


def _add(url):
    with db.get_session() as session:
        return manager.add_from_github(session, url).id


@pytest.mark.usefixtures("test_db")
def test_a_failed_clone_names_the_reason_and_leaves_nothing(tmp_path):
    with pytest.raises(manager.AdapterError, match="does not exist"):
        _add(str(tmp_path / "missing"))

    assert list((tmp_path / "adapters").iterdir()) == []
    assert _rows() == []


@pytest.mark.usefixtures("test_db")
def test_the_same_url_cant_be_added_twice(tmp_path):
    url = str(adapter_repo(tmp_path / "src").working_tree_dir)
    _add(url)

    with pytest.raises(manager.AdapterError, match="already installed"):
        _add(url)


@pytest.mark.parametrize(
    "manifest, error",
    [
        ("[other]\nname = x\n", "Invalid manifest.ini"),
        ("[platform]\nname = gmail\n", "needs name, display_name"),
        (MANIFEST.format(name="gmail", proto_id="oauth2"), "Invalid manifest value"),
    ],
)
@pytest.mark.usefixtures("test_db")
def test_a_bad_manifest_is_rejected_and_rolled_back(tmp_path, manifest, error):
    repo = adapter_repo(tmp_path / "src")
    (tmp_path / "src" / "manifest.ini").write_text(manifest)
    repo.index.add(["manifest.ini"])
    repo.index.commit("break the manifest")

    with pytest.raises(manager.AdapterError, match=error):
        _add(str(repo.working_tree_dir))

    assert list((tmp_path / "adapters").iterdir()) == []


@pytest.mark.usefixtures("test_db")
def test_dependencies_install_into_the_adapter_venv(tmp_path, monkeypatch):
    url = _repo_with_requirements(tmp_path)
    commands = []
    monkeypatch.setattr(manager.subprocess, "check_call", commands.append)

    adapter_id = _add(url)

    venv = tmp_path / "venvs" / adapter_id
    assert commands[0][1:] == ["-m", "venv", str(venv)]
    assert commands[1][0] == str(venv / "bin/pip3")
    assert commands[1][-1] == str(
        tmp_path / "adapters" / adapter_id / "requirements.txt"
    )


@pytest.mark.usefixtures("test_db")
def test_a_failed_dependency_install_rolls_back(tmp_path, monkeypatch):
    url = _repo_with_requirements(tmp_path)

    def fail(command):
        raise manager.subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(manager.subprocess, "check_call", fail)

    with pytest.raises(manager.AdapterError, match="Dependency installation failed"):
        _add(url)
    assert list((tmp_path / "adapters").iterdir()) == []
    assert _rows() == []


@pytest.mark.usefixtures("test_db")
def test_a_failed_pull_leaves_the_adapter_unchanged(tmp_path):
    source = adapter_repo(tmp_path / "src")
    adapter_id = _add(str(source.working_tree_dir))
    shutil.rmtree(tmp_path / "src")

    with (
        pytest.raises(manager.AdapterError, match="Pulling 'gmail' failed"),
        db.get_session() as session,
    ):
        manager.update(session, session.get(PlatformAdapter, adapter_id))
    assert _actions() == ["platforms.add"]


@pytest.mark.usefixtures("test_db")
def test_remove_refuses_an_id_that_points_outside_the_adapters_dir():
    with db.get_session() as session:
        adapter = PlatformAdapter(id="..", name="x", proto_id=OAUTH2)
        with pytest.raises(manager.AdapterError, match="Unsafe adapter id"):
            manager.remove(session, adapter)


@pytest.mark.usefixtures("test_db")
def test_enabling_an_enabled_adapter_changes_nothing():
    add_adapter("gmail", OAUTH2)

    with db.get_session() as session:
        manager.set_enabled(session, session.get(PlatformAdapter, "gmail-0"), True)

    assert _actions() == []
