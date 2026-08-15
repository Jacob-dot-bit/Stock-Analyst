"""Local SQLite connection and SQLAlchemy session."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import BACKEND_DIR, get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()

engine = create_engine(
    settings.database_url,
    # check_same_thread: required because FastAPI serves requests across threads.
    # timeout: how long SQLite waits for a writer lock before raising "database is
    # locked" — the DBAPI default (5s) is tight now that a price refresh commits
    # from several worker threads at once (DEVLOG "Decision 3n.1"); widened to give
    # concurrent commits room to queue instead of failing.
    connect_args=(
        {"check_same_thread": False, "timeout": 30}
        if settings.database_url.startswith("sqlite")
        else {}
    ),
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency providing one session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Bring the schema up to date via Alembic (see `backend/alembic/`).

    Supersedes a raw `Base.metadata.create_all`: that only ever adds tables
    that don't exist yet, so it can't apply a schema change to a table that's
    already there. A brand-new install has no `alembic_version` row, so this
    applies every migration starting from the baseline (which itself creates
    every table) — same end result `create_all` used to give a fresh
    database. An existing database just picks up whatever has landed since it
    was last stamped.
    """
    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")

    # Real holdings and transaction history live here — restrict it to the owning
    # user, same posture as the .env API-key file (see config.py's get_settings()).
    # Only meaningful for a real on-disk file; an in-memory test database has none.
    if settings.database_url.startswith("sqlite:///"):
        db_path = Path(settings.database_url.removeprefix("sqlite:///"))
        if db_path.exists():
            db_path.chmod(0o600)
