# SPDX-License-Identifier: GPL-3.0-only
"""Server identity keys initialization on application startup."""

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from sqlalchemy.exc import IntegrityError, OperationalError

from db import get_session
from logutils import get_logger
from models.server_identity_key import ServerIdentityKey, count_keys

logger = get_logger(__name__)


def generate_server_identity_keys(count: int = 256) -> None:
    """Generate and store server identity keys on first startup.

    Args:
        count: Number of keys to generate (default: 256, range 0-255)
    """
    with get_session() as session:
        existing_count = count_keys(session=session)

        if existing_count > 0:
            logger.info(
                f"Server identity keys already exist ({existing_count} keys), skipping generation"
            )
            return

        logger.info(f"Generating {count} server identity keys...")

        keypairs = [
            (key_index, X25519PrivateKey.generate()) for key_index in range(count)
        ]

        keys_to_insert = [
            ServerIdentityKey(
                key_index=key_index,
                private_key=private_key_obj.private_bytes_raw(),
                public_key=private_key_obj.public_key().public_bytes_raw(),
            )
            for key_index, private_key_obj in keypairs
        ]

        try:
            session.bulk_save_objects(keys_to_insert)
            session.commit()
            logger.info(
                f"Successfully generated and stored {count} server identity keys"
            )
        except (IntegrityError, OperationalError) as e:
            session.rollback()
            logger.info(
                "Server identity keys were created by another process, skipping"
            )
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to generate server identity keys: {e}")
            raise


def initialize_server_identity_keys() -> None:
    """Generate server identity keys if they don't exist."""
    generate_server_identity_keys()
