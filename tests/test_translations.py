"""
This program is free software: you can redistribute it under the terms
of the GNU General Public License, v. 3.0. If a copy of the GNU General
Public License was not distributed with this file, see <https://www.gnu.org/licenses/>.
"""

import pytest
from translations import Localization

TEST_LOCALIZATION_DATA = """
[en]
greeting = Hello, welcome!
farewell = Goodbye, see you soon.

[fr]
greeting = Bonjour, bienvenue !
farewell = Au revoir, à bientôt.

[de]
greeting = Hallo, willkommen!
"""


@pytest.fixture
def temp_ini_file(tmp_path):
    """
    Creates a temporary localization INI file for testing.
    """
    ini_path = tmp_path / "localization.ini"
    ini_path.write_text(TEST_LOCALIZATION_DATA.strip(), encoding="utf-8")
    return ini_path


@pytest.fixture
def localization(temp_ini_file):
    """
    Returns a Localization instance using the temporary INI file.
    """
    return Localization(file_path=temp_ini_file, default_locale="en")


@pytest.mark.parametrize(
    "locale, key, expected",
    [
        ("en", "greeting", "Hello, welcome!"),
        ("en", "farewell", "Goodbye, see you soon."),
        ("fr", "greeting", "Bonjour, bienvenue !"),
        ("fr", "farewell", "Au revoir, à bientôt."),
        ("de", "greeting", "Hallo, willkommen!"),
    ],
)
def test_translate_existing_keys(localization, locale, key, expected):
    """
    Test retrieving valid translations across multiple locales.
    """
    localization.set_locale(locale)
    assert localization.translate(key) == expected


def test_translate_missing_key(localization):
    """
    Test behavior when requesting a missing translation key.
    """
    with pytest.raises(
        KeyError, match="Translation key 'unknown_key' is missing under the 'en' locale"
    ):
        localization.translate("unknown_key")


def test_set_locale_valid(localization):
    """
    Test setting a valid locale and ensure translations work as expected.
    """
    localization.set_locale("fr")
    assert localization.translate("farewell") == "Au revoir, à bientôt."

    localization.set_locale("de")
    assert localization.translate("greeting") == "Hallo, willkommen!"


def test_set_locale_invalid(localization):
    """
    Test behavior when setting an unsupported locale.
    """
    with pytest.raises(ValueError, match="Localization for 'es' is not available"):
        localization.set_locale("es")


def test_set_locale_does_not_change_on_failure(localization):
    """
    Ensure that failing to set a locale does not change the previous valid locale.
    """
    assert localization.locale_code == "en"

    with pytest.raises(ValueError):
        localization.set_locale("es")

    assert localization.locale_code == "en"


def test_default_locale_is_used_when_no_locale_is_set(temp_ini_file):
    """
    Ensure the default locale is set correctly when no explicit locale is provided.
    """
    loc = Localization(file_path=temp_ini_file)
    assert loc.translate("greeting") == "Hello, welcome!"


def test_missing_ini_file():
    """
    Test error handling when the INI file is missing.
    """
    with pytest.raises(
        FileNotFoundError, match="Localization file 'missing.ini' is missing"
    ):
        Localization(file_path="missing.ini")


def test_translate_without_setting_locale(temp_ini_file):
    """
    Test behavior when translate() is called without setting a valid locale.
    """
    loc = Localization(file_path=temp_ini_file, default_locale="en")
    loc.locale_code = None

    with pytest.raises(RuntimeError, match="Locale is not set"):
        loc.translate("greeting")


def test_translation_falls_back_to_default_on_invalid_locale(localization):
    """
    Test that if setting a locale fails, translations continue using the default locale.
    """
    assert localization.locale_code == "en"

    with pytest.raises(ValueError, match="Localization for 'es' is not available"):
        localization.set_locale("es")

    assert localization.translate("greeting") == "Hello, welcome!"
