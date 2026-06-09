"""Utitlies Module."""

import os

from logutils import get_logger

logger = get_logger(__name__)


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
