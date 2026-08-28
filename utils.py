"""Utitlies Module."""

import os
from typing import List, Optional

from logutils import get_logger

logger = get_logger(__name__)


class PlatformAwareError(Exception):
    """Base for exceptions that may know which platform they occurred on."""

    def __init__(self, message: str, *, platform_name: Optional[str] = None):
        super().__init__(message)
        self.platform_name = platform_name


def get_configs(config_name, strict=False, default_value=None):
    """
    Retrieves the value of a configuration from the environment variables.

    Args:
        config_name (str): The name of the configuration to retrieve.
        strict (bool): If True, raises an error if the configuration
            is not found. Default is False.
        default_value (str): The default value to return if the configuration
            is not found and strict is False. Default is None.

    Returns:
        str: The value of the configuration, or default_value if not found and s
            trict is False.

    Raises:
        KeyError: If the configuration is not found and strict is True.
        ValueError: If the configuration value is empty and strict is True.
    """
    try:
        value = (
            os.environ[config_name]
            if strict
            else os.environ.get(config_name) or default_value
        )
        if strict and (value is None or value.strip() == ""):
            raise ValueError(f"Configuration '{config_name}' is missing or empty.")
        return value
    except KeyError as error:
        logger.error(
            "Configuration '%s' not found in environment variables: %s",
            config_name,
            error,
        )
        raise
    except ValueError as error:
        logger.error("Configuration '%s' is empty: %s", config_name, error)
        raise


def get_config_bool(config_name: str, default_value: bool = False) -> bool:
    """Retrieves a configuration as a boolean ("true", case-insensitive)."""
    return (
        get_configs(config_name, default_value=str(default_value)).strip().lower()
        == "true"
    )


def get_config_list(
    config_name: str, default_value: Optional[List[str]] = None
) -> List[str]:
    """Retrieves a comma-separated configuration as a list of trimmed values."""
    raw = get_configs(config_name, default_value="") or ""
    values = [item.strip() for item in raw.split(",") if item.strip()]
    return values or (default_value or [])


def set_configs(config_name: str, config_value: str) -> None:
    """
    Sets the value of a configuration in the environment variables.

    Args:
        config_name (str): The name of the configuration to set.
        config_value (str): The value of the configuration to set.

    Raises:
        ValueError: If config_name or config_value is empty.
    """
    if not config_name or not config_value:
        error_message = (
            f"Cannot set configuration. Invalid config_name '{config_name}' ",
            "or config_value '{config_value}'.",
        )
        logger.error(error_message)
        raise ValueError(error_message)

    try:
        os.environ[config_name] = config_value
    except Exception as error:
        logger.error("Failed to set configuration '%s': %s", config_name, error)
        raise
