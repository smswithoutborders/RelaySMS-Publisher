"""
This program is free software: you can redistribute it under the terms
of the GNU General Public License, v. 3.0. If a copy of the GNU General
Public License was not distributed with this file, see <https://www.gnu.org/licenses/>.
"""

import base64
import struct
import pytest
import grpc
from smswithoutborders_libsig.keypairs import x25519
from smswithoutborders_libsig.ratchets import Ratchets, States

import vault_pb2
import vault_pb2_grpc


class GrpcError:
    """Represents a gRPC error with a code and details."""

    def __init__(self, code, details):
        self.code = code
        self.details = details


def initialize_keypair(db_path):
    """Initializes a keypair and returns it along with its public key."""
    keypair = x25519(db_path)
    return keypair, keypair.init()


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


def create_payload(encrypted_payload):
    """Creates a payload from the encrypted message payload."""
    payload = (
        bytes([0])
        + bytes([10])
        + bytes([1])
        + struct.pack("<H", len(encrypted_payload))
        + b"e"
        + encrypted_payload
    )
    encoded_payload = base64.b64encode(payload).decode()
    return encoded_payload


@pytest.fixture
def keypairs(tmp_path):
    """Fixture to initialize and return keypairs for testing."""
    pub_keypair, pub_pk = initialize_keypair(tmp_path / "pub.db")
    did_keypair, did_pk = initialize_keypair(tmp_path / "did.db")
    return pub_keypair, pub_pk, did_keypair, did_pk


@pytest.fixture
def authenticated_entity(grpc_stub):
    """Fixture to authenticate an entity using gRPC."""

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


def test_gmail_publishing(
    authenticated_entity,
    keypairs,
    tmp_path,
    send_message,
    credentials,
    messages,
):
    """Tests the Gmail publishing functionality."""
    pub_keypair, pub_pk, _, did_pk = keypairs
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

    print(">>>>>>", res)
    if not res.requires_ownership_proof:
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
        shared_key = pub_keypair.agree(server_pub_key)
    except Exception as e:
        pytest.fail(f"Key agreement failed: {str(e)}")

    keystore_path = tmp_path / "state.db"

    gmail_message = messages["gmail_message"]
    try:
        encrypted_payload = encrypt_message(
            gmail_message, shared_key, server_pub_key, keystore_path
        )
    except Exception as e:
        pytest.fail(f"Message encryption failed: {str(e)}")

    try:
        encoded_payload = create_payload(encrypted_payload)
    except Exception as e:
        pytest.fail(f"Payload creation failed: {str(e)}")

    response = send_message(phone_number, encoded_payload)
    assert (
        response.status_code == 200
    ), f"Expected status code 200, got {response.status_code}"
