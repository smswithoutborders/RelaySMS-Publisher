"""Utitlies Module."""

import os
import base64
import json
from functools import wraps
from email.message import EmailMessage
from peewee import DatabaseError

import pymysql
from logutils import get_logger

SUPPORTED_PLATFORM_FILE_PATH = os.path.join("resources", "platforms.json")

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


def load_platforms_from_file(file_path):
    """
    Load platform data from a JSON file.

    Args:
        file_path (str): The path to the JSON file containing platform data.

    Returns:
        dict: A dictionary containing platform data.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            platforms_data = json.load(file)
        return platforms_data
    except FileNotFoundError:
        logger.error("Error: File '%s' not found.", file_path)
        return {}
    except json.JSONDecodeError as e:
        logger.error("Error decoding JSON from '%s': %s", file_path, e)
        return {}


def check_platform_supported(platform_name, protocol):
    """
    Check if the given platform is supported for the specified protocol.

    Args:
        platform_name (str): The platform name to check.
        protocol (str): The protocol to check for the given platform.

    Raises:
        NotImplementedError: If the platform is not supported or the protocol
            does not match the supported protocol.
    """
    platform_details = load_platforms_from_file(SUPPORTED_PLATFORM_FILE_PATH)
    supported_platform = next(
        (
            platform
            for platform in platform_details
            if platform["name"] == platform_name
        ),
        None,
    )

    if not supported_platform:
        raise NotImplementedError(
            f"The platform '{platform_name}' is currently not supported. "
            "Please contact the developers for more information on when "
            "this platform will be implemented."
        )

    expected_protocol = supported_platform.get("protocol_type")

    if protocol != expected_protocol:
        raise NotImplementedError(
            f"The protocol '{protocol}' for platform '{platform_name}' "
            "is currently not supported. "
            f"Expected protocol: '{expected_protocol}'."
        )


def get_platform_details_by_shortcode(shortcode):
    """
    Get the platform details corresponding to the given shortcode.

    Args:
        shortcode (str): The shortcode to look up.

    Returns:
        tuple: A tuple containing (platform_details, error_message).
            - platform_details (dict): Details of the platform if found.
            - error_message (str): Error message if platform is not found,
    """
    platform_details = load_platforms_from_file(SUPPORTED_PLATFORM_FILE_PATH)

    for platform in platform_details:
        if platform.get("shortcode") == shortcode:
            return platform, None

    available_platforms = ", ".join(
        f"'{platform['shortcode']}' for {platform['name']}"
        for platform in platform_details
    )
    error_message = (
        f"No platform found for shortcode '{shortcode}'. "
        f"Available shortcodes: {available_platforms}"
    )

    return None, error_message


def create_email_message(from_email, to_email, subject, body, **kwargs):
    """
    Create an encoded email message from individual email components.

    Args:
        from_email (str): The sender's email address.
        to_email (str): The recipient's email address.
        cc_email (str): The CC (carbon copy) email addresses, separated by commas.
        bcc_email (str): The BCC (blind carbon copy) email addresses, separated by commas.
        subject (str): The subject of the email.
        body (str): The body content of the email.

    Returns:
        dict: A dictionary containing the raw encoded email message, with the key "raw".
    """
    cc_email = kwargs.get("cc_email")
    bcc_email = kwargs.get("bcc_email")

    message = EmailMessage()
    message.set_content(body)

    message["to"] = to_email
    message["from"] = from_email
    message["subject"] = subject

    if cc_email:
        message["cc"] = cc_email
    if bcc_email:
        message["bcc"] = bcc_email

    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    create_message = {"raw": encoded_message}

    return create_message


def parse_content(service_type, content):
    """
    Parse the content string into its components based on the service_type.

    Args:
        service_type (str): The type of the platform (email, text, message).
        content (str): The content string in the format specific to the platform.

    Returns:
        tuple: A tuple containing:
            - parts (tuple): A tuple with the parsed components based on the
                service_type.
            - error (str): An error message if parsing fails, otherwise None.
    """
    if service_type == "email":
        # Email format: 'from:to:cc:bcc:subject:body'
        parts = content.split(":", 5)
        if len(parts) != 6:
            return None, "Email content must have exactly 6 parts."
        from_email, to_email, cc_email, bcc_email, subject, body = parts
        return (from_email, to_email, cc_email, bcc_email, subject, body), None

    if service_type == "text":
        # Text format: 'sender:text'
        parts = content.split(":", 1)
        if len(parts) != 2:
            return None, "Text content must have exactly 2 parts."
        sender, text = parts
        return (sender, text), None

    if service_type == "message":
        # Message format: 'sender:receiver:message'
        parts = content.split(":", 2)
        if len(parts) != 3:
            return None, "Message content must have exactly 3 parts."
        sender, receiver, message = parts
        return (sender, receiver, message), None

    if service_type == "test":
        # Test format: 'sms_sent_time:test_id:msisdn'
        parts = content.split(":", 2)
        if len(parts) != 3:
            return None, "Message content must have exactly 3 parts."
        sms_sent_time, test_id, msisdn = parts
        return (sms_sent_time, test_id, msisdn), None

    return None, "Invalid service_type. Must be 'email', 'text', 'message', or 'test'."


def mask_sensitive_info(value):
    """
    Masks all but the last three digits of the given value.

    Args:
        value (str): The string to be masked.

    Returns:
        str: The masked string with all but the last three digits replaced by '*'.
    """
    if not value:
        return value
    return "*" * (len(value) - 3) + value[-3:]


def ensure_database_exists(host, user, password, database_name):
    """
    Decorator that ensures a MySQL database exists before executing a function.

    Args:
        host (str): The host address of the MySQL server.
        user (str): The username for connecting to the MySQL server.
        password (str): The password for connecting to the MySQL server.
        database_name (str): The name of the database to ensure existence.

    Returns:
        function: Decorated function.
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                connection = pymysql.connect(
                    host=host,
                    user=user,
                    password=password,
                    charset="utf8mb4",
                    collation="utf8mb4_unicode_ci",
                )
                with connection.cursor() as cursor:
                    sql = "CREATE DATABASE IF NOT EXISTS " + database_name
                    cursor.execute(sql)

                logger.debug(
                    "Database %s created successfully (if it didn't exist)",
                    database_name,
                )

            except pymysql.MySQLError as error:
                logger.error("Failed to create database: %s", error)

            finally:
                connection.close()

            return func(*args, **kwargs)

        return wrapper

    return decorator


def create_tables(models):
    """
    Creates tables for the given models if they don't
        exist in their specified database.

    Args:
        models(list): A list of Peewee Model classes.
    """
    if not models:
        logger.warning("No models provided for table creation.")
        return

    try:
        databases = {}
        for model in models:
            database = model._meta.database
            if database not in databases:
                databases[database] = []
            databases[database].append(model)

        for database, db_models in databases.items():
            with database.atomic():
                existing_tables = set(database.get_tables())
                tables_to_create = [
                    model
                    for model in db_models
                    if model._meta.table_name not in existing_tables
                ]

                if tables_to_create:
                    database.create_tables(tables_to_create)
                    logger.info(
                        "Created tables: %s",
                        [model._meta.table_name for model in tables_to_create],
                    )
                else:
                    logger.debug("No new tables to create.")

    except DatabaseError as e:
        logger.error("An error occurred while creating tables: %s", e)
