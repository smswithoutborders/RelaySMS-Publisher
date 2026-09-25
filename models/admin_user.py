# SPDX-License-Identifier: GPL-3.0-only
"""AdminUser model and related functions."""

import datetime
import re
import secrets
from functools import lru_cache
from typing import TYPE_CHECKING, List, Optional

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import Index, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from db import Base
from db_types import UTCDateTime, utc_now
from models.admin_session import revoke_all

if TYPE_CHECKING:
    from models import AdminSession

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MAX_EMAIL_LENGTH = 254

password_hasher = PasswordHasher()


class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(_MAX_EMAIL_LENGTH))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(UTCDateTime, default=utc_now)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        UTCDateTime, default=utc_now, onupdate=utc_now
    )
    last_login_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        UTCDateTime, default=None
    )

    sessions: Mapped[List["AdminSession"]] = relationship(
        "AdminSession", back_populates="admin_user", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("uq_admin_users_email", "email", unique=True),)


class AdminUserExistsError(ValueError):
    pass


class AdminUserNotFoundError(ValueError):
    pass


def _normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if len(normalized) > _MAX_EMAIL_LENGTH or not _EMAIL_PATTERN.match(normalized):
        raise ValueError(f"Invalid email address: {email!r}")
    return normalized


def _generate_password() -> str:
    return secrets.token_urlsafe(24)


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return password_hasher.hash(_generate_password())


def get_by_email(session: Session, email: str) -> Optional[AdminUser]:
    return session.scalars(
        select(AdminUser).filter_by(email=email.strip().lower())
    ).first()


def get_or_raise(session: Session, email: str) -> AdminUser:
    admin = get_by_email(session, email)
    if admin is None:
        raise AdminUserNotFoundError(f"No admin user with email {email!r}")
    return admin


def list_admins(session: Session) -> List[AdminUser]:
    return list(session.scalars(select(AdminUser).order_by(AdminUser.email)))


def create_admin(session: Session, email: str) -> tuple[AdminUser, str]:
    email = _normalize_email(email)
    if get_by_email(session, email) is not None:
        raise AdminUserExistsError(f"Admin user {email!r} already exists")

    password = _generate_password()
    admin = AdminUser(email=email, password_hash=password_hasher.hash(password))
    session.add(admin)
    session.flush()
    return admin, password


def reset_password(session: Session, email: str) -> tuple[AdminUser, str]:
    admin = get_or_raise(session, email)
    password = _generate_password()
    admin.password_hash = password_hasher.hash(password)
    revoke_all(session, admin.id)
    return admin, password


def set_active(session: Session, email: str, active: bool) -> AdminUser:
    admin = get_or_raise(session, email)
    admin.is_active = active
    if not active:
        revoke_all(session, admin.id)
    session.flush()
    return admin


def delete_admin(session: Session, email: str) -> None:
    session.delete(get_or_raise(session, email))
    session.flush()


def verify_credentials(
    session: Session, email: str, password: str
) -> Optional[AdminUser]:
    admin = get_by_email(session, email)
    if admin is None:
        # Hash anyway so response timing doesn't reveal which emails exist.
        try:
            password_hasher.verify(_dummy_hash(), password)
        except VerificationError:
            pass
        return None

    try:
        password_hasher.verify(admin.password_hash, password)
    except (VerificationError, InvalidHashError):
        return None

    if not admin.is_active:
        return None

    if password_hasher.check_needs_rehash(admin.password_hash):
        admin.password_hash = password_hasher.hash(password)
    return admin


def record_login(admin: AdminUser, *, min_interval_seconds: int = 0) -> None:
    now = utc_now()
    last = admin.last_login_at
    if last is None or (now - last).total_seconds() >= min_interval_seconds:
        admin.last_login_at = now
