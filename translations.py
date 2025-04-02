"""
This program is free software: you can redistribute it under the terms
of the GNU General Public License, v. 3.0. If a copy of the GNU General
Public License was not distributed with this file, see <https://www.gnu.org/licenses/>.
"""

import configparser
import os


class Localization:
    """A class to manage translations."""

    def __init__(self, file_path=None, default_locale="en"):
        """
        Initialize the Localization manager.

        Args:
            file_path (str, optional): Path to the localization file.
            default_locale (str): Default language code.
        """
        self.file_path = file_path or os.path.join("configs", "localization.ini")
        self.config = self._load_config()
        self.locale_code = None
        self.set_locale(default_locale)

    def _load_config(self):
        """Load and parse the localization file."""
        if not os.path.exists(self.file_path):
            raise FileNotFoundError(f"Localization file '{self.file_path}' is missing.")

        config = configparser.ConfigParser()
        config.read(self.file_path)
        return config

    def set_locale(self, locale_code):
        """
        Set the active locale for translations.

        Args:
            locale_code (str): The language code to use.

        Raises:
            ValueError: If the specified locale is not available.
        """
        if locale_code not in self.config:
            available_locales = ", ".join(self.config.sections())
            raise ValueError(
                f"Localization for '{locale_code}' is not available. "
                f"Available options: {available_locales}"
            )

        self.locale_code = locale_code

    def translate(self, key):
        """
        Retrieve the translation for a given key.

        Args:
            key (str): The translation key.

        Returns:
            str: The translated string.

        Raises:
            KeyError: If the key is not found in the specified locale section.
        """
        if self.locale_code is None:
            raise RuntimeError("Locale is not set. Call set_locale() first.")

        if not self.config.has_option(self.locale_code, key):
            raise KeyError(
                f"Translation key '{key}' is missing under the '{self.locale_code}' locale."
            )

        return self.config.get(self.locale_code, key)
