"""
This program is free software: you can redistribute it under the terms
of the GNU General Public License, v. 3.0. If a copy of the GNU General
Public License was not distributed with this file, see <https://www.gnu.org/licenses/>.
"""

import sys
import os
import importlib.util
import shutil
import configparser
from typing import Optional
from git import Repo, RemoteProgress
from tqdm import tqdm
from platforms.adapter_interfaces import BaseAdapterInterface
from logutils import get_logger

logger = get_logger(__name__)


class AdapterManager:
    """
    Handles discovery and importing of adapters.
    """

    _adapters_dir = os.path.join(os.path.dirname(__file__), "adapters")

    @staticmethod
    def _rollback_directory(path: str):
        """
        Deletes a directory and its contents.

        Args:
            path (str): The path to the directory to delete.
        """
        try:
            shutil.rmtree(path)
            logger.info("Rolled back and removed directory: %s", path)
        except Exception as e:
            logger.error("Failed to remove directory %s: %s", path, e)

    @staticmethod
    def _validate_adapter_files(path: str) -> bool:
        """
        Validates that the required adapter files exist in the given directory.

        Args:
            path (str): The path to the adapter directory.

        Returns:
            bool: True if all required files are present, False otherwise.
        """
        required_files = ["manifest.ini", "main.py", "config.ini"]
        missing = [
            f for f in required_files if not os.path.isfile(os.path.join(path, f))
        ]
        if missing:
            logger.warning("Missing files in %s: %s", path, ", ".join(missing))
            return False
        return True

    @staticmethod
    def import_adapter(
        path: str,
        expected_name: str,
        expected_protocol: str,
        rollback_on_failure: bool = True,
    ) -> Optional[BaseAdapterInterface]:
        """
        Imports an adapter from the specified path.

        Args:
            path (str): The path to the adapter directory.
            expected_name (str): The expected name of the adapter.
            expected_protocol (str): The expected protocol of the adapter.
            rollback_on_failure (bool): Whether to delete the directory on failure.

        Returns:
            Optional[BaseAdapterInterface]: An instance of the adapter if successful,
                None otherwise.
        """
        if not AdapterManager._validate_adapter_files(path):
            if rollback_on_failure:
                AdapterManager._rollback_directory(path)
            return None

        try:
            config = configparser.ConfigParser()
            config.read(os.path.join(path, "manifest.ini"))

            name = config.get("platform", "name", fallback="").lower()
            protocol = config.get("platform", "protocol", fallback="").lower()

            if name != expected_name.lower() or protocol != expected_protocol.lower():
                logger.warning(
                    "Adapter %s/%s does not match manifest. %s",
                    name,
                    protocol,
                    "Rolling back." if rollback_on_failure else "Rollback not enabled.",
                )
                if rollback_on_failure:
                    AdapterManager._rollback_directory(path)
                return None

            if path not in sys.path:
                sys.path.insert(0, path)

            spec = importlib.util.spec_from_file_location(
                f"platforms.adapters.{os.path.basename(path)}.main",
                os.path.join(path, "main.py"),
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            class_name = f"{name}{protocol}Adapter".lower()
            classes = {cls.lower(): getattr(module, cls) for cls in dir(module)}
            adapter_cls = classes.get(class_name)

            if adapter_cls:
                instance = adapter_cls()
                logger.info("Successfully imported adapter: %s", class_name)
                return instance

            logger.warning("Adapter class '%s' not found in %s", class_name, path)

        except Exception as e:
            logger.exception("Error importing adapter from %s: %s", path, e)

        if rollback_on_failure:
            logger.info("Rolling back due to import error.")
            AdapterManager._rollback_directory(path)
        else:
            logger.info("Rollback not enabled despite import error.")
        return None

    @classmethod
    def load_adapter(cls, name: str, protocol: str) -> Optional[BaseAdapterInterface]:
        """
        Loads an adapter by name and protocol from the adapters directory.

        Args:
            name (str): The name of the adapter.
            protocol (str): The protocol of the adapter.

        Returns:
            Optional[BaseAdapterInterface]: The adapter class if found, None otherwise.

        Raises:
            ModuleNotFoundError: If no matching adapter is found.
        """
        if not os.path.isdir(cls._adapters_dir):
            logger.warning("Adapters directory missing: %s", cls._adapters_dir)
            return None

        for subdir in os.listdir(cls._adapters_dir):
            path = os.path.join(cls._adapters_dir, subdir)
            if os.path.isdir(path):
                adapter = cls.import_adapter(
                    path, name, protocol, rollback_on_failure=False
                )
                if adapter:
                    return type(adapter)

        raise ModuleNotFoundError(f"No adapter found for {name}/{protocol}")

    @classmethod
    def add_adapter_from_github(cls, url: str):
        """
        Clones an adapter repository from GitHub and validates it.

        Args:
            url (str): The URL of the GitHub repository.

        Raises:
            ValueError: If the cloned repository is not a valid adapter.
            Exception: If an error occurs during cloning.
        """
        os.makedirs(cls._adapters_dir, exist_ok=True)

        class CloneProgress(RemoteProgress):
            """
            Tracks the progress of a Git repository clone operation.
            """

            def __init__(self):
                """
                Initializes the progress tracker.
                """
                super().__init__()
                self.progress_bar = None

            def update(self, op_code, cur_count, max_count=None, message=""):
                """
                Updates the progress bar.

                Args:
                    op_code: The operation code.
                    cur_count: The current count of objects processed.
                    max_count: The total number of objects (optional).
                    message: Additional message (optional).
                """
                if max_count:
                    if not self.progress_bar:
                        self.progress_bar = tqdm(
                            total=max_count, unit="objects", desc="Cloning", leave=False
                        )
                    self.progress_bar.n = cur_count
                    self.progress_bar.refresh()
                if message:
                    logger.debug("Git progress: %s", message)

            def __del__(self):
                """
                Cleans up the progress bar.
                """
                if self.progress_bar:
                    self.progress_bar.close()

        repo_name = url.rstrip("/").split("/")[-1].replace(".git", "")
        dest_path = os.path.join(cls._adapters_dir, repo_name)

        if os.path.exists(dest_path):
            logger.info("Repo '%s' already exists at %s", repo_name, dest_path)
            return

        try:
            Repo.clone_from(url, dest_path, progress=CloneProgress())
            logger.info("Cloned GitHub repo '%s' into '%s'", repo_name, dest_path)

            if not cls._validate_adapter_files(dest_path):
                logger.error(
                    "Validation failed for adapter at '%s'. Rolling back.", dest_path
                )
                cls._rollback_directory(dest_path)
                raise ValueError(
                    f"Cloned repository at {dest_path} is not a valid adapter."
                )
        except Exception as e:
            logger.error("An error occurred while cloning the repository: %s", e)
            raise
