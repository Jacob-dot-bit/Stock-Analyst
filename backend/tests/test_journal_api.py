"""End-to-end tests for the decision-journal endpoints
(`POST/GET /api/journal`, `PATCH /api/journal/{id}`,
`PATCH /api/journal/{id}/outcome`, `DELETE /api/journal/{id}`).

An entry is user-written reasoning, optionally tied to one instrument —
never computed or scored. See DEVLOG "Decision 3u.68".
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Instrument, JournalEntry


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
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


def _db_session():
    return next(app.dependency_overrides[get_db]())


class TestAddJournalEntry:
    def test_with_a_symbol_creates_the_instrument_and_the_entry(self, client):
        response = client.post("/api/journal", json={"broker_symbol": "AAA.US", "thesis": "Undervalued vs peers."})

        assert response.status_code == 201
        body = response.json()
        assert body["instrument"]["broker_symbol"] == "AAA.US"
        assert body["thesis"] == "Undervalued vs peers."
        assert body["entry_date"] == date.today().isoformat()
        assert body["review_date"] is None
        assert body["outcome_note"] is None

    def test_with_no_symbol_creates_an_instrument_less_entry(self, client):
        response = client.post("/api/journal", json={"thesis": "Staying cautious given macro conditions."})

        assert response.status_code == 201
        assert response.json()["instrument"] is None

    def test_a_blank_thesis_is_rejected(self, client):
        response = client.post("/api/journal", json={"thesis": ""})

        assert response.status_code == 422

    def test_a_missing_thesis_is_rejected(self, client):
        response = client.post("/api/journal", json={"broker_symbol": "AAA.US"})

        assert response.status_code == 422

    def test_entry_date_is_always_today_even_if_the_client_sends_one(self, client):
        response = client.post(
            "/api/journal", json={"thesis": "Test.", "entry_date": "2000-01-01"}
        )

        assert response.json()["entry_date"] == date.today().isoformat()

    def test_review_date_is_stored_when_given(self, client):
        response = client.post("/api/journal", json={"thesis": "Test.", "review_date": "2027-01-01"})

        assert response.json()["review_date"] == "2027-01-01"


class TestListJournalEntries:
    def test_newest_entry_date_first(self, client):
        session = _db_session()
        try:
            session.add_all(
                [
                    JournalEntry(thesis="Older", entry_date=date(2026, 1, 1)),
                    JournalEntry(thesis="Newer", entry_date=date(2026, 6, 1)),
                    JournalEntry(thesis="Newest", entry_date=date(2026, 9, 1)),
                ]
            )
            session.commit()
        finally:
            session.close()

        body = client.get("/api/journal").json()

        assert [row["thesis"] for row in body] == ["Newest", "Newer", "Older"]

    def test_empty_when_nothing_written(self, client):
        assert client.get("/api/journal").json() == []


class TestUpdateJournalEntry:
    def test_updates_thesis_and_review_date(self, client):
        entry_id = client.post("/api/journal", json={"thesis": "Original."}).json()["id"]

        response = client.patch(
            f"/api/journal/{entry_id}", json={"thesis": "Revised after reflection.", "review_date": "2027-03-01"}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["thesis"] == "Revised after reflection."
        assert body["review_date"] == "2027-03-01"

    def test_entry_date_cannot_be_changed_via_update(self, client):
        entry_id = client.post("/api/journal", json={"thesis": "Original."}).json()["id"]
        original_entry_date = date.today().isoformat()

        response = client.patch(
            f"/api/journal/{entry_id}", json={"thesis": "Revised.", "entry_date": "2000-01-01"}
        )

        assert response.json()["entry_date"] == original_entry_date

    def test_404_for_an_unknown_entry(self, client):
        response = client.patch("/api/journal/999", json={"thesis": "Revised."})

        assert response.status_code == 404


class TestJournalEntryOutcome:
    def test_sets_outcome_without_touching_thesis_or_review_date(self, client):
        entry_id = client.post(
            "/api/journal", json={"thesis": "Original thesis.", "review_date": "2027-01-01"}
        ).json()["id"]

        response = client.patch(f"/api/journal/{entry_id}/outcome", json={"outcome_note": "Thesis played out."})

        assert response.status_code == 200
        body = response.json()
        assert body["outcome_note"] == "Thesis played out."
        assert body["thesis"] == "Original thesis."
        assert body["review_date"] == "2027-01-01"

    def test_404_for_an_unknown_entry(self, client):
        response = client.patch("/api/journal/999/outcome", json={"outcome_note": "Note."})

        assert response.status_code == 404


class TestDeleteJournalEntry:
    def test_removes_the_entry(self, client):
        entry_id = client.post("/api/journal", json={"thesis": "Test."}).json()["id"]

        response = client.delete(f"/api/journal/{entry_id}")

        assert response.status_code == 204
        assert client.get("/api/journal").json() == []

    def test_deleting_the_referenced_instrument_does_not_cascade(self, client):
        entry_id = client.post("/api/journal", json={"broker_symbol": "AAA.US", "thesis": "Test."}).json()["id"]

        session = _db_session()
        try:
            instrument = session.query(Instrument).filter_by(broker_symbol="AAA.US").one()
            session.delete(instrument)
            session.commit()
        finally:
            session.close()

        response = client.get("/api/journal")

        assert response.status_code == 200
        # The FK survives with a now-dangling instrument_id — never
        # silently deletes real journal history because an instrument
        # went away, same guarantee `Lot.instrument_id` already gives.
        assert len(response.json()) == 1

    def test_404_for_an_unknown_entry(self, client):
        response = client.delete("/api/journal/999")

        assert response.status_code == 404
