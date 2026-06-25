# SPDX-License-Identifier: GPL-3.0-only
"""Server identity keys initialization on application startup."""

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError

from db import get_session
from logutils import get_logger
from models.server_identity_key import ServerIdentityKey

logger = get_logger(__name__)


def initialize_server_identity_keys(count: int = 256) -> None:
    """Generate and store server identity keys on first startup."""
    with get_session() as s:
        existing = s.scalar(select(func.count(ServerIdentityKey.id)))
        if existing > 0:
            logger.info(
                "Server identity keys already exist (%d keys), skipping", existing
            )
            return

        logger.info("Generating %d server identity keys ...", count)
        try:
            keypairs = [X25519PrivateKey.generate() for _ in range(count)]
            s.execute(
                insert(ServerIdentityKey),
                [
                    {
                        "key_index": i,
                        "private_key": kp.private_bytes_raw(),
                        "public_key": kp.public_key().public_bytes_raw(),
                    }
                    for i, kp in enumerate(keypairs)
                ],
            )
            logger.info(
                "Successfully generated and stored %d server identity keys", count
            )
        except IntegrityError:
            logger.info(
                "Server identity keys already created by another process, skipping"
            )
        except Exception as e:
            logger.error("Failed to generate server identity keys: %s", e)
            raise
