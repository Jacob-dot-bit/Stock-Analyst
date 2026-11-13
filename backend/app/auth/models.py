"""Tables for the login: the one account, browser sessions, service tokens.

Secrets are never stored as given: the password is a scrypt hash, session and
service tokens are SHA-256 hashes (they are random 256-bit values, so a fast
hash is enough). Only the TOTP secret is stored as is, because the server needs
it to compute the expected code.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AuthAccount(Base):
    """The single user of this instance. At most one row."""

    __tablename__ = "auth_account"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64))
    password_hash: Mapped[str] = mapped_column(String(255))
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Time step of the last accepted code: a code is never accepted twice.
    totp_last_step: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AuthSession(Base):
    """A browser logged in. The cookie holds the token, this row its hash."""

    __tablename__ = "auth_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuthServiceToken(Base):
    """A script allowed to call the API without a browser session.

    ``scope`` is ``read`` (GET and HEAD only) or ``write`` (everything).
    """

    __tablename__ = "auth_service_tokens"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scope: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
