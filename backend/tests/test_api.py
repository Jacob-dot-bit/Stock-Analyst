"""Tests for the HTTP endpoints."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Instrument, Position


@pytest.fixture
def client():
    # StaticPool: without it every connection to "sqlite://" opens a separate
    # in-memory database, and the tables created here would be invisible to the
    # thread serving the requests.
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
        # Shape only: which integrations exist grows over time, and whether each is
        # enabled is config loading, covered properly in test_config.py.
        assert body["integrations"]
        assert all(isinstance(enabled, bool) for enabled in body["integrations"].values())
        # The .env locations searched are reported, so "why is my key not read" has a
        # one-request answer.
        assert body["env_files"]


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
        # Market values: 1558.00 + 1312.08; P&L: 834.30 + 614.27.
        assert totals["market_value"] == pytest.approx(2870.08)
        assert totals["unrealized_pl"] == pytest.approx(1448.57)
        # Purchase value follows exactly from market value and P&L.
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

    def test_sections_describe_each_sheet(self, client, xtb_export):
        response = client.post(
            "/api/imports/xtb",
            files={"file": ("EUR_1234567.xlsx", xtb_export, "application/octet-stream")},
        )

        sections = {s["kind"]: s for s in response.json()["sections"]}
        assert set(sections) == {"open_positions", "closed_positions", "cash_operations"}
        # Two holdings, but five rows in the sheet: the lots are visible in source_rows.
        assert sections["open_positions"]["count"] == 2
        assert sections["open_positions"]["source_rows"] == 5


class TestLanguageNeutrality:
    """The API must never return prose: the client owns the wording.

    Without this guarantee, a French message reaching a Polish or English user could
    not be translated by any amount of frontend work — the meaning is lost as soon as
    the backend commits to one language.
    """

    def test_warnings_are_codes_with_parameters(self, client):
        response = client.post(
            "/api/imports/xtb", files={"file": ("report.pdf", b"%PDF-1.4", "application/pdf")}
        )

        warning = response.json()["warnings"][0]
        assert warning["code"] == "import.unsupportedFileType"
        assert warning["params"] == {"extension": ".pdf"}

    def test_no_warning_contains_a_sentence(self, client, xtb_export):
        client.post(
            "/api/imports/xtb",
            files={"file": ("EUR_1234567.xlsx", xtb_export, "application/octet-stream")},
        )

        for batch in client.get("/api/imports").json():
            for warning in batch["warnings"]:
                # A code is a dotted identifier, never a sentence.
                assert " " not in warning["code"]
                assert warning["code"].count(".") >= 1


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


class TestDeleteInstrument:
    """See DEVLOG "Decision 3j.1" — deleting a bad, unresolved instrument must
    not require correcting it first, but must never touch one still backing
    real data."""

    def test_deletes_an_orphaned_instrument(self, client):
        client.put(
            "/api/portfolio/symbol-overrides",
            json={"broker_symbol": "GARBAGE.US", "provider_symbol": "X"},
        )
        # The override endpoint requires an existing instrument — seed one via
        # a manual position, then delete the position so the instrument is
        # orphaned but still present, matching the real-world case (a stray
        # instrument with no position/lot/transaction left).
        created = client.post(
            "/api/portfolio/positions",
            json={"broker_symbol": "ORPHAN.US", "quantity": 1, "avg_price": 1.0},
        )
        instrument_id = created.json()["instrument"]["id"]
        client.delete(f"/api/portfolio/positions/{created.json()['id']}")

        response = client.delete(f"/api/portfolio/instruments/{instrument_id}")
        assert response.status_code == 204

        instruments = client.get("/api/portfolio").json()["unresolved_symbols"]
        assert all(i["id"] != instrument_id for i in instruments)

    def test_refuses_when_a_position_still_references_it(self, client):
        created = client.post(
            "/api/portfolio/positions",
            json={"broker_symbol": "HELD.US", "quantity": 1, "avg_price": 1.0},
        )
        instrument_id = created.json()["instrument"]["id"]

        response = client.delete(f"/api/portfolio/instruments/{instrument_id}")
        assert response.status_code == 400

        assert client.get("/api/portfolio").json()["positions"][0]["instrument"]["id"] == instrument_id

    def test_404_for_unknown_id(self, client):
        assert client.delete("/api/portfolio/instruments/999").status_code == 404


class TestIncompleteData:
    """A position without broker figures must not be counted as zero."""

    def test_totals_flag_incomplete_data(self, client):
        client.post(
            "/api/portfolio/positions",
            json={"broker_symbol": "AAPL.US", "quantity": 10, "avg_price": 185.5},
        )

        totals = client.get("/api/portfolio").json()["totals"]

        assert totals["has_incomplete_data"] is True
        assert totals["invested_value"] is None


class TestP2PAggregate:
    """A `category == "P2P"` position (the Mintos Core aggregate) shows its
    broker-declared value but never a computed gain/loss — the user
    explicitly rejected both "PRU = last value" (implies a real cost that
    isn't known) and "PRU = cumulative reinvestment" (double-counts
    auto-invest churn). See DEVLOG "Decision 3u.39"."""

    def test_value_shows_but_pl_is_never_computed(self, client):
        instrument = Instrument(
            broker_symbol="MINTOS-CORE-P2P",
            category="P2P",
            not_priceable_reason="p2p_aggregate",
            currency="EUR",
        )
        _seed(client, [instrument])
        _seed(
            client,
            [
                Position(
                    instrument_id=instrument.id,
                    source="IMPORT",
                    account="Mintos Core P2P",
                    quantity=1,
                    avg_price=4500.00,  # a required placeholder, never read as a cost basis
                    broker_market_value=4500.00,
                    currency="EUR",
                )
            ],
        )

        position = client.get("/api/portfolio").json()["positions"][0]

        assert position["current_value"] == 4500.00
        assert position["current_unrealized_pl"] is None
        assert position["current_unrealized_pl_pct"] is None

    def test_pl_is_never_derived_from_avg_price_and_value(self, client):
        """Regression guard: `avg_price` is a required NOT NULL placeholder
        for this category (never a real cost basis — Decision 3u.39) and
        must never be combined with `broker_market_value` to *derive* a
        P&L — this is the one behaviour the generic broker-value fallback
        would otherwise compute for any other category. `broker_net_pl`
        left unset here (unlike the test below) to isolate exactly this
        guarantee."""
        instrument = Instrument(
            broker_symbol="MINTOS-CORE-P2P",
            category="P2P",
            not_priceable_reason="p2p_aggregate",
            currency="EUR",
        )
        _seed(client, [instrument])
        _seed(
            client,
            [
                Position(
                    instrument_id=instrument.id,
                    source="IMPORT",
                    account="Mintos Core P2P",
                    quantity=1,
                    avg_price=1000.0,  # would read as a huge, fabricated gain if ever compared to value
                    broker_market_value=4500.00,
                    currency="EUR",
                )
            ],
        )

        position = client.get("/api/portfolio").json()["positions"][0]

        assert position["current_value"] == 4500.00
        assert position["current_unrealized_pl"] is None

    def test_a_separately_computed_broker_net_pl_is_passed_through(self, client):
        """The one deliberate exception to "P2P never gets a P&L": when
        something *else* (`import_mintos_transactions_file` — DEVLOG
        "Decision 3u.47") has already computed a real, non-fabricated gain
        (cumulative interest earned) and stored it on `broker_net_pl`, it
        must surface exactly like any other category's — the guard above is
        specifically about never *deriving* one from `avg_price`, not about
        ignoring a real figure that arrived through a different path."""
        instrument = Instrument(
            broker_symbol="MINTOS-CORE-P2P",
            category="P2P",
            not_priceable_reason="p2p_aggregate",
            currency="EUR",
        )
        _seed(client, [instrument])
        _seed(
            client,
            [
                Position(
                    instrument_id=instrument.id,
                    source="IMPORT",
                    account="Mintos Core P2P",
                    quantity=1,
                    avg_price=5000.0,  # required placeholder, still unused
                    broker_market_value=5000.0,
                    broker_net_pl=250.0,
                    broker_net_pl_pct=6.50,
                    performance_note={"code": "performance.mintosInterestIncome", "params": {"since": "2024-06-30"}},
                    currency="EUR",
                )
            ],
        )

        position = client.get("/api/portfolio").json()["positions"][0]

        assert position["current_value"] == 5000.0
        assert position["current_unrealized_pl"] == 250.0
        assert position["current_unrealized_pl_pct"] == 6.50
        assert position["performance_note"] == {
            "code": "performance.mintosInterestIncome",
            "params": {"since": "2024-06-30"},
        }

    def test_p2p_value_still_counts_toward_portfolio_and_account_totals(self, client):
        """Real bug found live 2026-09-07: `_aggregate()` excluded a position
        from *every* total (not just the P&L sum) whenever its P&L was
        `None` — which is always true for P2P by design. Mintos Core's
        entire declared value was silently invisible everywhere in the
        app, not just its unknown gain/loss, even though the value itself
        was known and deliberately surfaced by `_current_position_figures`
        for exactly this purpose."""
        instrument = Instrument(
            broker_symbol="MINTOS-CORE-P2P",
            category="P2P",
            not_priceable_reason="p2p_aggregate",
            currency="EUR",
        )
        _seed(client, [instrument])
        _seed(
            client,
            [
                Position(
                    instrument_id=instrument.id,
                    source="IMPORT",
                    account="Mintos Core P2P",
                    quantity=1,
                    avg_price=4500.00,
                    broker_market_value=4500.00,
                    currency="EUR",
                )
            ],
        )

        body = client.get("/api/portfolio").json()
        totals = body["totals"]
        accounts = {a["account"]: a for a in body["accounts"]}

        assert totals["market_value"] == 4500.00
        assert totals["excluded_positions"] == 0
        assert accounts["Mintos Core P2P"]["market_value"] == 4500.00

    def test_p2p_alongside_a_normally_valued_position_sums_correctly(self, client):
        """The P2P value must add to, not replace or exclude, another
        position's own contribution to the same total — e.g. an Amundi-style
        FUND position, which (unlike Mintos) does carry a broker-reported
        gain/loss and so takes the generic broker-value fallback path."""
        p2p = Instrument(
            broker_symbol="MINTOS-CORE-P2P", category="P2P", not_priceable_reason="p2p_aggregate", currency="EUR"
        )
        fund = Instrument(broker_symbol="AMUNDI-PEG-TEST", category="FUND", currency="EUR")
        _seed(client, [p2p, fund])
        _seed(
            client,
            [
                Position(
                    instrument_id=p2p.id, source="IMPORT", account="Mintos Core P2P",
                    quantity=1, avg_price=4500.00, broker_market_value=4500.00, currency="EUR",
                ),
                Position(
                    instrument_id=fund.id, source="IMPORT", account="Amundi PEG",
                    quantity=20, avg_price=10.0, broker_market_value=300.00, broker_net_pl=25.00, currency="EUR",
                ),
            ],
        )

        totals = client.get("/api/portfolio").json()["totals"]

        assert totals["market_value"] == pytest.approx(4500.00 + 300.00)
        assert totals["excluded_positions"] == 0


class TestBrokerValueFallbackWithoutPnl:
    """Real bug found live 2026-09-08, immediately after adding the Amundi
    Synthese import (DEVLOG "Decision 3u.44"): the generic broker-value
    fallback in `_current_position_figures` required *both*
    `broker_market_value` and `broker_net_pl` to be known before
    surfacing a value at all — so a position with a real, known value but
    no known gain/loss (that new import's raw export carries no P&L
    column, unlike the annual PDF) silently lost its value everywhere,
    the exact same "value is None or pl is None" conflation already fixed
    once for the P2P branch (Decision 3u.42), just recurring here."""

    def test_a_known_value_with_no_known_pl_still_surfaces(self, client):
        instrument = Instrument(broker_symbol="AMUNDI-PEG-TEST", category="FUND", currency="EUR")
        _seed(client, [instrument])
        _seed(
            client,
            [
                Position(
                    instrument_id=instrument.id, source="IMPORT", account="Amundi PEG",
                    quantity=18.5000, avg_price=10.75000, broker_market_value=310.00, currency="EUR",
                )
            ],
        )

        position = client.get("/api/portfolio").json()["positions"][0]

        assert position["current_value"] == 310.00
        assert position["current_unrealized_pl"] is None

    def test_it_still_counts_toward_portfolio_and_account_totals(self, client):
        instrument = Instrument(broker_symbol="AMUNDI-PEG-TEST", category="FUND", currency="EUR")
        _seed(client, [instrument])
        _seed(
            client,
            [
                Position(
                    instrument_id=instrument.id, source="IMPORT", account="Amundi PEG",
                    quantity=18.5000, avg_price=10.75000, broker_market_value=310.00, currency="EUR",
                )
            ],
        )

        body = client.get("/api/portfolio").json()

        assert body["totals"]["market_value"] == 310.00
        assert body["totals"]["excluded_positions"] == 0
        assert {a["account"]: a for a in body["accounts"]}["Amundi PEG"]["market_value"] == 310.00


class TestUnknownPnlIsNeverDisplayedAsZero:
    """Real bug found live 2026-09-08, reported directly by the user
    ("il nous manque le latent et perf pour l'amundi et mintos"): an
    account where *every* position's P&L is unknown (Mintos Core P2P by
    design; Amundi funds once updated only from the Synthese export,
    which carries no gain/loss column) summed to a literal `0.0` in
    `_aggregate()` — displayed as a confident "0.00 / 0.00%" that reads as
    "no gain, no loss" when the honest answer is "unknown." Fixed by
    returning `None` (not `0.0`) whenever no position in the group
    contributed a known figure — see DEVLOG "Decision 3u.42"/"3u.44"'s own
    fix for the *value* half of this same conflation."""

    def test_an_all_unknown_pl_account_shows_none_not_zero(self, client):
        p2p = Instrument(broker_symbol="MINTOS-CORE-P2P", category="P2P", not_priceable_reason="p2p_aggregate", currency="EUR")
        _seed(client, [p2p])
        _seed(
            client,
            [
                Position(
                    instrument_id=p2p.id, source="IMPORT", account="Mintos Core P2P",
                    quantity=1, avg_price=8000.00, broker_market_value=8000.00, currency="EUR",
                )
            ],
        )

        body = client.get("/api/portfolio").json()
        account = {a["account"]: a for a in body["accounts"]}["Mintos Core P2P"]

        assert account["unrealized_pl"] is None
        assert account["unrealized_pl_pct"] is None
        # "Invested" (cost basis) is derived as market_value − unrealized —
        # with the gain genuinely unknown, that subtraction is unknown too,
        # not silently assumed to be "the same as today's value" (itself a
        # fabricated zero-gain assumption). Only the value itself is known.
        assert account["market_value"] == 8000.00
        assert account["invested_value"] is None

    def test_a_mixed_group_still_sums_the_known_contributions(self, client):
        """The global portfolio total mixes ordinary priced holdings with
        Mintos/Amundi — it must not go entirely blank just because one
        contributing position's P&L is unknown."""
        p2p = Instrument(broker_symbol="MINTOS-CORE-P2P", category="P2P", not_priceable_reason="p2p_aggregate", currency="EUR")
        fund = Instrument(broker_symbol="AMUNDI-PEG-TEST", category="FUND", currency="EUR")
        _seed(client, [p2p, fund])
        _seed(
            client,
            [
                Position(
                    instrument_id=p2p.id, source="IMPORT", account="Mintos Core P2P",
                    quantity=1, avg_price=1000.0, broker_market_value=1000.0, currency="EUR",
                ),
                Position(
                    instrument_id=fund.id, source="IMPORT", account="Amundi PEG",
                    quantity=20, avg_price=10.0, broker_market_value=300.00, broker_net_pl=25.00, currency="EUR",
                ),
            ],
        )

        totals = client.get("/api/portfolio").json()["totals"]

        assert totals["unrealized_pl"] == pytest.approx(25.00)


class TestDeclaredValuationFreshness:
    """A Mintos/Amundi position's `value_as_of` drives `valuation_note`
    ('valuation.declaredFresh'/'valuation.declaredStale') and, when stale,
    `PortfolioTotals.has_stale_declared_valuations` — a known value is
    never dropped from the total for being old (Decision 3u.42 already
    guarantees that); this only adds a caveat on top. See DEVLOG
    "Decision 3u.50"."""

    def test_a_recent_mintos_value_is_fresh_and_does_not_warn(self, client):
        instrument = Instrument(
            broker_symbol="MINTOS-CORE-P2P", category="P2P", not_priceable_reason="p2p_aggregate", currency="EUR"
        )
        _seed(client, [instrument])
        _seed(
            client,
            [
                Position(
                    instrument_id=instrument.id, source="IMPORT", account="Mintos Core P2P",
                    quantity=1, avg_price=8000.00, broker_market_value=8000.00, currency="EUR",
                    value_as_of=date.today() - timedelta(days=5),
                )
            ],
        )

        body = client.get("/api/portfolio").json()
        position = body["positions"][0]

        assert position["valuation_note"]["code"] == "valuation.declaredFresh"
        assert position["valuation_note"]["params"]["provider"] == "Mintos"
        assert body["totals"]["has_stale_declared_valuations"] is False

    def test_an_old_mintos_value_is_stale_and_warns_on_the_total(self, client):
        instrument = Instrument(
            broker_symbol="MINTOS-CORE-P2P", category="P2P", not_priceable_reason="p2p_aggregate", currency="EUR"
        )
        _seed(client, [instrument])
        _seed(
            client,
            [
                Position(
                    instrument_id=instrument.id, source="IMPORT", account="Mintos Core P2P",
                    quantity=1, avg_price=4500.00, broker_market_value=4500.00, currency="EUR",
                    value_as_of=date(2025, 9, 30),
                )
            ],
        )

        body = client.get("/api/portfolio").json()
        position = body["positions"][0]

        assert position["valuation_note"]["code"] == "valuation.declaredStale"
        assert position["valuation_note"]["params"] == {"provider": "Mintos", "date": "2025-09-30"}
        # The value is still fully included — staleness is a caveat, never an exclusion.
        assert body["totals"]["market_value"] == 4500.00
        assert body["totals"]["excluded_positions"] == 0
        assert body["totals"]["has_stale_declared_valuations"] is True

    def test_an_old_amundi_value_uses_its_own_wider_threshold(self, client):
        """Amundi's annual cadence gets a wider freshness window than
        Mintos's quarterly one — a value old enough to flag Mintos must
        not also flag Amundi."""
        fund = Instrument(
            broker_symbol="AMUNDI-PEG-TEST", category="FUND", not_priceable_reason="employee_savings_fund", currency="EUR"
        )
        _seed(client, [fund])
        _seed(
            client,
            [
                Position(
                    instrument_id=fund.id, source="IMPORT", account="Amundi PEG",
                    quantity=20, avg_price=10.0, broker_market_value=310.00, currency="EUR",
                    value_as_of=date.today() - timedelta(days=200),  # stale for Mintos, fine for Amundi
                )
            ],
        )

        body = client.get("/api/portfolio").json()
        position = body["positions"][0]

        assert position["valuation_note"]["code"] == "valuation.declaredFresh"
        assert position["valuation_note"]["params"]["provider"] == "Amundi ESR"
        assert body["totals"]["has_stale_declared_valuations"] is False

    def test_an_ordinary_priced_position_never_gets_a_valuation_note(self, client):
        instrument = Instrument(broker_symbol="AAPL.US", category="STOCK", currency="USD")
        _seed(client, [instrument])
        _seed(
            client,
            [
                Position(
                    instrument_id=instrument.id, source="MANUAL", quantity=1, avg_price=100.0,
                    broker_market_value=100.0, currency="USD",
                )
            ],
        )

        position = client.get("/api/portfolio").json()["positions"][0]
        assert position["valuation_note"] is None

    def test_account_totals_carry_the_valuation_note_independently_of_performance_note(self, client):
        """Real gap found live 2026-09-08: the "By account" table showed
        bare "—" cells for Mintos Core P2P's Invested/Unrealised/Perf. with
        no explanation of what kind of figure `market_value` even is —
        `performance_note` is `None` for this account (no interest-income
        import has run for it, Decision 3u.47), so the existing footnote
        never fires. `valuation_note` must reach `AccountTotals`
        independently of whether a `performance_note` exists at all."""
        instrument = Instrument(
            broker_symbol="MINTOS-CORE-P2P", category="P2P", not_priceable_reason="p2p_aggregate", currency="EUR"
        )
        _seed(client, [instrument])
        _seed(
            client,
            [
                Position(
                    instrument_id=instrument.id, source="IMPORT", account="Mintos Core P2P",
                    quantity=1, avg_price=8000.00, broker_market_value=8000.00, currency="EUR",
                    value_as_of=date.today() - timedelta(days=5),
                )
            ],
        )

        body = client.get("/api/portfolio").json()
        account = {a["account"]: a for a in body["accounts"]}["Mintos Core P2P"]

        assert account["performance_note"] is None
        assert account["valuation_note"]["code"] == "valuation.declaredFresh"
        assert account["valuation_note"]["params"]["provider"] == "Mintos"

    def test_account_valuation_note_prefers_stale_over_fresh_across_its_positions(self, client):
        fund1 = Instrument(
            broker_symbol="AMUNDI-PEG-A", category="FUND", not_priceable_reason="employee_savings_fund", currency="EUR"
        )
        fund2 = Instrument(
            broker_symbol="AMUNDI-PEG-B", category="FUND", not_priceable_reason="employee_savings_fund", currency="EUR"
        )
        _seed(client, [fund1, fund2])
        _seed(
            client,
            [
                Position(
                    instrument_id=fund1.id, source="IMPORT", account="Amundi PEG",
                    quantity=10, avg_price=10.0, broker_market_value=100.0, currency="EUR",
                    value_as_of=date.today(),  # fresh
                ),
                Position(
                    instrument_id=fund2.id, source="IMPORT", account="Amundi PEG",
                    quantity=10, avg_price=10.0, broker_market_value=100.0, currency="EUR",
                    value_as_of=date(2024, 1, 1),  # stale
                ),
            ],
        )

        body = client.get("/api/portfolio").json()
        account = {a["account"]: a for a in body["accounts"]}["Amundi PEG"]

        assert account["valuation_note"]["code"] == "valuation.declaredStale"

    def test_a_not_priceable_instrument_with_no_value_as_of_is_unaffected(self, client):
        """A CFD (or anything else structurally non-priceable with no
        declared-value date of its own) isn't swept into this behaviour
        just because it shares `not_priceable_reason`'s presence — only the
        two reasons in `DECLARED_VALUE_FRESHNESS_DAYS` qualify."""
        instrument = Instrument(broker_symbol="CFD1", category="CFD", not_priceable_reason="cfd", currency="EUR")
        _seed(client, [instrument])
        _seed(
            client,
            [
                Position(
                    instrument_id=instrument.id, source="IMPORT", quantity=1, avg_price=100.0,
                    broker_market_value=100.0, currency="EUR",
                )
            ],
        )

        position = client.get("/api/portfolio").json()["positions"][0]
        assert position["valuation_note"] is None


def _seed(client, rows):
    session = next(app.dependency_overrides[get_db]())
    try:
        for row in rows:
            session.add(row)
        session.commit()
        for row in rows:
            session.refresh(row)
    finally:
        session.close()
    return rows


class TestBackfillIsins:
    """`POST /api/portfolio/backfill-isins` — see `symbols/duplicates.py::backfill_isins`."""

    def test_backfills_an_instrument_that_already_has_a_name(self, client, monkeypatch):
        instrument = Instrument(broker_symbol="NKE.US", name="Nike", category="STOCK", currency="USD", country="US")
        _seed(client, [instrument])
        _seed(client, [Position(instrument_id=instrument.id, source="MANUAL", quantity=1, avg_price=1.0)])
        monkeypatch.setattr("app.symbols.duplicates.resolve_isin", lambda name: "US6541061031")

        response = client.post("/api/portfolio/backfill-isins")

        assert response.status_code == 200
        assert response.json() == {"checked": 1, "updated": 1}
        assert client.get("/api/portfolio").json()["positions"][0]["instrument"]["isin"] == "US6541061031"

    def test_skips_an_instrument_with_no_name(self, client, monkeypatch):
        instrument = Instrument(broker_symbol="EL.PA.US", category="STOCK", currency="USD", country="US")
        _seed(client, [instrument])
        _seed(client, [Position(instrument_id=instrument.id, source="MANUAL", quantity=1, avg_price=1.0)])

        def fail_if_called(*args, **kwargs):
            raise AssertionError("resolve_isin must not be called for a nameless instrument")

        monkeypatch.setattr("app.symbols.duplicates.resolve_isin", fail_if_called)

        response = client.post("/api/portfolio/backfill-isins")

        assert response.json() == {"checked": 0, "updated": 0}

    def test_skips_an_instrument_that_already_has_an_isin(self, client, monkeypatch):
        instrument = Instrument(
            broker_symbol="MC.FR", name="LVMH", isin="FR0000121014", category="STOCK", currency="EUR", country="FR"
        )
        _seed(client, [instrument])
        _seed(client, [Position(instrument_id=instrument.id, source="MANUAL", quantity=1, avg_price=1.0)])

        def fail_if_called(*args, **kwargs):
            raise AssertionError("resolve_isin must not be called when an ISIN is already on file")

        monkeypatch.setattr("app.symbols.duplicates.resolve_isin", fail_if_called)

        response = client.post("/api/portfolio/backfill-isins")

        assert response.json() == {"checked": 0, "updated": 0}

    def test_skips_an_untracked_instrument_even_with_a_name(self, client, monkeypatch):
        """A named instrument nothing references (held/watchlisted/screened)
        isn't worth spending a Wikidata request on."""
        _seed(client, [Instrument(broker_symbol="ORPHAN.US", name="Orphan Corp", category="STOCK", currency="USD", country="US")])

        def fail_if_called(*args, **kwargs):
            raise AssertionError("resolve_isin must not be called for an untracked instrument")

        monkeypatch.setattr("app.symbols.duplicates.resolve_isin", fail_if_called)

        response = client.post("/api/portfolio/backfill-isins")

        assert response.json() == {"checked": 0, "updated": 0}

    def test_a_name_that_resolves_to_nothing_is_checked_but_not_updated(self, client, monkeypatch):
        instrument = Instrument(broker_symbol="XYZ.US", name="Nonexistent Corp", category="STOCK", currency="USD", country="US")
        _seed(client, [instrument])
        _seed(client, [Position(instrument_id=instrument.id, source="MANUAL", quantity=1, avg_price=1.0)])
        monkeypatch.setattr("app.symbols.duplicates.resolve_isin", lambda name: None)

        response = client.post("/api/portfolio/backfill-isins")

        assert response.json() == {"checked": 1, "updated": 0}
