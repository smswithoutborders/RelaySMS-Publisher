"""
This program is free software: you can redistribute it under the terms
of the GNU General Public License, v. 3.0. If a copy of the GNU General
Public License was not distributed with this file, see <https://www.gnu.org/licenses/>.
"""

import base64
import struct
import hashlib
import hmac
import pytest
import grpc
from smswithoutborders_libsig.keypairs import x25519
from smswithoutborders_libsig.ratchets import Ratchets, States

import vault_pb2
import vault_pb2_grpc

from logutils import get_logger

logger = get_logger(__name__)


@pytest.fixture
def keypairs(tmp_path):
    """Fixture to initialize and return keypairs for testing."""

    def initialize_keypair(db_path):
        """Initializes a keypair and returns it along with its public key."""
        keypair = x25519(db_path)
        return keypair, keypair.init()

    pub_keypair, pub_pk = initialize_keypair(tmp_path / "pub.db")
    did_keypair, did_pk = initialize_keypair(tmp_path / "did.db")
    return pub_keypair, pub_pk, did_keypair, did_pk


@pytest.fixture
def authenticated_entity(grpc_stub):
    """Fixture to authenticate an entity using gRPC."""

    class GrpcError:
        """Represents a gRPC error with a code and details."""

        def __init__(self, code, details):
            self.code = code
            self.details = details

    def _authenticated_entity(**kwargs):
        did_pk = (
            base64.b64encode(kwargs.get("did_pk")).decode()
            if kwargs.get("did_pk")
            else None
        )
        pub_pk = (
            base64.b64encode(kwargs.get("pub_pk")).decode()
            if kwargs.get("pub_pk")
            else None
        )

        try:
            stub = grpc_stub(vault_pb2_grpc.EntityStub)
            request = vault_pb2.AuthenticateEntityRequest(
                phone_number=kwargs.get("phone_number"),
                password=kwargs.get("password"),
                client_publish_pub_key=pub_pk,
                client_device_id_pub_key=did_pk,
                ownership_proof_response=kwargs.get("ownership_proof_response"),
            )
            response = stub.AuthenticateEntity(request)
            error = None
        except grpc.RpcError as e:
            response = None
            error = GrpcError(code=e.code().name, details=e.details())

        return response, error

    return _authenticated_entity


def encrypt_message(message, shared_key, server_pub_key, keystore_path):
    """Encrypts a message using the provided shared key and server public key."""
    state = States()
    Ratchets.alice_init(state, shared_key, server_pub_key, keystore_path)
    header, ciphertext = Ratchets.encrypt(
        state=state, data=message.encode(), AD=server_pub_key
    )
    serialized_header = header.serialize()
    encrypted_payload = (
        struct.pack("<i", len(serialized_header)) + serialized_header + ciphertext
    )
    return encrypted_payload


def generate_device_id(phone_number, device_id_public_key, secret_key):
    """Generates a device ID."""
    combined_input = phone_number.encode("utf-8") + device_id_public_key
    hmac_object = hmac.new(secret_key, combined_input, hashlib.sha256)
    return hmac_object.digest()


def create_payload_v0(encrypted_payload, platform_shortcode, device_id):
    """Creates a v0 payload."""
    payload = (
        struct.pack("<i", len(encrypted_payload))
        + platform_shortcode
        + encrypted_payload
        + device_id
    )
    encoded_payload = base64.b64encode(payload).decode()
    return encoded_payload


def create_payload_v1(
    encrypted_payload,
    platform_shortcode,
    device_id,
    language,
):
    """Creates a v1 payload."""
    payload = (
        bytes([1])
        + struct.pack("<H", len(encrypted_payload))
        + bytes([len(device_id)])
        + platform_shortcode
        + encrypted_payload
        + device_id
        + language
    )
    encoded_payload = base64.b64encode(payload).decode()
    return encoded_payload


def perform_auth_and_publish(
    authenticated_entity,
    keypairs,
    tmp_path,
    send_message,
    credentials,
    messages,
    platform,
    platform_shortcode,
    use_device_id,
    create_payload_func,
    create_payload_args,
    include_tokens=False,
    tokens=None,
):
    """Helper function to perform authentication and publishing."""
    pub_keypair, pub_pk, did_keypair, did_pk = keypairs
    phone_number = credentials["phone_number"]
    password = credentials["password"]

    res, error = authenticated_entity(
        phone_number=phone_number,
        password=password,
        pub_pk=pub_pk,
        did_pk=did_pk,
    )
    if error:
        pytest.fail(f"Authentication failed: {error.code} -- {error.details}")

    if not res.requires_ownership_proof:
        logger.error("server Response: %s", res)
        pytest.fail("Ownership proof was not required when it should be.")

    ownership_proof_response = credentials["ownership_proof_response"]
    res, error = authenticated_entity(
        phone_number=phone_number,
        password=password,
        pub_pk=pub_pk,
        did_pk=did_pk,
        ownership_proof_response=ownership_proof_response,
    )
    if error:
        pytest.fail(f"Authentication failed: {error.code} -- {error.details}")

    try:
        server_pub_key = base64.b64decode(res.server_publish_pub_key)
        server_did_key = base64.b64decode(res.server_device_id_pub_key)
        pub_shared_key = pub_keypair.agree(server_pub_key)
        did_shared_key = did_keypair.agree(server_did_key)
    except Exception as e:
        pytest.fail(f"Key agreement failed: {str(e)}")

    keystore_path = tmp_path / "state.db"

    platform_message = messages[f"{platform}_message"]
    if include_tokens:
        platform_message += f":{tokens['access_token']}:{tokens['refresh_token']}"

    try:
        encrypted_payload = encrypt_message(
            platform_message, pub_shared_key, server_pub_key, keystore_path
        )
    except Exception as e:
        pytest.fail(f"Message encryption failed: {str(e)}")

    device_id = (
        generate_device_id(phone_number, did_pk, did_shared_key)
        if use_device_id
        else b""
    )
    try:
        encoded_payload = create_payload_func(
            encrypted_payload, platform_shortcode, device_id, *create_payload_args
        )
    except Exception as e:
        pytest.fail(f"Payload creation failed: {str(e)}")

    if use_device_id:
        phone_number = phone_number[:-1] + str(int(phone_number[-1]) + 1)
    response = send_message(phone_number, encoded_payload)
    logger.info("Response: %s", response.json())
    assert (
        response.status_code == 200
    ), f"Expected status code 200, got {response.status_code}"


@pytest.mark.parametrize(
    "platform, platform_shortcode, use_device_id",
    [
        ("gmail", b"g", False),  # Gmail with phone number
        ("gmail", b"g", True),  # Gmail with device ID
    ],
)
def test_auth_and_publish_v0(
    authenticated_entity,
    keypairs,
    tmp_path,
    send_message,
    credentials,
    messages,
    platform,
    platform_shortcode,
    use_device_id,
):
    """Tests publishing functionality for v0."""
    perform_auth_and_publish(
        authenticated_entity,
        keypairs,
        tmp_path,
        send_message,
        credentials,
        messages,
        platform,
        platform_shortcode,
        use_device_id,
        create_payload_v0,
        [],
    )


@pytest.mark.parametrize(
    "platform, platform_shortcode, use_device_id, include_tokens",
    [
        ("gmail", b"g", False, True),  # Gmail with phone number
        # ("gmail", b"g", True, True),  # Gmail with device ID
        # ("gmail", b"g", False, False),  # Without tokens
    ],
)
def test_auth_and_publish_v1(
    authenticated_entity,
    keypairs,
    tmp_path,
    send_message,
    credentials,
    tokens,
    messages,
    platform,
    platform_shortcode,
    use_device_id,
    include_tokens,
):
    """Tests publishing functionality for v1."""
    language = credentials["language"].encode()

    perform_auth_and_publish(
        authenticated_entity,
        keypairs,
        tmp_path,
        send_message,
        credentials,
        messages,
        platform,
        platform_shortcode,
        use_device_id,
        create_payload_v1,
        [language],
        include_tokens=include_tokens,
        tokens=tokens,
    )
