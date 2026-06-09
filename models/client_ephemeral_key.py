# SPDX-License-Identifier: GPL-3.0-only
"""Client ephemeral key model and related functions."""

import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    UniqueConstraint,
)
from sqlalchemy.orm import Session, relationship

from db import Base, get_session


def utc_now() -> datetime.datetime:
    """Get current UTC datetime."""
    return datetime.datetime.now(datetime.timezone.utc)


class ClientEphemeralKey(Base):
    """Client Ephemeral Key Model."""

    __tablename__ = "client_ephemeral_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    token_hash_id = Column(
        Integer, ForeignKey("token_hashes.id", ondelete="CASCADE"), nullable=False
    )
    key_index = Column(Integer, nullable=False)
    public_key = Column(LargeBinary(32), nullable=False)
    used = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    used_at = Column(DateTime, nullable=True)

    token_hash = relationship("TokenHash", back_populates="client_keys")

    __table_args__ = (
        UniqueConstraint(
            "token_hash_id", "key_index", name="uq_client_keys_token_hash_id_key_index"
        ),
        Index("ix_client_ephemeral_keys_token_hash_id_used", "token_hash_id", "used"),
    )


def bulk_upload_keys(
    token_hash_id: int, public_keys: List[bytes], session: Optional[Session] = None
) -> int:
    """Upload multiple public keys."""
    from models.token_hash import TokenHash

    def _upload(s: Session):
        token_hash = s.query(TokenHash).filter(TokenHash.id == token_hash_id).first()
        if not token_hash:
            raise ValueError(f"TokenHash with id {token_hash_id} not found")

        for idx, key in enumerate(public_keys):
            if len(key) != 32:
                raise ValueError(f"Key at index {idx} must be 32 bytes, got {len(key)}")

        client_keys = [
            ClientEphemeralKey(
                token_hash_id=token_hash_id,
                key_index=idx,
                public_key=public_key,
                used=False,
            )
            for idx, public_key in enumerate(public_keys)
        ]

        s.bulk_save_objects(client_keys)
        s.flush()
        return len(client_keys)

    if session:
        return _upload(session)

    with get_session() as s:
        return _upload(s)


def mark_as_used(key_id: int, session: Optional[Session] = None) -> int:
    """Mark key as used."""

    def _update(s: Session):
        return (
            s.query(ClientEphemeralKey)
            .filter(ClientEphemeralKey.id == key_id)
            .update({"used": True, "used_at": utc_now()}, synchronize_session=False)
        )

    if session:
        rows = _update(session)
        session.flush()
        return rows

    with get_session() as s:
        return _update(s)


def get_by_index(
    token_hash_id: int, key_index: int, session: Optional[Session] = None
) -> Optional[ClientEphemeralKey]:
    """Get key by index."""
    if session:
        return (
            session.query(ClientEphemeralKey)
            .filter(
                ClientEphemeralKey.token_hash_id == token_hash_id,
                ClientEphemeralKey.key_index == key_index,
            )
            .first()
        )

    with get_session() as s:
        return (
            s.query(ClientEphemeralKey)
            .filter(
                ClientEphemeralKey.token_hash_id == token_hash_id,
                ClientEphemeralKey.key_index == key_index,
            )
            .first()
        )


def delete_all_for_token_hash(
    token_hash_id: int, session: Optional[Session] = None
) -> int:
    """Delete all keys for token hash. Returns rows deleted."""

    def _delete(s: Session):
        return (
            s.query(ClientEphemeralKey)
            .filter(ClientEphemeralKey.token_hash_id == token_hash_id)
            .delete(synchronize_session=False)
        )

    if session:
        rows = _delete(session)
        session.flush()
        return rows

    with get_session() as s:
        return _delete(s)
