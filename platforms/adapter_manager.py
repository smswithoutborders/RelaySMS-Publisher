"""
This program is free software: you can redistribute it under the terms
of the GNU General Public License, v. 3.0. If a copy of the GNU General
Public License was not distributed with this file, see <https://www.gnu.org/licenses/>.
"""

import importlib
from typing import Type
from platforms.adapter_interfaces import OAuthAdapterInterface
import os
import configparser


class AdapterManager:
    """
    Handles discovery and management of adapters.
    """

    @staticmethod
    def find_adapter(name: str, protocol: str, directory: str = None) -> str:
        """
        Recursively searches the adapters/ directory for config.ini files
        and matches the adapter by name and protocol.

        Args:
            name (str): The name of the adapter to find.
            protocol (str): The protocol of the adapter to find.
            directory (str): The root directory to start the search.
                Defaults to the "platforms/adapters" directory in the project root.

        Returns:
            str: The path to the matching adapter's directory, or None if not found.
        """
        if directory is None:
            directory = os.path.join(os.path.dirname(__file__), "adapters")

        for root, _, files in os.walk(directory):
            if "config.ini" in files:
                config_path = os.path.join(root, "config.ini")
                config = configparser.ConfigParser()
                config.read(config_path)

                if (
                    config.has_section("Setup")
                    and config.get("Setup", "name", fallback="") == name
                    and config.get("Setup", "protocol", fallback="") == protocol
                ):
                    return root
        return None
