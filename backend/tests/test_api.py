"""Tests des endpoints HTTP."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app


@pytest.fixture
def client():
    # StaticPool : sans lui, chaque connexion à "sqlite://" ouvre une base
    # en mémoire distincte et les tables créées ici seraient invisibles
    # du thread qui sert les requêtes.
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


class TestHealth:
    def test_reports_disabled_integrations(self, client):
        response = client.get("/api/health")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        # L'application doit démarrer sans aucune clé API configurée.
        assert set(body["integrations"]) == {"finnhub", "edgar", "perplexity"}


class TestEmptyPortfolio:
    def test_empty_portfolio_is_valid(self, client):
        response = client.get("/api/portfolio")

        assert response.status_code == 200
        body = response.json()
        assert body["positions"] == []
        assert body["totals"]["positions_count"] == 0
        assert body["last_import_at"] is None


class TestImportEndpoint:
    def test_upload_and_read_back(self, client, xtb_export):
        response = client.post(
            "/api/imports/xtb",
            files={
                "file": (
                    "EUR_1234567.xlsx",
                    xtb_export,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        assert response.status_code == 200
        batch = response.json()
        assert batch["positions_found"] == 2
        assert batch["accounts"] == ["My Trades"]

        portfolio = client.get("/api/portfolio").json()
        totals = portfolio["totals"]

        assert len(portfolio["positions"]) == 2
        # Valeurs de marché : 1558.00 + 1312.08 ; P&L : 834.30 + 614.27.
        assert totals["market_value"] == pytest.approx(2870.08)
        assert totals["unrealized_pl"] == pytest.approx(1448.57)
        # La valeur d'achat se déduit exactement de la valeur de marché et du P&L.
        assert totals["invested_value"] == pytest.approx(1421.51)
        assert totals["has_incomplete_data"] is False

    def test_accounts_are_broken_down(self, client, xtb_export, xtb_pea_export):
        for name, content in (("EUR.xlsx", xtb_export), ("PEA.xlsx", xtb_pea_export)):
            client.post("/api/imports/xtb", files={"file": (name, content, "application/octet-stream")})

        accounts = {a["account"]: a for a in client.get("/api/portfolio").json()["accounts"]}

        assert set(accounts) == {"My Trades", "PEA"}
        assert accounts["PEA"]["market_value"] == pytest.approx(620.0)
        assert accounts["My Trades"]["positions_count"] == 2

    def test_empty_file_is_rejected(self, client):
        response = client.post("/api/imports/xtb", files={"file": ("empty.xlsx", b"", "application/octet-stream")})

        assert response.status_code == 400

    def test_unsupported_format_reports_warning_not_crash(self, client):
        response = client.post(
            "/api/imports/xtb", files={"file": ("report.pdf", b"%PDF-1.4", "application/pdf")}
        )

        assert response.status_code == 200
        assert response.json()["warnings"]


class TestManualPosition:
    def test_create_and_delete(self, client):
        created = client.post(
            "/api/portfolio/positions",
            json={"broker_symbol": "MC.FR", "quantity": 3, "avg_price": 700.0},
        )
        assert created.status_code == 201
        body = created.json()
        assert body["instrument"]["provider_symbol"] == "MC.PA"
        assert body["source"] == "MANUAL"

        deleted = client.delete(f"/api/portfolio/positions/{body['id']}")
        assert deleted.status_code == 204
        assert client.get("/api/portfolio").json()["positions"] == []

    def test_delete_unknown_position(self, client):
        assert client.delete("/api/portfolio/positions/999").status_code == 404


class TestSymbolOverride:
    def test_override_updates_instrument(self, client):
        client.post(
            "/api/portfolio/positions",
            json={"broker_symbol": "ERICB.SE", "quantity": 100, "avg_price": 60.0},
        )

        response = client.put(
            "/api/portfolio/symbol-overrides",
            json={"broker_symbol": "ERICB.SE", "provider_symbol": "ERIC-B.ST"},
        )

        assert response.status_code == 200
        assert response.json()["provider_symbol"] == "ERIC-B.ST"
        assert response.json()["mapping_status"] == "MANUAL"

    def test_override_on_unknown_symbol_is_rejected(self, client):
        response = client.put(
            "/api/portfolio/symbol-overrides",
            json={"broker_symbol": "NOPE.US", "provider_symbol": "NOPE"},
        )

        assert response.status_code == 404


class TestIncompleteData:
    """Une position sans valeurs courtier ne doit pas être comptée comme un zéro."""

    def test_totals_flag_incomplete_data(self, client):
        client.post(
            "/api/portfolio/positions",
            json={"broker_symbol": "AAPL.US", "quantity": 10, "avg_price": 185.5},
        )

        totals = client.get("/api/portfolio").json()["totals"]

        assert totals["has_incomplete_data"] is True
        assert totals["invested_value"] is None
