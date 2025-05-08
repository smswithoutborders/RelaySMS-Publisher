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
import hashlib
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
    _cache_hash = None

    @classmethod
    def _calculate_directory_hash(cls) -> str:
        """
        Calculate a hash of the current state of the adapters directory.

        Returns:
            str: The MD5 hash of the adapters directory.
        """
        hash_md5 = hashlib.md5()
        if not os.path.isdir(cls._adapters_dir):
            return ""

        for root, dirs, files in os.walk(cls._adapters_dir):
            for name in sorted(dirs + files):
                path = os.path.join(root, name)
                hash_md5.update(path.encode("utf-8"))
                if os.path.isfile(path):
                    with open(path, "rb") as f:
                        hash_md5.update(f.read())

        return hash_md5.hexdigest()

    @classmethod
    def _is_registry_outdated(cls) -> bool:
        """
        Check if the registry is outdated by comparing the directory hash.

        Returns:
            bool: True if the registry is outdated, False otherwise.
        """
        current_hash = cls._calculate_directory_hash()
        if cls._cache_hash != current_hash:
            cls._cache_hash = current_hash
            return True
        return False

    @classmethod
    def _populate_registry(cls):
        """
        Populate the registry with adapter metadata if there are changes in the adapters directory.
        """
        if not os.path.isdir(cls._adapters_dir):
            logger.warning(
                "Adapters directory '%s' does not exist. Creating it.",
                cls._adapters_dir,
            )
            os.makedirs(cls._adapters_dir, exist_ok=True)

        if not cls._is_registry_outdated():
            logger.debug("Registry is up-to-date. No changes detected.")
            return

        cls._registry.clear()

        for item in os.listdir(cls._adapters_dir):
            adapter_path = os.path.join(cls._adapters_dir, item)
            if not os.path.isdir(adapter_path):
                continue

            manifest_data = cls._load_manifest(adapter_path)
            if manifest_data and (adapter_name := manifest_data.get("name")):
                protocol = manifest_data.get("protocol", "").lower()
                key = f"{adapter_name}_{protocol}".lower()
                manifest_data["path"] = adapter_path
                cls._registry[key] = manifest_data
                logger.info(
                    "Registered adapter '%s' with protocol '%s' from '%s'",
                    adapter_name,
                    protocol,
                    adapter_path,
                )
            else:
                logger.warning("Skipping invalid adapter directory: '%s'", adapter_path)

        logger.info("Adapter registry populated with %d adapters.", len(cls._registry))

    @staticmethod
    def _rollback_directory(path: str):
        """
        Roll back changes by removing a specified directory.

        Args:
            path (str): The path of the directory to remove.
        """
        try:
            shutil.rmtree(path)
            logger.info("Rolled back and removed directory: %s", path)
        except Exception as e:
            logger.error("Failed to remove directory '%s': %s", path, e)

    @staticmethod
    def _validate_adapter_files(path: str) -> bool:
        """
        Validate the presence of required files in an adapter directory.

        Args:
            path (str): The path to the adapter directory.

        Returns:
            bool: True if all required files are present, False otherwise.
        """
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
        """
        Install adapter dependencies in a virtual environment.

        Args:
            requirements_path (str): Path to the requirements.txt file.
            venv_path (str): Path to the virtual environment directory.

        Raises:
            ValueError: If dependency installation fails.
        """
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
        """
        Load the manifest file from an adapter directory.

        Args:
            path (str): The path to the adapter directory.

        Returns:
            Optional[dict]: A dictionary containing manifest data, or None if invalid.
        """
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
    def get_adapter(cls, shortcode: Optional[str] = None) -> Optional[dict]:
        """
        Retrieve an adapter's manifest based on its shortcode.

        Args:
            shortcode (Optional[str]): The shortcode of the adapter.

        Returns:
            Optional[dict]: The adapter's manifest data, or None if not found.
        """
        cls._populate_registry()

        if shortcode:
            for manifest in cls._registry.values():
                if manifest.get("shortcode") == shortcode:
                    return manifest
            logger.warning("Adapter with shortcode '%s' not found.", shortcode)
            return None

        logger.warning("Shortcode must be provided to get an adapter.")
        return None

    @classmethod
    def get_adapter_path(cls, name: str, protocol: str) -> Optional[dict]:
        """
        Retrieve the adapter's path and virtual environment path.

        Args:
            name (str): The name of the adapter.
            protocol (str): The protocol used by the adapter.

        Returns:
            Optional[dict]: A dictionary containing the adapter path and
                virtual environment path, or None if not found.
        """
        cls._populate_registry()

        manifest = cls._registry.get(f"{name}_{protocol}".lower())
        if manifest:
            adapter_path = manifest.get("path")
            adapter_dir_name = os.path.basename(adapter_path)
            venv_path = os.path.join(cls._adapters_venv_dir, adapter_dir_name)
            return {"path": adapter_path, "venv_path": venv_path}

        logger.warning(
            "Adapter with name '%s' and protocol '%s' not found.",
            name,
            protocol,
        )
        return None

    @classmethod
    def add_adapter_from_github(cls, url: str):
        """
        Add a new adapter by cloning a GitHub repository.

        Args:
            url (str): The URL of the GitHub repository.

        Raises:
            ValueError: If the adapter structure is invalid or dependencies fail to install.
        """
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

    @classmethod
    def remove_adapter(cls, name: str):
        """
        Remove an adapter by its name.

        Args:
            name (str): The name of the adapter to remove.

        Raises:
            ValueError: If the adapter does not exist.
        """
        cls._populate_registry()

        manifest = cls._registry.get(name)
        if not manifest:
            raise ValueError(f"Adapter '{name}' does not exist.")

        adapter_path = manifest.get("path")
        adapter_dir_name = os.path.basename(adapter_path)
        venv_path = os.path.join(cls._adapters_venv_dir, adapter_dir_name)

        if os.path.exists(adapter_path):
            cls._rollback_directory(adapter_path)

        if os.path.exists(venv_path):
            cls._rollback_directory(venv_path)

        logger.info("Adapter '%s' removed successfully.", name)
