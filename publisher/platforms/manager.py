# SPDX-License-Identifier: GPL-3.0-only

import configparser
import logging
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import override
from urllib.parse import urlsplit

from git import GitCommandError, RemoteProgress, Repo
from git.cmd import Git
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError
from tqdm import tqdm

from publisher.config import PlatformsConfig
from publisher.errors import PublisherError
from publisher.models import audit_event
from publisher.models import platform_adapter as platform_adapters
from publisher.models import token as tokens
from publisher.models.audit_event import AuditAction
from publisher.models.credential import Credential
from publisher.models.platform_adapter import PlatformAdapter

logger = logging.getLogger(__name__)

_GITHUB_REPO_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
_VERSION_TAG = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_REQUIRED_FILES = ("manifest.ini", "main.py", "config.ini")
_REQUIRED_MANIFEST_FIELDS = ("name", "display_name", "cat_id", "proto_id")


class AdapterError(PublisherError):
    pass


def _git_error(e: GitCommandError) -> str:
    # GitPython wraps git's message as "stderr: '<message>'".
    return str(e.stderr).strip().removeprefix("stderr: ").strip("'")


class AdapterConflictError(AdapterError):
    pass


class AdapterInUseError(AdapterError):
    pass


def is_allowed_github_url(url: str) -> bool:
    """Whether url is a GitHub repo of an org in PLATFORMS_GITHUB_ORGS."""
    parts = urlsplit(url.strip())
    if parts.scheme != "https" or parts.netloc.lower() != "github.com":
        return False
    if parts.query or parts.fragment:
        return False
    segments = parts.path.strip("/").split("/")
    if len(segments) != 2:
        return False
    org, repo = segments
    return (
        org.lower() in PlatformsConfig.get().github_orgs
        and repo not in (".", "..")
        and _GITHUB_REPO_PATTERN.match(repo) is not None
    )


class CloneProgress(RemoteProgress):
    """Shows a progress bar while cloning."""

    def __init__(self):
        super().__init__()
        self.pbar = None

    @override
    def update(self, op_code, cur_count, max_count=None, message=""):
        if max_count and not self.pbar:
            self.pbar = tqdm(
                total=float(max_count),
                unit="objects",
                desc="Cloning repository",
                leave=False,
            )
        if self.pbar:
            self.pbar.n = cur_count
            self.pbar.refresh()

    def close(self):
        if self.pbar:
            self.pbar.close()
            self.pbar = None


def _rmtree(path: Path) -> None:
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.error("Failed to delete %s: %s", path, e)


def _install_dependencies(path: Path, venv: Path, log: list[str]) -> None:
    requirements = path / "requirements.txt"
    if not requirements.is_file():
        return
    for command in (
        [sys.executable, "-m", "venv", str(venv)],
        [str(venv / "bin/pip3"), "install", "-r", str(requirements)],
    ):
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as e:
            log.extend([e.stdout, e.stderr])
            raise AdapterError(f"Dependency installation failed: {e.stderr}") from e
        log.append(result.stdout)


def _read_manifest(path: Path) -> dict:
    missing = [name for name in _REQUIRED_FILES if not (path / name).is_file()]
    if missing:
        raise AdapterError(f"{path} is missing {', '.join(missing)}")
    ini = configparser.ConfigParser()
    try:
        ini.read(path / "manifest.ini")
        manifest = dict(ini["platform"])
    except (configparser.Error, KeyError) as e:
        raise AdapterError(f"Invalid manifest.ini in {path}: {e}") from e
    if not all(manifest.get(field) for field in _REQUIRED_MANIFEST_FIELDS):
        raise AdapterError(
            f"manifest.ini in {path} needs {', '.join(_REQUIRED_MANIFEST_FIELDS)}"
        )
    return manifest


def _apply_manifest(adapter: PlatformAdapter, manifest: dict) -> None:
    try:
        adapter.name = manifest["name"].strip().lower()
        adapter.display_name = manifest["display_name"]
        adapter.cat_id = int(manifest["cat_id"])
        adapter.proto_id = int(manifest["proto_id"])
    except ValueError as e:
        raise AdapterError(f"Invalid manifest value: {e}") from e
    adapter.auth_provider = manifest.get("auth_provider") or None
    adapter.supports_offline_first = (
        manifest.get("supports_offline_first", "").strip().lower() == "true"
    )
    adapter.icon_svg = manifest.get("icon_svg") or None
    adapter.icon_png = manifest.get("icon_png") or None


def _flush(session: Session, adapter: PlatformAdapter) -> None:
    # Read before flushing: a failed flush expires the adapter's attributes.
    name, proto_id = adapter.name, adapter.proto_id
    try:
        session.flush()
    except IntegrityError:
        raise AdapterError(
            f"An adapter for {name!r} with protocol {proto_id} is already installed"
        ) from None
    except StaleDataError:
        raise AdapterConflictError(
            f"Adapter {name!r} was changed concurrently; retry"
        ) from None


def adapter_id(url: str) -> str:
    """Stable per URL, so a reinstall finds the same directories."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, url.strip().lower()))


def latest_tag(url: str) -> str:
    """The newest version tag (v1.2.3 or 1.2.3) of the repository at url."""
    try:
        refs = str(Git().ls_remote("--tags", "--refs", url))
    except GitCommandError as e:
        raise AdapterError(f"Listing the tags of {url} failed: {_git_error(e)}") from e
    versions = {}
    for line in refs.splitlines():
        tag = line.rpartition("refs/tags/")[2]
        if match := _VERSION_TAG.match(tag):
            versions[tuple(int(n) for n in match.groups())] = tag
    if not versions:
        raise AdapterError(f"{url} has no version tags such as v1.0.0")
    return versions[max(versions)]


def _beside(path: str | Path, suffix: str) -> Path:
    return Path(f"{path}.{suffix}")


def _discard_build(adapter: PlatformAdapter) -> None:
    _rmtree(_beside(adapter.path, "new"))
    _rmtree(_beside(adapter.venv_path, "new"))


def _build(
    adapter: PlatformAdapter, tag: str | None, log: list[str]
) -> tuple[str, dict]:
    """Clone tag, or the default branch, and its venv next to the running version.

    Returns the commit and the manifest.
    """
    path, venv = _beside(adapter.path, "new"), _beside(adapter.venv_path, "new")
    _discard_build(adapter)
    path.parent.mkdir(parents=True, exist_ok=True)
    progress = CloneProgress()
    try:
        # A RemoteProgress, not its update method, keeps git's error lines.
        # GitPython accepts one here though its type hint says a callable.
        repo = Repo.clone_from(
            adapter.source_url,
            path,
            progress=progress,  # pyright: ignore[reportArgumentType]
            branch=tag,
            depth=1,
        )
        manifest = _read_manifest(path)
        _install_dependencies(path, venv, log)
    except Exception as e:
        _discard_build(adapter)
        if isinstance(e, GitCommandError):
            reason = " ".join(progress.error_lines) or _git_error(e)
            raise AdapterError(f"Cloning {adapter.source_url} failed: {reason}") from e
        raise
    finally:
        progress.close()
    return repo.head.commit.hexsha, manifest


def _register(session: Session, adapter: PlatformAdapter, manifest: dict) -> None:
    try:
        _apply_manifest(adapter, manifest)
        session.add(adapter)
        _flush(session, adapter)
    except AdapterError:
        _discard_build(adapter)
        raise


def _resolve_tag(url: str, tag: str | None, branch: bool) -> str | None:
    return None if branch else tag or latest_tag(url)


def activate(adapter: PlatformAdapter) -> None:
    """Move a built version into place. Call it after the install or update commits.

    Run before the commit, a failed commit would leave the new files with the old row.
    """
    # Renames are atomic, so an adapter call sees the old version or the new.
    for current in (Path(adapter.path), Path(adapter.venv_path)):
        new, old = _beside(current, "new"), _beside(current, "old")
        if not new.exists():
            continue
        if current.exists():
            current.rename(old)
        new.rename(current)
        _rmtree(old)


def delete_files(adapter: PlatformAdapter) -> None:
    """Delete a removed adapter's files. Call it after the removal commits."""
    _rmtree(Path(adapter.path))
    _rmtree(Path(adapter.venv_path))


def install(
    session: Session,
    url: str,
    tag: str | None = None,
    *,
    branch: bool = False,
    actor: Credential | None = None,
    log: list[str],
) -> PlatformAdapter:
    """Build and register url at tag, its newest tag, or its default branch."""
    url = url.strip()
    adapter = PlatformAdapter(
        id=adapter_id(url),
        source_url=url,
        tag=_resolve_tag(url, tag, branch),
        created_by=actor.id if actor else None,
        updated_by=actor.id if actor else None,
    )
    if session.get(PlatformAdapter, adapter.id) or Path(adapter.path).exists():
        raise AdapterError(f"Adapter from {url} is already installed")
    adapter.commit, manifest = _build(adapter, adapter.tag, log)
    _register(session, adapter, manifest)

    audit_event.record(
        session,
        AuditAction.PLATFORMS_ADD,
        actor=actor,
        target=adapter,
        details={
            "source_url": adapter.source_url,
            "tag": adapter.tag,
            "commit": adapter.commit,
        },
    )
    return adapter


def update(
    session: Session,
    adapter: PlatformAdapter,
    tag: str | None = None,
    *,
    branch: bool = False,
    actor: Credential | None = None,
    log: list[str],
) -> None:
    """Register tag, the newest version tag, or the default branch for an adapter."""
    tag = _resolve_tag(adapter.source_url, tag, branch)
    commit, manifest = _build(adapter, tag, log)
    # A tag that now names other code was moved, which a release shouldn't do.
    if tag and tag == adapter.tag and commit != adapter.commit:
        _discard_build(adapter)
        raise AdapterError(
            f"Tag {tag} of {adapter.name!r} now points to {commit[:12]}, "
            f"not the installed {adapter.commit[:12]}"
        )
    details = {"from_tag": adapter.tag, "from_commit": adapter.commit}
    adapter.tag, adapter.commit = tag, commit
    adapter.updated_by = actor.id if actor else None
    _register(session, adapter, manifest)

    audit_event.record(
        session,
        AuditAction.PLATFORMS_UPDATE,
        actor=actor,
        target=adapter,
        details={**details, "to_tag": tag, "to_commit": commit},
    )


def set_enabled(
    session: Session,
    adapter: PlatformAdapter,
    enabled: bool,
    actor: Credential | None = None,
) -> None:
    if adapter.is_enabled == enabled:
        return
    adapter.is_enabled = enabled
    adapter.updated_by = actor.id if actor else None
    _flush(session, adapter)
    action = AuditAction.PLATFORMS_ENABLE if enabled else AuditAction.PLATFORMS_DISABLE
    audit_event.record(session, action, actor=actor, target=adapter)


def remove(
    session: Session,
    adapter: PlatformAdapter,
    actor: Credential | None = None,
    *,
    force: bool = False,
) -> None:
    """Unregister an adapter; call delete_files after the commit.

    Raises:
        AdapterInUseError: When accounts are linked through it and force is off.
    """
    # The id names its directories; reject one that could point elsewhere.
    if adapter.id in ("", ".", "..") or "/" in adapter.id:
        raise AdapterError(f"Unsafe adapter id {adapter.id!r}")
    linked = tokens.count_for_platform(session, adapter.name, adapter.proto_id)
    # Their tokens can only be revoked upstream through the adapter.
    if linked and not force:
        raise AdapterInUseError(
            f"{linked} linked account(s) use {adapter.name!r}. Disable it instead, "
            "or remove it with the CLI's --force."
        )
    audit_event.record(
        session,
        AuditAction.PLATFORMS_REMOVE,
        actor=actor,
        target=adapter,
        details={
            "source_url": adapter.source_url,
            "commit": adapter.commit,
            "linked_accounts": linked,
        },
    )
    session.delete(adapter)
    _flush(session, adapter)


def import_from_disk(session: Session) -> list[PlatformAdapter]:
    """Register adapter directories with no row, e.g. from the old JSON registry."""
    adapters_dir = PlatformsConfig.get().adapters_dir
    if not adapters_dir.is_dir():
        return []

    # Checked up front: one clash at flush would fail the whole import.
    taken = {
        (a.name, a.proto_id)
        for a in platform_adapters.find(session, include_disabled=True)
    }
    imported = []
    for path in sorted(adapters_dir.iterdir()):
        if not path.is_dir() or session.get(PlatformAdapter, path.name):
            continue
        try:
            manifest = _read_manifest(path)
            repo = Repo(path)
            adapter = PlatformAdapter(
                id=path.name,
                source_url=repo.remotes.origin.url,
                commit=repo.head.commit.hexsha,
            )
            _apply_manifest(adapter, manifest)
        except Exception as e:
            logger.warning("Skipping adapter directory %s: %s", path, e)
            continue
        if (adapter.name, adapter.proto_id) in taken:
            logger.warning("Skipping %s: %r is already installed", path, adapter.name)
            continue
        taken.add((adapter.name, adapter.proto_id))
        session.add(adapter)
        imported.append(adapter)
    session.flush()
    return imported


def move_files_out_of_code(session: Session) -> list[PlatformAdapter]:
    """Copy credentials.json to config dirs and move assets dirs to state dirs.

    Leaves an adapter alone where its new location already exists.
    """
    legacy_state_dir = PlatformsConfig.get().adapters_state_dir.parent / "assets"
    changed = []
    for adapter in platform_adapters.find(session, include_disabled=True):
        credentials = Path(adapter.path) / "credentials.json"
        config = Path(adapter.config_path) / "credentials.json"
        legacy_state = legacy_state_dir / adapter.id
        state = Path(adapter.state_path)
        moved = False
        if credentials.is_file() and not config.exists():
            config.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(credentials, config)
            moved = True
        if legacy_state.is_dir() and not state.exists():
            state.parent.mkdir(parents=True, exist_ok=True)
            legacy_state.rename(state)
            moved = True
        if moved:
            changed.append(adapter)
    return changed
