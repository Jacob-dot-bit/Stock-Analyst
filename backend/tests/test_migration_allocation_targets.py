"""The migration that folds `allocation_targets` into
`personal_policy_limits` (DEVLOG "Step 3u.101"): every target is copied, and
a category limit set by hand keeps its own bounds."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from app.config import get_settings

BACKEND = Path(__file__).resolve().parent.parent


def _config(db_path: Path) -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return config


@pytest.fixture(autouse=True)
def _fresh_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_targets_move_into_policy_limits(tmp_path, monkeypatch):
    db_path = tmp_path / "app.db"
    # alembic/env.py takes the URL from the app settings, which are cached.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    config = _config(db_path)
    command.upgrade(config, "8f3a6c1d2e54")

    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO allocation_targets (category, min_pct, max_pct) VALUES (?, ?, ?)",
            [("ETF", 20.0, 30.0), ("STOCK", 40.0, 70.0)],
        )
        conn.execute(
            "INSERT INTO personal_policy_limits (dimension, target, min_pct, max_pct) "
            "VALUES ('category', 'STOCK', NULL, 60.0)"
        )

    command.upgrade(config, "c4d8e2a7f190")

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT target, min_pct, max_pct FROM personal_policy_limits "
            "WHERE dimension = 'category' ORDER BY target"
        ).fetchall()
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    # STOCK: the hand-set max wins, the missing min comes from the target.
    assert rows == [("ETF", 20.0, 30.0), ("STOCK", 40.0, 60.0)]
    assert "allocation_targets" not in tables
