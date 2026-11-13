"""Login, sessions and service tokens.

Everything here takes the SQLAlchemy session it works on, so the API and the
command line (``python -m app.auth``) share the same code and tests can run it
on an in-memory database.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth import passwords, totp
from app.auth.models import AuthAccount, AuthServiceToken, AuthSession
from app.config import get_settings

SCOPES = ("read", "write")
READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

#: A session's last visit is written at most this often, so browsing doesn't
#: turn every request into a database write.
_TOUCH_EVERY = timedelta(minutes=10)


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    """SQLite hands datetimes back without their timezone; they are all UTC."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# --- The account -------------------------------------------------------------


def get_account(db: Session) -> AuthAccount | None:
    return db.scalars(select(AuthAccount).order_by(AuthAccount.id)).first()


def set_password(db: Session, username: str, password: str) -> AuthAccount:
    """Create the account or change its name and password.

    Every open session is closed: a password change must log out a browser
    that may have been left logged in somewhere.
    """
    if len(password) < passwords.MIN_PASSWORD_LENGTH:
        raise ValueError(f"password must be at least {passwords.MIN_PASSWORD_LENGTH} characters")
    username = username.strip()
    if not username:
        raise ValueError("username must not be empty")
    account = get_account(db)
    if account is None:
        account = AuthAccount(username=username, password_hash="")
        db.add(account)
    account.username = username
    account.password_hash = passwords.hash_password(password)
    account.failed_attempts = 0
    account.locked_until = None
    account.updated_at = _now()
    db.execute(delete(AuthSession))
    db.commit()
    return account


def start_totp(db: Session) -> str:
    """Give the account a new TOTP secret, not yet required at login.

    ``confirm_totp`` turns it on once a code from the app has been checked, so
    a mistyped secret can't lock the user out.
    """
    account = get_account(db)
    if account is None:
        raise ValueError("set a password first")
    account.totp_secret = totp.new_secret()
    account.totp_enabled = False
    account.totp_last_step = None
    db.commit()
    return account.totp_secret


def confirm_totp(db: Session, code: str) -> bool:
    account = get_account(db)
    if account is None or not account.totp_secret:
        return False
    step = totp.matching_step(account.totp_secret, code)
    if step is None:
        return False
    account.totp_enabled = True
    account.totp_last_step = step
    db.execute(delete(AuthSession))
    db.commit()
    return True


def disable_totp(db: Session) -> None:
    account = get_account(db)
    if account is not None:
        account.totp_enabled = False
        account.totp_secret = None
        account.totp_last_step = None
        db.commit()


# --- Login -------------------------------------------------------------------


class LoginError(Exception):
    """A refused login. ``code`` is a message code for the client."""

    def __init__(self, code: str, retry_after: int | None = None):
        super().__init__(code)
        self.code = code
        self.retry_after = retry_after


INVALID_CREDENTIALS = "auth.invalidCredentials"
TOTP_REQUIRED = "auth.totpRequired"
LOCKED = "auth.locked"
NOT_CONFIGURED = "auth.notConfigured"


def _register_failure(db: Session, account: AuthAccount) -> None:
    settings = get_settings()
    account.failed_attempts = (account.failed_attempts or 0) + 1
    if account.failed_attempts >= settings.auth_max_failures:
        account.locked_until = _now() + timedelta(minutes=settings.auth_lockout_minutes)
        account.failed_attempts = 0
    db.commit()


def login(db: Session, username: str, password: str, code: str | None) -> str:
    """Check the credentials and open a session. Returns the session token.

    Raises ``LoginError``. A wrong name, a wrong password and a wrong code all
    give the same answer and all count towards the lockout. A right password
    without a code (TOTP on) only asks for the code and counts nothing.
    """
    account = get_account(db)
    if account is None:
        raise LoginError(NOT_CONFIGURED)

    locked_until = _aware(account.locked_until)
    if locked_until is not None and locked_until > _now():
        raise LoginError(LOCKED, retry_after=int((locked_until - _now()).total_seconds()) + 1)

    name_ok = secrets.compare_digest(username.strip().encode(), account.username.encode())
    password_ok = passwords.verify_password(password, account.password_hash)
    if not (name_ok and password_ok):
        _register_failure(db, account)
        raise LoginError(INVALID_CREDENTIALS)

    if account.totp_enabled and account.totp_secret:
        if not code:
            raise LoginError(TOTP_REQUIRED)
        step = totp.matching_step(account.totp_secret, code)
        if step is None or (account.totp_last_step is not None and step <= account.totp_last_step):
            _register_failure(db, account)
            raise LoginError(INVALID_CREDENTIALS)
        account.totp_last_step = step

    account.failed_attempts = 0
    account.locked_until = None
    return _open_session(db)


def _open_session(db: Session) -> str:
    settings = get_settings()
    token = secrets.token_urlsafe(32)
    now = _now()
    db.add(
        AuthSession(
            token_hash=_hash_token(token),
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(days=settings.auth_session_max_days),
        )
    )
    db.commit()
    return token


def check_session(db: Session, token: str | None) -> bool:
    """True if ``token`` is a live session; refreshes its last visit."""
    if not token:
        return False
    session = db.get(AuthSession, _hash_token(token))
    if session is None:
        return False
    now = _now()
    idle_limit = timedelta(days=get_settings().auth_session_idle_days)
    last_seen = _aware(session.last_seen_at)
    if _aware(session.expires_at) <= now or last_seen + idle_limit <= now:
        db.delete(session)
        db.commit()
        return False
    if now - last_seen >= _TOUCH_EVERY:
        session.last_seen_at = now
        db.commit()
    return True


def logout(db: Session, token: str | None) -> None:
    if token:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == _hash_token(token)))
        db.commit()


def logout_everywhere(db: Session) -> int:
    count = db.execute(delete(AuthSession)).rowcount or 0
    db.commit()
    return count


# --- Service tokens ----------------------------------------------------------


@dataclass(frozen=True)
class ServiceCaller:
    name: str
    scope: str

    def allows(self, method: str) -> bool:
        return self.scope == "write" or method.upper() in READ_METHODS


def add_service_token(db: Session, name: str, scope: str) -> str:
    """Create (or replace) the token called ``name``. Returns it, once."""
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of {', '.join(SCOPES)}")
    name = name.strip()
    if not name or len(name) > 64:
        raise ValueError("name must be 1 to 64 characters")
    token = "sat_" + secrets.token_urlsafe(32)
    existing = db.get(AuthServiceToken, name)
    if existing is not None:
        db.delete(existing)
        db.flush()
    db.add(AuthServiceToken(name=name, token_hash=_hash_token(token), scope=scope, created_at=_now()))
    db.commit()
    return token


def revoke_service_token(db: Session, name: str) -> bool:
    count = db.execute(delete(AuthServiceToken).where(AuthServiceToken.name == name)).rowcount
    db.commit()
    return bool(count)


def list_service_tokens(db: Session) -> list[AuthServiceToken]:
    return list(db.scalars(select(AuthServiceToken).order_by(AuthServiceToken.name)))


def check_service_token(db: Session, token: str | None) -> ServiceCaller | None:
    if not token:
        return None
    row = db.scalars(select(AuthServiceToken).where(AuthServiceToken.token_hash == _hash_token(token))).first()
    if row is None:
        return None
    now = _now()
    last_used = _aware(row.last_used_at)
    if last_used is None or now - last_used >= _TOUCH_EVERY:
        row.last_used_at = now
        db.commit()
    return ServiceCaller(name=row.name, scope=row.scope)
