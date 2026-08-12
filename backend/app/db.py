"""Connexion SQLite locale et session SQLAlchemy."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()

engine = create_engine(
    settings.database_url,
    # check_same_thread : nécessaire car FastAPI sert les requêtes sur plusieurs threads
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """Dépendance FastAPI fournissant une session par requête."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Crée les tables manquantes. Suffisant pour une base locale mono-utilisateur."""
    from app import models  # noqa: F401  (import nécessaire pour enregistrer les modèles)

    Base.metadata.create_all(bind=engine)
