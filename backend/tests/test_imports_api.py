"""Tests for import preview, history, and undo. See DEVLOG "Decision 3h.1"."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import ImportBatch, Instrument, Lot, Position, Transaction
from tests.conftest import CASH_HEADERS, build_xtb_workbook


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _db(client):
    """Grab a session on the same in-memory engine the app is using."""
    return next(app.dependency_overrides[get_db]())


def _row_counts(db):
    return {
        "batches": len(db.execute(select(ImportBatch)).scalars().all()),
        "positions": len(db.execute(select(Position)).scalars().all()),
        "lots": len(db.execute(select(Lot)).scalars().all()),
        "transactions": len(db.execute(select(Transaction)).scalars().all()),
    }


def _upload(client, path, filename, content):
    return client.post(path, files={"file": (filename, content, "application/octet-stream")})


def _deposit_export(deposit_id: str, extra_id: str | None = None) -> bytes:
    """A minimal one-cash-op export, for building overlapping-import scenarios
    without depending on the full xtb_export fixture's shape."""
    rows = [
        ["Deposit", None, None, None, "2024-01-01 00:00:00", 1000.0, deposit_id, "seed", "My Trades", None],
    ]
    if extra_id:
        rows.append(
            ["Deposit", None, None, None, "2024-02-01 00:00:00", 50.0, extra_id, "extra", "My Trades", None]
        )
    return build_xtb_workbook(
        [("Cash Operations", [["Account number", 1234567]], CASH_HEADERS, rows)]
    )


class TestPreviewImport:
    def test_preview_persists_nothing(self, client, xtb_export):
        response = _upload(client, "/api/imports/xtb/preview", "a.xlsx", xtb_export)
        assert response.status_code == 200
        body = response.json()
        assert body["positions_found"] == 2
        assert "id" not in body

        db = _db(client)
        assert _row_counts(db) == {"batches": 0, "positions": 0, "lots": 0, "transactions": 0}

    def test_preview_twice_gives_identical_counts(self, client, xtb_export):
        first = _upload(client, "/api/imports/xtb/preview", "a.xlsx", xtb_export).json()
        second = _upload(client, "/api/imports/xtb/preview", "a.xlsx", xtb_export).json()
        assert first == second

    def test_preview_after_real_import_reflects_dedup(self, client, xtb_export):
        committed = _upload(client, "/api/imports/xtb", "a.xlsx", xtb_export).json()
        preview = _upload(client, "/api/imports/xtb/preview", "a.xlsx", xtb_export).json()

        assert committed["transactions_inserted"] > 0
        # Re-previewing the exact same file: everything would dedupe away.
        assert preview["transactions_inserted"] == 0
        assert preview["transactions_found"] == committed["transactions_found"]

    def test_empty_file_rejected(self, client):
        response = _upload(client, "/api/imports/xtb/preview", "a.xlsx", b"")
        assert response.status_code == 400


class TestListImports:
    def test_most_recent_first(self, client, xtb_export, xtb_pea_export):
        _upload(client, "/api/imports/xtb", "a.xlsx", xtb_export)
        _upload(client, "/api/imports/xtb", "b.xlsx", xtb_pea_export)

        body = client.get("/api/imports").json()
        assert [b["filename"] for b in body] == ["b.xlsx", "a.xlsx"]


class TestUndoImport:
    def test_undo_the_only_import(self, client, xtb_export):
        batch = _upload(client, "/api/imports/xtb", "a.xlsx", xtb_export).json()

        response = client.delete(f"/api/imports/{batch['id']}")
        assert response.status_code == 204

        db = _db(client)
        assert _row_counts(db) == {"batches": 0, "positions": 0, "lots": 0, "transactions": 0}

    def test_404_for_unknown_id(self, client):
        assert client.delete("/api/imports/999").status_code == 404

    def test_cannot_undo_an_older_import(self, client, xtb_export, xtb_pea_export):
        first = _upload(client, "/api/imports/xtb", "a.xlsx", xtb_export).json()
        _upload(client, "/api/imports/xtb", "b.xlsx", xtb_pea_export)

        db = _db(client)
        before = _row_counts(db)

        response = client.delete(f"/api/imports/{first['id']}")
        assert response.status_code == 400

        db = _db(client)
        assert _row_counts(db) == before

    def test_undoing_the_newest_import_never_deletes_a_row_an_older_import_owns(self, client):
        """The core safety regression test for the LIFO restriction: import A
        creates a Deposit transaction; import B re-sees the same external id
        (deduped, stays owned by A) plus a brand-new one. Undoing B — the
        newest — must leave A's transaction untouched and only remove B's own.
        """
        _upload(client, "/api/imports/xtb", "a.xlsx", _deposit_export("shared-1"))
        second = _upload(
            client, "/api/imports/xtb", "b.xlsx", _deposit_export("shared-1", "only-in-b")
        ).json()

        response = client.delete(f"/api/imports/{second['id']}")
        assert response.status_code == 204

        db = _db(client)
        external_ids = {
            t.external_id for t in db.execute(select(Transaction)).scalars().all()
        }
        assert external_ids == {"shared-1"}

    def test_undoing_a_position_import_leaves_the_instrument_behind(self, client, xtb_export):
        batch = _upload(client, "/api/imports/xtb", "a.xlsx", xtb_export).json()

        client.delete(f"/api/imports/{batch['id']}")

        db = _db(client)
        assert db.execute(select(Position)).scalars().all() == []
        assert len(db.execute(select(Instrument)).scalars().all()) > 0
