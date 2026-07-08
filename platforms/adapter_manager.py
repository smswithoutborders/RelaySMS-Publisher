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

REGISTRY_FILE = Path(
    get_configs(
        "PLATFORMS_REGISTRY_FILE", default_value=str(BASE_DIR / "registry.json")
    )
)
logger = get_logger(__name__)


class PlatformManifest(msgspec.Struct, forbid_unknown_fields=False):
    id: str
    display_name: str
    name: str
    path: str
    venv_path: str
    assets_path: str
    cat_id: int
    proto_id: int
    auth_provider: Optional[str] = None
    icon_svg: Optional[str] = None
    icon_png: Optional[str] = None


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
        try:
            current_mtime = os.stat(self.registry_file).st_mtime
        except FileNotFoundError:
            return {}

        if current_mtime == self._last_modified:
            return self._app_registry

        try:
            with open(self.registry_file, "rb") as f:
                registry = msgspec.json.decode(
                    f.read(), type=Dict[str, PlatformManifest]
                )
            self._app_registry = registry
            self._last_modified = current_mtime
            return self._app_registry
        except Exception as e:
            logger.error("[!] Registry read failed: %s", e)
            return self._app_registry

    def _save_registry(self, data: Dict[str, PlatformManifest]):
        try:
            self.registry_file.parent.mkdir(parents=True, exist_ok=True)
            self.registry_file.write_bytes(msgspec.json.encode(data))
            self._last_modified = os.stat(self.registry_file).st_mtime
            self._app_registry = data
        except (OSError, msgspec.ValidationError) as e:
            logger.error("[!] Registry write failed: %s", e)

    @classmethod
    def _generate_id(cls, url: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, url.strip().lower()))

    @classmethod
    def _is_safe_path(cls, base_folder: Path, target_path: Path) -> bool:
        try:
            return (
                base_folder.resolve() in target_path.resolve().parents
                or base_folder.resolve() == target_path.resolve()
            )
        except (OSError, ValueError):
            return False

    @classmethod
    def _load_ini_file(cls, path: Path, *sections: str) -> Optional[dict]:
        """Reads and merges specified INI sections into a flat dict."""
        if not path.is_file():
            logger.error("[!] Missing file: %s", path)
            return None

        config = configparser.ConfigParser()
        try:
            config.read(path)
        except Exception as e:
            logger.error("[!] INI parse failed %s: %s", path, e)
            return None

        merged = {}
        for section in sections:
            if section not in config:
                logger.error("[!] Section '%s' missing in: %s", section, path)
                return None
            merged.update(dict(config[section]))

        return merged

    @staticmethod
    def _rollback_directory(path: Path):
        try:
            if path.is_dir():
                shutil.rmtree(path)
                logger.info("[-] Rolled back directory: %s", path)
        except OSError as e:
            logger.error("[!] Rollback failed for %s: %s", path, e)

    @staticmethod
    def _validate_adapter_files(path: Path) -> bool:
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
        if not cls._is_safe_path(cls._adapters_venv_dir, venv_path):
            raise ValueError("Invalid virtual environment path localization.")

        try:
            subprocess.check_call([sys.executable, "-m", "venv", str(venv_path)])
            subprocess.check_call(
                [str(venv_path / "bin/pip3"), "install", "-r", str(requirements_path)]
            )
            logger.info("[+] Dependencies installed: %s", venv_path)
        except subprocess.SubprocessError as e:
            logger.error("[!] Pip install failed: %s", e)
            raise ValueError("Dependency installation failed.") from e

    def _build_manifest_from_ini(
        self, adapter_id: str, ini_data: dict, existing: PlatformManifest
    ) -> PlatformManifest:
        try:
            return PlatformManifest(
                id=adapter_id,
                display_name=ini_data["display_name"],
                name=ini_data["name"],
                path=existing.path,
                venv_path=existing.venv_path,
                assets_path=existing.assets_path,
                cat_id=int(ini_data["cat_id"]),
                proto_id=int(ini_data["proto_id"]),
                auth_provider=ini_data.get("auth_provider"),
                icon_svg=ini_data.get("icon_svg"),
                icon_png=ini_data.get("icon_png"),
            )
        except KeyError as e:
            raise ValueError(f"Missing required manifest field: {e}") from e

    def find_adapter_ids(
        self,
        name: Optional[str] = None,
        proto_id: Optional[Any] = None,
        cat_id: Optional[Any] = None,
    ) -> List[str]:
        """Return registry keys matching any combination of optional filters."""
        registry = self._load_registry()
        if not registry:
            return []

        n_term = name.strip().lower() if name else None
        p_term = str(proto_id).strip().lower() if proto_id is not None else None
        c_term = str(cat_id).strip().lower() if cat_id is not None else None

        return [
            adapter_id
            for adapter_id, manifest in registry.items()
            if not (n_term and str(manifest.name).strip().lower() != n_term)
            and not (p_term and str(manifest.proto_id).strip().lower() != p_term)
            and not (c_term and str(manifest.cat_id).strip().lower() != c_term)
        ]

    def list_adapters(
        self,
        name: Optional[str] = None,
        proto_id: Optional[Any] = None,
        cat_id: Optional[Any] = None,
    ) -> List[PlatformManifest]:
        """Return manifests matching any combination of optional filters."""
        registry = self._load_registry()
        if not registry:
            return []

        n_term = name.strip().lower() if name else None
        p_term = str(proto_id).strip().lower() if proto_id is not None else None
        c_term = str(cat_id).strip().lower() if cat_id is not None else None

        return [
            manifest
            for manifest in registry.values()
            if not (n_term and str(manifest.name).strip().lower() != n_term)
            and not (p_term and str(manifest.proto_id).strip().lower() != p_term)
            and not (c_term and str(manifest.cat_id).strip().lower() != c_term)
        ]

    def get_oauth2_adapter(self, platform: str) -> PlatformManifest:
        """Resolve the OAuth2 adapter for a platform or raise NotImplementedError."""
        adapter = self.list_adapters(name=platform.lower(), proto_id=0)
        if not adapter:
            raise NotImplementedError(
                f"Platform '{platform.lower()}' with protocol 'oauth2' is not supported. "
                "Contact the developers for implementation status."
            )
        return adapter[0]

    def get_pnba_adapter(self, platform: str) -> PlatformManifest:
        """Resolve the PNBA adapter for a platform or raise NotImplementedError."""
        adapter = self.list_adapters(name=platform.lower(), proto_id=1)
        if not adapter:
            raise NotImplementedError(
                f"Platform '{platform.lower()}' with protocol 'pnba' is not supported. "
                "Contact the developers for implementation status."
            )
        return adapter[0]

    def add_adapter_from_github(self, url: str):
        """Clone a repository and register its manifest."""
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

        ini_data = self._load_ini_file(dest_path / "manifest.ini", "platform")
        if not ini_data or not all(
            ini_data.get(f) for f in ("name", "display_name", "cat_id", "proto_id")
        ):
            self._rollback_directory(dest_path)
            raise ValueError(
                "Manifest incomplete: missing one or more of name, cat_id, proto_id."
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

        stub = PlatformManifest(
            id=adapter_id,
            display_name="",
            name="",
            path=str(dest_path),
            venv_path=str(venv_path),
            assets_path=str(self._adapters_assets_dir / adapter_id),
            cat_id=0,
            proto_id=0,
        )

        try:
            manifest_record = self._build_manifest_from_ini(adapter_id, ini_data, stub)
        except ValueError:
            self._rollback_directory(dest_path)
            self._rollback_directory(venv_path)
            raise

        registry[adapter_id] = manifest_record
        self._save_registry(registry)
        logger.info("[+] Registered adapter: '%s'", ini_data["name"])

    def remove_adapter(self, adapter_id: str):
        """Remove adapter workspace folders and registry entry."""
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
        """Pull updates and refresh registry entries for targeted adapters."""
        registry = self._load_registry()
        if not registry:
            logger.warning("[!] Registry is empty or failed to load, aborting update.")
            return

        targets = [adapter_id] if adapter_id else list(registry.keys())

        for target_id in targets:
            manifest = registry.get(target_id)
            if not manifest:
                continue

            adapter_path = Path(manifest.path)
            if not self._is_safe_path(self._adapters_dir, adapter_path):
                logger.error("[!] Update skipped: invalid path for %s", target_id)
                continue

            try:
                Repo(manifest.path).git.pull()
                logger.info("[+] Pulled source updates for: %s", target_id)
            except Exception as e:
                logger.error("[!] Git pull failed for %s: %s", target_id, e)
                continue

            ini_data = self._load_ini_file(adapter_path / "manifest.ini", "platform")
            if not ini_data:
                logger.error(
                    "[!] Could not read updated manifest for %s, skipping.", target_id
                )
                continue

            try:
                registry[target_id] = self._build_manifest_from_ini(
                    target_id, ini_data, manifest
                )
                logger.info("[+] Manifest updated for: %s", target_id)
            except ValueError as e:
                logger.error("[!] Manifest build failed for %s: %s", target_id, e)
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

    def recover_registry(self):
        """Attempt to repopulate the registry from existing adapter directories."""
        if not self._adapters_dir.is_dir():
            logger.error("[!] Adapters directory not found: %s", self._adapters_dir)
            return

        registry = self._load_registry()
        recovered = 0

        for adapter_path in self._adapters_dir.iterdir():
            if not adapter_path.is_dir():
                continue

            adapter_id = adapter_path.name

            if adapter_id in registry:
                logger.debug("[~] Skipping already registered adapter: %s", adapter_id)
                continue

            if not self._validate_adapter_files(adapter_path):
                logger.warning(
                    "[!] Skipping invalid adapter directory: %s", adapter_path
                )
                continue

            ini_data = self._load_ini_file(adapter_path / "manifest.ini", "platform")
            if not ini_data or not all(
                ini_data.get(f) for f in ("name", "display_name", "cat_id", "proto_id")
            ):
                logger.warning("[!] Skipping incomplete manifest in: %s", adapter_path)
                continue

            venv_path = self._adapters_venv_dir / adapter_id
            stub = PlatformManifest(
                id=adapter_id,
                display_name="",
                name="",
                path=str(adapter_path),
                venv_path=str(venv_path),
                assets_path=str(self._adapters_assets_dir / adapter_id),
                cat_id=0,
                proto_id=0,
            )

            try:
                registry[adapter_id] = self._build_manifest_from_ini(
                    adapter_id, ini_data, stub
                )
                logger.info("[+] Recovered adapter: '%s'", ini_data["name"])
                recovered += 1
            except ValueError as e:
                logger.error("[!] Failed to recover adapter at %s: %s", adapter_path, e)

        if recovered:
            self._save_registry(registry)
            logger.info("[+] Recovery complete: %d adapter(s) restored.", recovered)
        else:
            logger.info("[-] No adapters recovered.")
