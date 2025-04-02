"""
This program is free software: you can redistribute it under the terms
of the GNU General Public License, v. 3.0. If a copy of the GNU General
Public License was not distributed with this file, see <https://www.gnu.org/licenses/>.
"""

import configparser
import grpc
import pytest
import requests

from logutils import get_logger

logger = get_logger(__name__)


def pytest_addoption(parser):
    """Adds the --env CLI argument for pytest."""
    parser.addoption(
        "--env",
        action="store",
        default="local",
        choices=["local", "staging", "prod"],
        help="Set test environment",
    )


def load_test_config():
    """
    Loads the test configuration from the 'tests/test_config.ini' file.

    Returns:
        configparser.ConfigParser: The configuration parser object containing
        the test configuration.
    """
    config = configparser.ConfigParser()
    config.read("tests/test_config.ini")
    return config


@pytest.fixture(scope="session")
def test_config():
    """
    Loads and returns the test configuration.

    Returns:
        dict: A dictionary containing the test configuration settings.
    """
    return load_test_config()


@pytest.fixture
def credentials(test_config):
    """Fixture to provide credentials."""
    return test_config["credentials"]


@pytest.fixture
def tokens(test_config):
    """Fixture to provide tokens."""
    return test_config["tokens"]


@pytest.fixture
def messages(test_config):
    """Fixture to provide messages."""
    return test_config["messages"]


@pytest.fixture(scope="session")
def grpc_channel(pytestconfig, test_config):
    """Provides a gRPC channel based on the selected environment."""
    environment = pytestconfig.getoption("--env")
    config = test_config[environment]
    address = f"{config['vault_grpc_host']}:{config['vault_grpc_port']}"

    if config.getboolean("vault_grpc_secure"):
        channel_credentials = grpc.ssl_channel_credentials(
            open(config["vault_grpc_cert"], "rb").read()
            if config["vault_grpc_cert"]
            else None
        )
        logger.info("Using secure gRPC channel to %s", address)
        return grpc.secure_channel(address, channel_credentials)

    logger.warning("Using insecure gRPC channel to %s", address)
    return grpc.insecure_channel(address)


@pytest.fixture
def grpc_stub(grpc_channel):
    """Factory fixture to create any gRPC stub dynamically."""

    def _get_stub(stub_class):
        return stub_class(grpc_channel)

    return _get_stub


@pytest.fixture
def send_message(pytestconfig, test_config):
    """Fixture to send a message over HTTP based on the selected environment."""
    environment = pytestconfig.getoption("--env")
    config = test_config[environment]
    url = config["gateway_server_http_url"]

    def _send_message(phone_number, encoded_payload):
        response = requests.post(
            url,
            timeout=30,
            json={"address": phone_number, "text": encoded_payload},
        )
        return response

    return _send_message
