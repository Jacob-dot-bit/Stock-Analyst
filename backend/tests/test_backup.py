"""Tests for backup/restore of the local SQLite database.

Runs entirely against temp files — `BACKUP_DIR`, `get_settings`, and
`engine` are all monkeypatched so nothing here ever touches this
developer's real `data/stock_analyst.db` or its own test-suite database.
"""

from __future__ import annotations

import shutil
import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.backup import service as backup_service
from app.main import app


def _make_sqlite_db(path: Path, version: str = "abc123") -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
    conn.execute("INSERT INTO alembic_version VALUES (?)", (version,))
    conn.execute("CREATE TABLE positions (id INTEGER PRIMARY KEY, quantity REAL)")
    conn.execute("INSERT INTO positions (quantity) VALUES (42.0)")
    conn.commit()
    conn.close()


@pytest.fixture
def live_db(tmp_path, monkeypatch):
    db_path = tmp_path / "live.db"
    _make_sqlite_db(db_path)

    backup_dir = tmp_path / "backups"

    class FakeSettings:
        database_url = f"sqlite:///{db_path}"

    monkeypatch.setattr(backup_service, "BACKUP_DIR", backup_dir)
    monkeypatch.setattr(backup_service, "get_settings", lambda: FakeSettings())

    class FakeEngine:
        disposed = False

        def dispose(self):
            self.disposed = True

    fake_engine = FakeEngine()
    monkeypatch.setattr(backup_service, "engine", fake_engine)

    return db_path, backup_dir, fake_engine


class TestCreateBackup:
    def test_creates_a_timestamped_copy(self, live_db):
        db_path, backup_dir, _ = live_db
        info = backup_service.create_backup()

        assert (backup_dir / info.filename).exists()
        assert info.filename.startswith("stock_analyst_")
        assert info.size_bytes == db_path.stat().st_size

    def test_backup_content_matches_live_db(self, live_db):
        db_path, backup_dir, _ = live_db
        info = backup_service.create_backup()

        conn = sqlite3.connect(backup_dir / info.filename)
        row = conn.execute("SELECT quantity FROM positions").fetchone()
        conn.close()
        assert row == (42.0,)

    def test_prunes_beyond_max_backups(self, live_db, monkeypatch):
        monkeypatch.setattr(backup_service, "MAX_BACKUPS", 3)
        for _ in range(5):
            backup_service.create_backup()
            time.sleep(0.01)  # distinct mtimes/filenames

        remaining = backup_service.list_backups()
        assert len(remaining) == 3

    def test_never_touches_env_file(self, live_db, tmp_path):
        """A backup is a copy of the .db file only — nothing else is ever
        read or written by create_backup, so a nearby .env is untouched."""
        env_file = tmp_path / ".env"
        env_file.write_text("SOME_API_KEY=secret")

        backup_service.create_backup()

        assert env_file.read_text() == "SOME_API_KEY=secret"


class TestListBackups:
    def test_empty_when_no_backups_exist(self, live_db):
        assert backup_service.list_backups() == []

    def test_newest_first(self, live_db):
        first = backup_service.create_backup()
        time.sleep(0.01)
        second = backup_service.create_backup()

        listed = backup_service.list_backups()
        assert [b.filename for b in listed] == [second.filename, first.filename]


class TestRestoreBackup:
    def test_restores_content_and_disposes_engine(self, live_db):
        db_path, backup_dir, fake_engine = live_db
        info = backup_service.create_backup()

        # Mutate the "live" db after the backup was taken.
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE positions SET quantity = 999")
        conn.commit()
        conn.close()

        backup_service.restore_backup(info.filename)

        assert fake_engine.disposed is True
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT quantity FROM positions").fetchone()
        conn.close()
        assert row == (42.0,)

    def test_rejects_unknown_filename(self, live_db):
        with pytest.raises(backup_service.BackupNotFoundError):
            backup_service.restore_backup("does-not-exist.db")

    def test_rejects_path_traversal(self, live_db, tmp_path):
        outside = tmp_path / "outside.db"
        outside.write_text("not a real db")
        with pytest.raises(backup_service.BackupNotFoundError):
            backup_service.restore_backup("../outside.db")

    def test_rejects_schema_version_mismatch(self, live_db, tmp_path):
        db_path, backup_dir, _ = live_db
        backup_dir.mkdir(parents=True, exist_ok=True)
        mismatched = backup_dir / "stock_analyst_old.db"
        _make_sqlite_db(mismatched, version="old999")

        with pytest.raises(backup_service.SchemaMismatchError):
            backup_service.restore_backup(mismatched.name)

        # The live db must be untouched after a rejected restore.
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        conn.close()
        assert row == ("abc123",)

    def test_matching_schema_version_is_accepted(self, live_db):
        db_path, backup_dir, _ = live_db
        info = backup_service.create_backup()
        backup_service.restore_backup(info.filename)  # must not raise


class TestBackupApi:
    def test_create_and_list_endpoints(self, live_db):
        with TestClient(app) as client:
            created = client.post("/api/backup")
            assert created.status_code == 201
            body = created.json()
            assert body["filename"].startswith("stock_analyst_")

            listed = client.get("/api/backup")
            assert listed.status_code == 200
            assert len(listed.json()) == 1
            assert listed.json()[0]["filename"] == body["filename"]

    def test_restore_endpoint_404_for_unknown_backup(self, live_db):
        with TestClient(app) as client:
            response = client.post("/api/backup/nope.db/restore")
            assert response.status_code == 404

    def test_restore_endpoint_409_for_schema_mismatch(self, live_db):
        db_path, backup_dir, _ = live_db
        backup_dir.mkdir(parents=True, exist_ok=True)
        mismatched = backup_dir / "stock_analyst_old.db"
        _make_sqlite_db(mismatched, version="old999")

        with TestClient(app) as client:
            response = client.post(f"/api/backup/{mismatched.name}/restore")
            assert response.status_code == 409
