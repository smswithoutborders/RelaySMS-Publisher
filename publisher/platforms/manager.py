# SPDX-License-Identifier: GPL-3.0-only

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
from publisher.models import token as tokens
from publisher.models.audit_event import AuditAction
from publisher.models.credential import Credential
from publisher.models.platform_adapter import PROTOCOL_NAMES, PlatformAdapter
from relaysms_adapter_sdk.manifest import Category, Manifest, ManifestError, Protocol
from relaysms_adapter_sdk.manifest import load as load_manifest

logger = logging.getLogger(__name__)

_GITHUB_REPO_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
_VERSION_TAG = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_PROTOCOL_IDS = {Protocol(name): proto_id for proto_id, name in PROTOCOL_NAMES.items()}
_CATEGORY_IDS = {
    Category.EMAIL: 0,
    Category.MESSAGE: 1,
    Category.TEXT: 2,
    Category.BRIDGE: 3,
}


class AdapterError(PublisherError):
    pass


def _git_error(e: GitCommandError) -> str:
    # GitPython wraps git's message as "stderr: '<message>'".
    return str(e.stderr).strip().removeprefix("stderr: ").strip("'")


class AdapterConflictError(AdapterError):
    pass


class InvalidConfigError(AdapterError):
    """Settings or setup inputs the caller gave don't fit the adapter."""


class AdapterFaultError(AdapterError):
    """The adapter or its files on this server are broken, not the caller's input."""


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
    """Install the adapter and its dependencies, including the SDK, into venv."""
    for command in (
        [sys.executable, "-m", "venv", str(venv)],
        [str(venv / "bin/pip"), "install", "--disable-pip-version-check", str(path)],
    ):
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as e:
            log.extend([e.stdout, e.stderr])
            raise AdapterError(f"Dependency installation failed: {e.stderr}") from e
        log.append(result.stdout)


def _read_manifest(path: Path) -> Manifest:
    if not (path / "pyproject.toml").is_file():
        raise AdapterError(f"{path} has no pyproject.toml")
    try:
        return load_manifest(path)
    except ManifestError as e:
        raise AdapterError(str(e)) from e


def _apply_manifest(adapter: PlatformAdapter, manifest: Manifest) -> None:
    adapter.name = manifest.name
    adapter.display_name = manifest.display_name
    adapter.proto_id = _PROTOCOL_IDS[manifest.protocol]
    adapter.cat_id = _CATEGORY_IDS[manifest.category]
    adapter.auth_provider = manifest.auth_provider
    adapter.supports_offline_first = manifest.offline_first
    adapter.icon_svg = manifest.icon_svg
    adapter.icon_png = manifest.icon_png


def flush(session: Session, adapter: PlatformAdapter) -> None:
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
            f"Adapter {name!r} was changed concurrently. Retry."
        ) from None


def adapter_id(url: str) -> str:
    """The adapter's id: a UUID derived from its source URL."""
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


def _build(adapter: PlatformAdapter, tag: str, log: list[str]) -> tuple[str, Manifest]:
    """Clone tag and build its venv next to the running version.

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


def _register(session: Session, adapter: PlatformAdapter, manifest: Manifest) -> None:
    try:
        _apply_manifest(adapter, manifest)
        session.add(adapter)
        flush(session, adapter)
    except AdapterError:
        _discard_build(adapter)
        raise


def activate(adapter: PlatformAdapter) -> None:
    """Move a built version into place. Call it after the install or update commits."""
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
    actor: Credential | None = None,
    log: list[str],
) -> PlatformAdapter:
    """Build and register url at tag, or its newest version tag."""
    url = url.strip()
    tag = tag or latest_tag(url)
    adapter = PlatformAdapter(
        id=adapter_id(url),
        source_url=url,
        tag=tag,
        created_by=actor.id if actor else None,
        updated_by=actor.id if actor else None,
    )
    if session.get(PlatformAdapter, adapter.id) or Path(adapter.path).exists():
        raise AdapterError(f"Adapter from {url} is already installed")
    adapter.commit, manifest = _build(adapter, tag, log)
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
    actor: Credential | None = None,
    log: list[str],
) -> None:
    """Register tag, or the newest version tag, for an adapter."""
    tag = tag or latest_tag(adapter.source_url)
    commit, manifest = _build(adapter, tag, log)
    # Refuse the installed tag when it now points to a different commit.
    if tag == adapter.tag and commit != adapter.commit:
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
    flush(session, adapter)
    action = AuditAction.PLATFORMS_ENABLE if enabled else AuditAction.PLATFORMS_DISABLE
    audit_event.record(session, action, actor=actor, target=adapter)


def remove(
    session: Session,
    adapter: PlatformAdapter,
    actor: Credential | None = None,
    *,
    force: bool = False,
) -> None:
    """Unregister an adapter. Call delete_files after the commit.

    Raises:
        AdapterInUseError: When accounts are linked through it and force is off.
    """
    # Reject an id that could make its directory paths point elsewhere.
    if adapter.id in ("", ".", "..") or "/" in adapter.id:
        raise AdapterError(f"Unsafe adapter id {adapter.id!r}")
    linked = tokens.count_for_platform(session, adapter.name, adapter.proto_id)
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
    flush(session, adapter)
