"""
This program is free software: you can redistribute it under the terms
of the GNU General Public License, v. 3.0. If a copy of the GNU General
Public License was not distributed with this file, see <https://www.gnu.org/licenses/>.
"""

import os
import sys
import shutil
import subprocess
import configparser
from typing import Optional
from git import Repo, RemoteProgress
from tqdm import tqdm

from logutils import get_logger
from utils import get_configs

BASE_DIR = os.path.dirname(__file__)
adapters_dir = get_configs(
    "PLATFORMS_ADAPTERS_DIR", default_value=os.path.join(BASE_DIR, "adapters")
)
adapters_venv_dir = get_configs(
    "PLATFORMS_ADAPTERS_VENV_DIR", default_value=os.path.join(BASE_DIR, "adapters_venv")
)

logger = get_logger(__name__)


class AdapterManager:
    """
    Handles discovery, validation, and installation of platform adapters.
    """

    _adapters_dir = adapters_dir
    _adapters_venv_dir = adapters_venv_dir
    _registry = {}

    @classmethod
    def _populate_registry(cls):
        cls._registry.clear()

        if not os.path.isdir(cls._adapters_dir):
            logger.warning("Adapters directory '%s' does not exist.", cls._adapters_dir)
            return

        for item in os.listdir(cls._adapters_dir):
            adapter_path = os.path.join(cls._adapters_dir, item)
            if not os.path.isdir(adapter_path):
                continue

            manifest_data = cls._load_manifest(adapter_path)
            if manifest_data and (adapter_name := manifest_data.get("name")):
                manifest_data["path"] = adapter_path
                cls._registry[adapter_name] = manifest_data
                logger.info(
                    "Registered adapter '%s' from '%s'", adapter_name, adapter_path
                )
            else:
                logger.warning("Skipping invalid adapter directory: '%s'", adapter_path)

        logger.info("Adapter registry populated with %d adapters.", len(cls._registry))

    @staticmethod
    def _rollback_directory(path: str):
        try:
            shutil.rmtree(path)
            logger.info("Rolled back and removed directory: %s", path)
        except Exception as e:
            logger.error("Failed to remove directory '%s': %s", path, e)

    @staticmethod
    def _validate_adapter_files(path: str) -> bool:
        required = ["manifest.ini", "main.py", "config.ini"]
        missing = [f for f in required if not os.path.isfile(os.path.join(path, f))]
        if missing:
            logger.warning(
                "Missing required files in '%s': %s", path, ", ".join(missing)
            )
            return False
        return True

    @staticmethod
    def _install_adapter_dependencies(requirements_path: str, venv_path: str):
        try:
            subprocess.check_call([sys.executable, "-m", "venv", venv_path])
            pip_path = os.path.join(venv_path, "bin", "pip")
            subprocess.check_call([pip_path, "install", "-r", requirements_path])
            logger.info("Dependencies installed in virtual environment: %s", venv_path)
        except Exception as e:
            logger.error("Dependency installation failed: %s", e)
            raise ValueError("Adapter dependency installation failed.") from e

    @classmethod
    def _load_manifest(cls, path: str) -> Optional[dict]:
        manifest_file = os.path.join(path, "manifest.ini")
        if not os.path.isfile(manifest_file):
            logger.error("Missing manifest at '%s'", manifest_file)
            return None

        config = configparser.ConfigParser()
        config.read(manifest_file)

        if "platform" not in config:
            logger.error("Manifest missing 'platform' section: '%s'", manifest_file)
            return None

        return dict(config["platform"])

    @classmethod
    def get_adapter(cls, name: str, protocol: str) -> Optional[str]:
        if not cls._registry:
            cls._populate_registry()

        manifest = cls._registry.get(name)
        if manifest and protocol.lower() in (v.lower() for v in manifest.values()):
            return manifest.get("path")

        logger.warning("Adapter '%s' with protocol '%s' not found.", name, protocol)
        return None

    @classmethod
    def add_adapter_from_github(cls, url: str):
        os.makedirs(cls._adapters_dir, exist_ok=True)

        class CloneProgress(RemoteProgress):
            def __init__(self):
                super().__init__()
                self.progress_bar = None

            def update(self, op_code, cur_count, max_count=None, message=""):
                if max_count and not self.progress_bar:
                    self.progress_bar = tqdm(
                        total=max_count, unit="objects", desc="Cloning", leave=False
                    )
                if self.progress_bar:
                    self.progress_bar.n = cur_count
                    self.progress_bar.refresh()
                if message:
                    logger.debug("Git progress: %s", message)

            def __del__(self):
                if self.progress_bar:
                    self.progress_bar.close()

        repo_name = url.rstrip("/").split("/")[-1].replace(".git", "")
        dest_path = os.path.join(cls._adapters_dir, repo_name)

        if os.path.exists(dest_path):
            logger.info("Repository already exists: %s", dest_path)
            return

        Repo.clone_from(url, dest_path, progress=CloneProgress())
        logger.info("Cloned adapter repository to '%s'", dest_path)

        if not cls._validate_adapter_files(dest_path):
            cls._rollback_directory(dest_path)
            raise ValueError(f"Invalid adapter structure at '{dest_path}'.")

        manifest_data = cls._load_manifest(dest_path)
        if not manifest_data:
            cls._rollback_directory(dest_path)
            raise ValueError(f"Manifest load failed for '{dest_path}'.")

        adapter_name = manifest_data.get("name")
        protocol = manifest_data.get("protocol")

        if not adapter_name:
            cls._rollback_directory(dest_path)
            raise ValueError("Adapter manifest missing 'name'.")

        new_dir_name = f"{adapter_name}_{protocol}".lower()
        new_dest_path = os.path.join(cls._adapters_dir, new_dir_name)

        if os.path.exists(new_dest_path):
            cls._rollback_directory(dest_path)
            raise ValueError(f"Adapter '{new_dir_name}' already exists.")

        os.rename(dest_path, new_dest_path)
        manifest_data["path"] = new_dest_path

        requirements_path = os.path.join(new_dest_path, "requirements.txt")
        if os.path.isfile(requirements_path):
            venv_path = os.path.join(cls._adapters_venv_dir, new_dir_name)

            if os.path.exists(venv_path):
                raise ValueError(f"Virtual environment already exists: {venv_path}")

            os.makedirs(venv_path, exist_ok=True)

            try:
                cls._install_adapter_dependencies(requirements_path, venv_path)
            except ValueError:
                cls._rollback_directory(new_dest_path)
                cls._rollback_directory(venv_path)
                raise

        logger.info(
            "Adapter '%s' added successfully with protocol '%s'.",
            adapter_name,
            protocol,
        )
