# SPDX-License-Identifier: GPL-3.0-only

import subprocess
from pathlib import Path

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
        return [
            (a.name, a.proto_id)
            for a in platform_adapters.find(session, include_disabled=True)
        ]


def _actions():
    with db.get_session() as session:
        return list(session.scalars(select(AuditEvent.action).order_by(AuditEvent.id)))


def _install(url, tag=None, **options):
    with db.get_session() as session:
        adapter = manager.install(session, str(url), tag, log=[], **options)
    manager.activate(adapter)
    return adapter.id, adapter.tag


def _update(adapter_id, tag=None, **options):
    with db.get_session() as session:
        adapter = session.get(PlatformAdapter, adapter_id)
        manager.update(session, adapter, tag, log=[], **options)
    manager.activate(adapter)


def _adapter(adapter_id):
    with db.get_session() as session:
        return session.get(PlatformAdapter, adapter_id)


def _siblings(tmp_path):
    """Leftover .new or .old directories from a build or swap."""
    return sorted(p.name for p in tmp_path.glob("*/*") if p.suffix in (".new", ".old"))


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
def test_install_takes_the_newest_version_tag(tmp_path):
    repo = adapter_repo(tmp_path / "src", tag="v1.2.0")
    newest = commit_manifest(repo, "gmail", OAUTH2, tag="v1.10.0")
    commit_manifest(repo, "gmail", OAUTH2, tag="nightly")

    adapter_id, tag = _install(repo.working_tree_dir)

    assert tag == "v1.10.0"
    assert _adapter(adapter_id).commit == newest
    assert (tmp_path / "adapters" / adapter_id / "manifest.ini").is_file()
    assert _siblings(tmp_path) == []


@pytest.mark.usefixtures("test_db")
def test_install_a_named_tag(tmp_path):
    repo = adapter_repo(tmp_path / "src", tag="v1.0.0")
    commit_manifest(repo, "gmail", OAUTH2, tag="v2.0.0")

    assert _install(repo.working_tree_dir, "v1.0.0")[1] == "v1.0.0"


@pytest.mark.usefixtures("test_db")
def test_an_untagged_repo_installs_only_from_its_branch(tmp_path):
    repo = adapter_repo(tmp_path / "src", tag=None)

    with pytest.raises(manager.AdapterError, match="no version tags"):
        _install(repo.working_tree_dir)
    adapter_id, tag = _install(repo.working_tree_dir, branch=True)

    assert tag is None
    assert _adapter(adapter_id).commit == repo.head.commit.hexsha


@pytest.mark.usefixtures("test_db")
def test_update_swaps_in_the_new_version(tmp_path):
    repo = adapter_repo(tmp_path / "src")
    adapter_id, _ = _install(repo.working_tree_dir)
    commit_manifest(repo, "gmail", PNBA, tag="v2.0.0")

    _update(adapter_id)

    adapter = _adapter(adapter_id)
    assert (adapter.tag, adapter.proto_id) == ("v2.0.0", PNBA)
    manifest = (tmp_path / "adapters" / adapter_id / "manifest.ini").read_text()
    assert "proto_id = 1" in manifest
    assert _siblings(tmp_path) == []
    assert _actions() == ["platforms.add", "platforms.update"]


@pytest.mark.usefixtures("test_db")
def test_a_moved_tag_is_refused(tmp_path):
    repo = adapter_repo(tmp_path / "src")
    adapter_id, _ = _install(repo.working_tree_dir)
    installed = _adapter(adapter_id).commit
    commit_manifest(repo, "gmail", OAUTH2, tag="v1.0.0")

    with pytest.raises(manager.AdapterError, match="now points to"):
        _update(adapter_id, "v1.0.0")

    assert _adapter(adapter_id).commit == installed
    assert _siblings(tmp_path) == []


@pytest.mark.usefixtures("test_db")
def test_a_failed_build_keeps_the_running_version(tmp_path):
    repo = adapter_repo(tmp_path / "src")
    adapter_id, _ = _install(repo.working_tree_dir)
    (tmp_path / "src" / "main.py").unlink()
    repo.index.remove(["main.py"])
    repo.index.commit("drop main.py")
    repo.create_tag("v2.0.0")

    with pytest.raises(manager.AdapterError, match="missing main"):
        _update(adapter_id)

    assert _adapter(adapter_id).tag == "v1.0.0"
    assert (tmp_path / "adapters" / adapter_id / "main.py").is_file()
    assert _siblings(tmp_path) == []


@pytest.mark.usefixtures("test_db")
def test_remove_deletes_the_row_and_files(tmp_path):
    adapter_id, _ = _install(adapter_repo(tmp_path / "src").working_tree_dir)

    with db.get_session() as session:
        adapter = session.get(PlatformAdapter, adapter_id)
        manager.remove(session, adapter)
    manager.delete_files(adapter)

    assert _rows() == []
    assert not (tmp_path / "adapters" / adapter_id).exists()
    assert _actions() == ["platforms.add", "platforms.remove"]


@pytest.mark.usefixtures("test_db")
def test_add_rejects_a_second_adapter_for_the_same_platform(tmp_path):
    add_adapter("gmail", OAUTH2)

    with pytest.raises(manager.AdapterError, match="already installed"):
        _install(adapter_repo(tmp_path / "src").working_tree_dir)

    assert list((tmp_path / "adapters").iterdir()) == []


@pytest.mark.usefixtures("test_db")
def test_the_same_url_cant_be_added_twice(tmp_path):
    url = adapter_repo(tmp_path / "src").working_tree_dir
    _install(url)

    with pytest.raises(manager.AdapterError, match="already installed"):
        _install(url)


@pytest.mark.usefixtures("test_db")
def test_a_failed_clone_names_the_reason_and_leaves_nothing(tmp_path):
    with pytest.raises(manager.AdapterError, match="does not exist"):
        _install(tmp_path / "missing", "v1.0.0")

    assert list((tmp_path / "adapters").iterdir()) == []
    assert _rows() == []


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
    repo = adapter_repo(tmp_path / "src", tag=None)
    (tmp_path / "src" / "manifest.ini").write_text(manifest)
    repo.index.add(["manifest.ini"])
    repo.create_tag("v1.0.0", ref=repo.index.commit("break the manifest").hexsha)

    with pytest.raises(manager.AdapterError, match=error):
        _install(repo.working_tree_dir)

    assert list((tmp_path / "adapters").iterdir()) == []


def _repo_with_requirements(tmp_path):
    repo = adapter_repo(tmp_path / "src", tag=None)
    (tmp_path / "src" / "requirements.txt").write_text("requests\n")
    repo.index.add(["requirements.txt"])
    repo.create_tag("v1.0.0", ref=repo.index.commit("add requirements").hexsha)
    return repo.working_tree_dir


@pytest.mark.usefixtures("test_db")
def test_dependencies_install_into_the_adapter_venv(tmp_path, monkeypatch):
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        if command[1:3] == ["-m", "venv"]:
            Path(command[3]).mkdir(parents=True)
        return subprocess.CompletedProcess(command, 0, "installed", "")

    monkeypatch.setattr(manager.subprocess, "run", run)

    adapter_id, _ = _install(_repo_with_requirements(tmp_path))

    # Built beside the running version, then renamed into place.
    venv = tmp_path / "venvs" / f"{adapter_id}.new"
    assert commands[0][1:] == ["-m", "venv", str(venv)]
    assert commands[1][0] == str(venv / "bin/pip3")
    assert (tmp_path / "venvs" / adapter_id).is_dir()


@pytest.mark.usefixtures("test_db")
def test_a_failed_dependency_install_rolls_back(tmp_path, monkeypatch):
    def fail(command, **kwargs):
        raise subprocess.CalledProcessError(1, command, "", "No matching version")

    monkeypatch.setattr(manager.subprocess, "run", fail)

    with pytest.raises(manager.AdapterError, match="No matching version"):
        _install(_repo_with_requirements(tmp_path))
    assert list((tmp_path / "adapters").iterdir()) == []
    assert _rows() == []


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
def test_moves_credentials_and_state_out_of_the_code(tmp_path):
    add_adapter("gmail", OAUTH2)
    add_adapter("telegram", PNBA)
    (tmp_path / "adapters/gmail-0").mkdir(parents=True)
    (tmp_path / "adapters/gmail-0/credentials.json").write_text("secret")
    (tmp_path / "assets/telegram-1").mkdir(parents=True)
    (tmp_path / "assets/telegram-1/pending.db").write_text("db")

    with db.get_session() as session:
        moved = manager.move_files_out_of_code(session)
        assert [a.name for a in moved] == ["gmail", "telegram"]
        assert manager.move_files_out_of_code(session) == []

    assert (tmp_path / "config/gmail-0/credentials.json").read_text() == "secret"
    assert (tmp_path / "adapters/gmail-0/credentials.json").is_file()
    assert (tmp_path / "state/telegram-1/pending.db").read_text() == "db"
    assert not (tmp_path / "assets/telegram-1").exists()


@pytest.mark.usefixtures("test_db")
def test_keeps_files_already_out_of_the_code(tmp_path):
    add_adapter("gmail", OAUTH2)
    for path, text in (("adapters", "old"), ("config", "new")):
        (tmp_path / path / "gmail-0").mkdir(parents=True)
        (tmp_path / path / "gmail-0/credentials.json").write_text(text)

    with db.get_session() as session:
        assert manager.move_files_out_of_code(session) == []

    assert (tmp_path / "config/gmail-0/credentials.json").read_text() == "new"


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


@pytest.mark.usefixtures("test_db")
def test_an_uncommitted_update_leaves_the_running_version(tmp_path):
    repo = adapter_repo(tmp_path / "src")
    adapter_id, _ = _install(repo.working_tree_dir)
    commit_manifest(repo, "gmail", PNBA, tag="v2.0.0")

    with pytest.raises(RuntimeError), db.get_session() as session:
        adapter = session.get(PlatformAdapter, adapter_id)
        manager.update(session, adapter, log=[])
        raise RuntimeError("commit fails")

    assert _adapter(adapter_id).tag == "v1.0.0"
    manifest = (tmp_path / "adapters" / adapter_id / "manifest.ini").read_text()
    assert "proto_id = 0" in manifest
