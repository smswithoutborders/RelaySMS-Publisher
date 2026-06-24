# SPDX-License-Identifier: GPL-3.0-only

import configparser
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import msgspec
from git import RemoteProgress, Repo
from tqdm import tqdm

from logutils import get_logger
from utils import get_configs

BASE_DIR = Path(__file__).resolve().parent
adapters_dir = Path(
    get_configs("PLATFORMS_ADAPTERS_DIR", default_value=str(BASE_DIR / "adapters"))
)
adapters_venv_dir = Path(
    get_configs(
        "PLATFORMS_ADAPTERS_VENV_DIR", default_value=str(BASE_DIR / "adapters_venv")
    )
)
adapters_assets_dir = Path(
    get_configs(
        "PLATFORMS_ADAPTERS_ASSETS_DIR", default_value=str(BASE_DIR / "adapters_assets")
    )
)

REGISTRY_FILE = BASE_DIR / "registry.json"
logger = get_logger(__name__)


class PlatformManifest(msgspec.Struct):
    id: str
    name: str
    path: str
    venv_path: str
    assets_path: str
    cat_id: int
    proto_id: int
    shortcode: Optional[str] = None
    icon_svg: Optional[str] = None
    icon_png: Optional[str] = None
    support_url_scheme: Optional[str] = None


class CloneProgress(RemoteProgress):
    """Displays progress bar for git clone tasks."""

    def __init__(self):
        super().__init__()
        self.pbar = None

    def update(self, op_code, cur_count, max_count=None, message=""):
        if max_count and not self.pbar:
            self.pbar = tqdm(
                total=max_count, unit="objects", desc="Cloning repository", leave=False
            )
        if self.pbar:
            self.pbar.n = cur_count
            self.pbar.refresh()

    def close(self):
        if self.pbar:
            self.pbar.close()
            self.pbar = None


class AdapterManager:
    """Manages adapter lifecycle operations using a JSON registry."""

    _adapters_dir: Path = adapters_dir
    _adapters_venv_dir: Path = adapters_venv_dir
    _adapters_assets_dir: Path = adapters_assets_dir

    def __init__(self, registry_file: Path = REGISTRY_FILE):
        self.registry_file = registry_file
        self._app_registry: Dict[str, PlatformManifest] = {}
        self._last_modified: float = 0.0

    def _load_registry(self) -> Dict[str, PlatformManifest]:
        """Loads registry from JSON file."""
        try:
            current_mtime = os.stat(self.registry_file).st_mtime
        except FileNotFoundError:
            return {}

        if current_mtime == self._last_modified:
            return self._app_registry

        try:
            with open(self.registry_file, "rb") as f:
                self._app_registry = msgspec.json.decode(
                    f.read(), type=Dict[str, PlatformManifest]
                )
            self._last_modified = current_mtime
            return self._app_registry
        except Exception as e:
            logger.error("[!] Registry read failed: %s", e)
            return {}

    def _save_registry(self, data: Dict[str, PlatformManifest]):
        """Saves registry data to JSON file."""
        try:
            encoded_bytes = msgspec.json.encode(data)
            self.registry_file.write_bytes(encoded_bytes)

            self._last_modified = os.stat(self.registry_file).st_mtime
            self._app_registry = data
        except (OSError, msgspec.ValidationError) as e:
            logger.error("[!] Registry write failed: %s", e)

    @classmethod
    def _generate_id(cls, url: str) -> str:
        """Generates deterministic ID from a URL string."""
        return str(uuid.uuid5(uuid.NAMESPACE_URL, url.strip().lower()))

    @classmethod
    def _is_safe_path(cls, base_folder: Path, target_path: Path) -> bool:
        """Checks if a path sits safely within its intended base folder boundaries."""
        try:
            return (
                base_folder.resolve() in target_path.resolve().parents
                or base_folder.resolve() == target_path.resolve()
            )
        except (OSError, ValueError):
            return False

    @classmethod
    def _load_ini_file(cls, path: Path, section: str) -> Optional[dict]:
        """Reads a section from an INI file as raw string values."""
        if not path.is_file():
            logger.error("[!] Missing file: %s", path)
            return None

        config = configparser.ConfigParser()
        try:
            config.read(path)
            if section not in config:
                logger.error("[!] Section '%s' missing in: %s", section, path)
                return None
            return dict(config[section])
        except Exception as e:
            logger.error("[!] INI parse failed %s: %s", path, e)
            return None

    @staticmethod
    def _rollback_directory(path: Path):
        """Deletes a directory if a task fails."""
        try:
            if path.is_dir():
                shutil.rmtree(path)
                logger.info("[-] Rolled back directory: %s", path)
        except OSError as e:
            logger.error("[!] Rollback failed for %s: %s", path, e)

    @staticmethod
    def _validate_adapter_files(path: Path) -> bool:
        """Checks if required core files exist."""
        required = ["manifest.ini", "main.py", "config.ini"]
        missing = [f for f in required if not (path / f).is_file()]
        if missing:
            logger.warning(
                "[!] Missing adapter files in %s: %s", path, ", ".join(missing)
            )
            return False
        return True

    @classmethod
    def _install_dependencies(cls, requirements_path: Path, venv_path: Path):
        """Creates venv and runs pip install."""
        if not cls._is_safe_path(cls._adapters_venv_dir, venv_path):
            raise ValueError("Invalid virtual environment path localization.")

        try:
            subprocess.check_call([sys.executable, "-m", "venv", str(venv_path)])
            pip_name = "bin/pip3"
            pip_executable = venv_path / pip_name
            subprocess.check_call(
                [str(pip_executable), "install", "-r", str(requirements_path)]
            )
            logger.info("[+] Dependencies installed: %s", venv_path)
        except subprocess.SubprocessError as e:
            logger.error("[!] Pip install failed: %s", e)
            raise ValueError("Dependency installation failed.") from e

    def find_adapter_ids(
        self,
        name: Optional[str] = None,
        proto_id: Optional[Any] = None,
        cat_id: Optional[Any] = None,
    ) -> List[str]:
        """Finds matching registry item keys using string metadata inputs."""
        registry = self._load_registry()
        if not registry:
            return []

        n_term = name.strip().lower() if name else None
        p_term = str(proto_id).strip().lower() if proto_id is not None else None
        c_term = str(cat_id).strip().lower() if cat_id is not None else None

        matches = []
        for adapter_id, manifest in registry.items():
            if n_term and str(manifest.name).strip().lower() != n_term:
                continue
            if p_term and str(manifest.proto_id).strip().lower() != p_term:
                continue
            if c_term and str(manifest.cat_id).strip().lower() != c_term:
                continue
            matches.append(adapter_id)

        return matches

    def list_adapters(
        self,
        name: Optional[str] = None,
        proto_id: Optional[Any] = None,
        cat_id: Optional[Any] = None,
    ) -> List[PlatformManifest]:
        """Returns a list of adapter records matching any combination of optional filters."""
        registry = self._load_registry()
        if not registry:
            return []

        n_term = name.strip().lower() if name else None
        p_term = str(proto_id).strip().lower() if proto_id is not None else None
        c_term = str(cat_id).strip().lower() if cat_id is not None else None

        results = []
        for manifest in registry.values():
            if n_term and str(manifest.name).strip().lower() != n_term:
                continue
            if p_term and str(manifest.proto_id).strip().lower() != p_term:
                continue
            if c_term and str(manifest.cat_id).strip().lower() != c_term:
                continue
            results.append(manifest)

        return results

    def add_adapter_from_github(self, url: str):
        """Clones a repository and registers its metadata."""
        self._adapters_dir.mkdir(parents=True, exist_ok=True)
        adapter_id = self._generate_id(url)
        dest_path = self._adapters_dir / adapter_id

        if not self._is_safe_path(self._adapters_dir, dest_path):
            raise ValueError("Invalid target folder destination.")

        registry = self._load_registry()
        if adapter_id in registry or dest_path.exists():
            logger.info("[-] Adapter already registered at %s, skipping.", dest_path)
            return

        progress = CloneProgress()
        try:
            Repo.clone_from(url, dest_path, progress=progress)
            logger.info("[+] Repository cloned: %s", dest_path)
        except Exception as e:
            logger.error("[!] Git clone failed for %s: %s", url, e)
            self._rollback_directory(dest_path)
            raise
        finally:
            progress.close()

        if not self._validate_adapter_files(dest_path):
            self._rollback_directory(dest_path)
            raise ValueError(f"Validation failed for files at: {dest_path}")

        manifest_data = self._load_ini_file(dest_path / "manifest.ini", "platform")
        if (
            not manifest_data
            or not manifest_data.get("name")
            or not manifest_data.get("cat_id")
            or not manifest_data.get("proto_id")
        ):
            self._rollback_directory(dest_path)
            raise ValueError(
                "Manifest content incomplete (missing name, cat_id, or proto_id)."
            )

        venv_path = self._adapters_venv_dir / adapter_id
        requirements_path = dest_path / "requirements.txt"

        if requirements_path.is_file():
            venv_path.mkdir(parents=True, exist_ok=True)
            try:
                self._install_dependencies(requirements_path, venv_path)
            except ValueError:
                self._rollback_directory(dest_path)
                self._rollback_directory(venv_path)
                raise

        manifest_record = PlatformManifest(
            id=adapter_id,
            name=manifest_data["name"],
            path=str(dest_path),
            venv_path=str(venv_path),
            assets_path=str(self._adapters_assets_dir / adapter_id),
            cat_id=int(manifest_data["cat_id"]),
            proto_id=int(manifest_data["proto_id"]),
            shortcode=manifest_data.get("shortcode"),
            icon_svg=manifest_data.get("icon_svg"),
            icon_png=manifest_data.get("icon_png"),
            support_url_scheme=manifest_data.get("support_url_scheme"),
        )

        registry[adapter_id] = manifest_record
        self._save_registry(registry)
        logger.info("[+] Registered adapter: '%s'", manifest_data["name"])

    def remove_adapter(self, adapter_id: str):
        """Removes adapter workspace folders and keys from registry."""
        registry = self._load_registry()
        if adapter_id not in registry:
            raise ValueError(f"Adapter ID '{adapter_id}' missing from registry.")

        manifest = registry[adapter_id]
        p_target = Path(manifest.path)
        v_target = Path(manifest.venv_path)

        if not self._is_safe_path(
            self._adapters_dir, p_target
        ) or not self._is_safe_path(self._adapters_venv_dir, v_target):
            raise ValueError("Deletion paths run outside system target roots.")

        self._rollback_directory(p_target)
        self._rollback_directory(v_target)

        del registry[adapter_id]
        self._save_registry(registry)
        logger.info("[-] Removed adapter entry: %s", adapter_id)

    def update_adapter(self, adapter_id: Optional[str] = None, install: bool = False):
        """Pulls updates from remote source targets for targeted items."""
        registry = self._load_registry()
        targets = [adapter_id] if adapter_id else list(registry.keys())

        for target_id in targets:
            manifest = registry.get(target_id)
            if not manifest:
                continue

            adapter_path = Path(manifest.path)
            if not self._is_safe_path(self._adapters_dir, adapter_path):
                logger.error(
                    "[!] Update skipped: Invalid file folder track path on %s",
                    target_id,
                )
                continue

            try:
                repo = Repo(manifest.path)
                repo.git.pull()
                logger.info("[+] Pulled source updates for: %s", target_id)
            except Exception as e:
                logger.error("[!] Git pull failed for %s: %s", target_id, e)
                continue

            updated_manifest = self._load_ini_file(
                adapter_path / "manifest.ini", "platform"
            )

            if updated_manifest:
                try:
                    registry[target_id] = PlatformManifest(
                        id=target_id,
                        name=updated_manifest["name"],
                        path=manifest.path,
                        venv_path=manifest.venv_path,
                        assets_path=manifest.assets_path,
                        cat_id=int(updated_manifest["cat_id"]),
                        proto_id=int(updated_manifest["proto_id"]),
                        shortcode=updated_manifest.get("shortcode"),
                        icon_svg=updated_manifest.get("icon_svg"),
                        icon_png=updated_manifest.get("icon_png"),
                        support_url_scheme=updated_manifest.get("support_url_scheme"),
                    )
                    logger.info("[+] Manifest cleanly overwritten for: %s", target_id)
                except KeyError as ke:
                    logger.error(
                        "[!] Missing required manifest field for %s: %s", target_id, ke
                    )
                    continue
                except Exception as e:
                    logger.error(
                        "[!] Failed to instantiate manifest for %s: %s", target_id, e
                    )
                    continue

            if install:
                requirements_path = adapter_path / "requirements.txt"
                if requirements_path.is_file():
                    try:
                        self._install_dependencies(
                            requirements_path, Path(manifest.venv_path)
                        )
                    except ValueError:
                        logger.error(
                            "[!] Dependency reinstall failed for: %s", target_id
                        )

        self._save_registry(registry)
        logger.info("[+] Update process completed.")
