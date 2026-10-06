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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from tqdm import tqdm

from publisher.config import PlatformsConfig
from publisher.errors import PublisherError
from publisher.models import audit_event
from publisher.models import platform_adapter as platform_adapters
from publisher.models.audit_event import AuditAction
from publisher.models.credential import Credential
from publisher.models.platform_adapter import PlatformAdapter

logger = logging.getLogger(__name__)

_GITHUB_REPO_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
_REQUIRED_FILES = ("manifest.ini", "main.py", "config.ini")
_REQUIRED_MANIFEST_FIELDS = ("name", "display_name", "cat_id", "proto_id")


class AdapterError(PublisherError):
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


def _install_dependencies(adapter: PlatformAdapter) -> None:
    requirements = Path(adapter.path) / "requirements.txt"
    if not requirements.is_file():
        return
    venv = Path(adapter.venv_path)
    try:
        subprocess.check_call([sys.executable, "-m", "venv", str(venv)])
        subprocess.check_call(
            [str(venv / "bin/pip3"), "install", "-r", str(requirements)]
        )
    except subprocess.SubprocessError as e:
        raise AdapterError(f"Dependency installation failed: {e}") from e


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
    try:
        session.flush()
    except IntegrityError:
        raise AdapterError(
            f"An adapter for {adapter.name!r} with protocol {adapter.proto_id} "
            "is already installed"
        ) from None


def add_from_github(
    session: Session, url: str, actor: Credential | None = None
) -> PlatformAdapter:
    """Clone a repository, install its dependencies and register it."""
    url = url.strip()
    adapter = PlatformAdapter(
        id=str(uuid.uuid5(uuid.NAMESPACE_URL, url.lower())),
        source_url=url,
        created_by=actor.id if actor else None,
        updated_by=actor.id if actor else None,
    )
    path = Path(adapter.path)
    if session.get(PlatformAdapter, adapter.id) or path.exists():
        raise AdapterError(f"Adapter from {url} is already installed")

    path.parent.mkdir(parents=True, exist_ok=True)
    progress = CloneProgress()
    try:
        # A RemoteProgress, not its update method, keeps git's error lines.
        # GitPython accepts one here though its type hint says a callable.
        repo = Repo.clone_from(
            url,
            path,
            progress=progress,  # pyright: ignore[reportArgumentType]
        )
        adapter.commit = repo.head.commit.hexsha
        _apply_manifest(adapter, _read_manifest(path))
        _install_dependencies(adapter)
        session.add(adapter)
        _flush(session, adapter)
    except Exception as e:
        _rmtree(path)
        _rmtree(Path(adapter.venv_path))
        if isinstance(e, GitCommandError):
            reason = " ".join(progress.error_lines) or e.stderr.strip()
            raise AdapterError(f"Cloning {url} failed: {reason}") from e
        raise
    finally:
        progress.close()

    audit_event.record(
        session,
        AuditAction.PLATFORMS_ADD,
        actor=actor,
        target=adapter,
        details={"source_url": adapter.source_url, "commit": adapter.commit},
    )
    return adapter


def update(
    session: Session,
    adapter: PlatformAdapter,
    *,
    install: bool = False,
    actor: Credential | None = None,
) -> None:
    """Pull an adapter's latest commit and refresh its manifest."""
    from_commit = adapter.commit
    repo = Repo(adapter.path)
    try:
        repo.git.pull()
    except GitCommandError as e:
        raise AdapterError(
            f"Pulling {adapter.name!r} failed: {e.stderr.strip()}"
        ) from e
    _apply_manifest(adapter, _read_manifest(Path(adapter.path)))
    adapter.commit = repo.head.commit.hexsha
    adapter.updated_by = actor.id if actor else None
    _flush(session, adapter)
    if install:
        _install_dependencies(adapter)

    audit_event.record(
        session,
        AuditAction.PLATFORMS_UPDATE,
        actor=actor,
        target=adapter,
        details={"from_commit": from_commit, "to_commit": adapter.commit},
    )


def remove(
    session: Session, adapter: PlatformAdapter, actor: Credential | None = None
) -> None:
    """Unregister an adapter and delete its files."""
    # The id names its directories; reject one that could point elsewhere.
    if adapter.id in ("", ".", "..") or "/" in adapter.id:
        raise AdapterError(f"Unsafe adapter id {adapter.id!r}")
    audit_event.record(
        session,
        AuditAction.PLATFORMS_REMOVE,
        actor=actor,
        target=adapter,
        details={"source_url": adapter.source_url, "commit": adapter.commit},
    )
    session.delete(adapter)
    session.flush()
    _rmtree(Path(adapter.path))
    _rmtree(Path(adapter.venv_path))


def import_from_disk(session: Session) -> list[PlatformAdapter]:
    """Register adapter directories with no row, e.g. from the old JSON registry."""
    adapters_dir = PlatformsConfig.get().adapters_dir
    if not adapters_dir.is_dir():
        return []

    # Checked up front: one clash at flush would fail the whole import.
    taken = {(a.name, a.proto_id) for a in platform_adapters.find(session)}
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
