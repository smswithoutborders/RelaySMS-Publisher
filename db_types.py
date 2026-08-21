# SPDX-License-Identifier: GPL-3.0-only
"""Custom SQLAlchemy column types."""

import json

from sqlalchemy import LargeBinary, Text, TypeDecorator

from crypto import get_encryption_algorithm
from utils import get_configs, get_logger

logger = get_logger(__name__)


class EncryptedJSON(TypeDecorator):
    """Encrypted JSON type using configurable encryption algorithm."""

    impl = Text
    cache_ok = True

    def __init__(self, algorithm: str = "aes-256-gcm"):
        super().__init__()
        self._encryption_enabled = (
            get_configs(
                "DATABASE_FIELD_ENCRYPTION_ENABLED", default_value="false"
            ).lower()
            == "true"
        )
        self._key = None
        self._encrypt_func = None
        self._decrypt_func = None

        if self._encryption_enabled:
            key_hex = get_configs("DATABASE_FIELD_ENCRYPTION_KEY")
            if not key_hex:
                raise ValueError(
                    "DATABASE_FIELD_ENCRYPTION_KEY required when encryption enabled"
                )

            try:
                self._key = bytes.fromhex(key_hex)
                if len(self._key) != 32:
                    raise ValueError(
                        "DATABASE_FIELD_ENCRYPTION_KEY must be 32 bytes (64 hex chars)"
                    )
            except ValueError as e:
                raise ValueError(f"Invalid DATABASE_FIELD_ENCRYPTION_KEY: {e}")

            self._encrypt_func, self._decrypt_func = get_encryption_algorithm(algorithm)

    def process_bind_param(self, value, dialect):
        """Encrypt JSON before storing."""
        if value is None:
            return None

        json_str = json.dumps(value)

        if not self._encryption_enabled or not self._key:
            return json_str

        ciphertext = self._encrypt_func(self._key, json_str.encode())
        return ciphertext.hex()

    def process_result_value(self, value, dialect):
        """Decrypt JSON after retrieving."""
        if value is None:
            return None

        if not self._encryption_enabled or not self._key:
            return json.loads(value)

        data = bytes.fromhex(value)
        plaintext = self._decrypt_func(self._key, data)
        return json.loads(plaintext.decode())


class PrivateEncryptedBinary(TypeDecorator):
    """
    Mandatory encrypted binary type for private keys.
    Uses DATA_ENCRYPTION_KEY regardless of other encryption settings.
    """

    impl = LargeBinary
    cache_ok = True

    def __init__(self, algorithm: str = "aes-256-gcm"):
        super().__init__()
        key_hex = get_configs("DATA_ENCRYPTION_KEY")
        if not key_hex:
            raise ValueError("DATA_ENCRYPTION_KEY required for PrivateEncryptedBinary")

        try:
            self._key = bytes.fromhex(key_hex)
            if len(self._key) != 32:
                raise ValueError("DATA_ENCRYPTION_KEY must be 32 bytes (64 hex chars)")
        except ValueError as e:
            raise ValueError(f"Invalid DATA_ENCRYPTION_KEY: {e}")

        self._encrypt_func, self._decrypt_func = get_encryption_algorithm(algorithm)

    def process_bind_param(self, value, dialect):
        """Encrypt binary data before storing."""
        if value is None:
            return None
        return self._encrypt_func(self._key, value)

    def process_result_value(self, value, dialect):
        """Decrypt binary data after retrieving."""
        if value is None:
            return None
        return self._decrypt_func(self._key, value)
