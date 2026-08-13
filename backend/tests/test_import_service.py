"""Tests for persisting an import to the database."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.messages import MessageCode
from app.ingest.service import import_export_file
from app.models import (
    Instrument,
    MappingStatus,
    Position,
    Source,
    SymbolOverride,
    Transaction,
    TxType,
)
from tests.conftest import OPEN_HEADERS, build_xtb_workbook


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()


class TestImport:
    def test_positions_and_instruments_are_created(self, db, xtb_export):
        batch = import_export_file(db, xtb_export, "EUR_1234567.xlsx")

        assert batch.positions_found == 2
        positions = db.execute(select(Position)).scalars().all()
        assert {p.instrument.broker_symbol for p in positions} == {"ASML.NL", "NVDA.US"}

    def test_company_name_and_category_are_stored(self, db, xtb_export):
        import_export_file(db, xtb_export, "EUR_1234567.xlsx")

        asml = db.execute(
            select(Instrument).where(Instrument.broker_symbol == "ASML.NL")
        ).scalar_one()
        assert asml.name == "ASML"
        assert asml.category == "STOCK"

    def test_symbol_mapping_is_applied(self, db, xtb_export):
        import_export_file(db, xtb_export, "EUR_1234567.xlsx")

        asml = db.execute(
            select(Instrument).where(Instrument.broker_symbol == "ASML.NL")
        ).scalar_one()
        assert asml.provider_symbol == "ASML.AS"
        assert asml.mapping_status == MappingStatus.RESOLVED

    def test_broker_values_are_preserved(self, db, xtb_export):
        import_export_file(db, xtb_export, "EUR_1234567.xlsx")

        nvidia = db.execute(
            select(Position).join(Instrument).where(Instrument.broker_symbol == "NVDA.US")
        ).scalar_one()
        assert nvidia.broker_market_value == 1312.08
        assert nvidia.broker_net_pl == 614.27
        assert nvidia.lots_count == 2
        assert nvidia.account == "My Trades"

    def test_cash_operations_become_transactions(self, db, xtb_export):
        import_export_file(db, xtb_export, "EUR_1234567.xlsx")

        types = {t.type for t in db.execute(select(Transaction)).scalars()}
        assert {TxType.DIVIDEND, TxType.TAX, TxType.DEPOSIT, TxType.CLOSED_TRADE} <= types

    def test_file_hash_is_recorded(self, db, xtb_export):
        batch = import_export_file(db, xtb_export, "EUR_1234567.xlsx")

        assert len(batch.file_hash) == 64


class TestIdempotency:
    """Re-importing the same file must not duplicate anything."""

    def test_transactions_are_not_duplicated(self, db, xtb_export):
        first = import_export_file(db, xtb_export, "EUR_1234567.xlsx")
        second = import_export_file(db, xtb_export, "EUR_1234567.xlsx")

        assert first.transactions_inserted > 0
        assert second.transactions_inserted == 0
        assert len(db.execute(select(Transaction)).scalars().all()) == first.transactions_inserted

    def test_partial_closes_sharing_a_position_id_survive_a_reimport(self, db, xtb_export):
        """Two partial closes share one "Position ID".

        They must stay two distinct records, without breaking the unique constraint
        and without duplicating on re-import.
        """
        import_export_file(db, xtb_export, "EUR_1234567.xlsx")
        import_export_file(db, xtb_export, "EUR_1234567.xlsx")

        closed = db.execute(
            select(Transaction).where(Transaction.type == TxType.CLOSED_TRADE)
        ).scalars().all()
        assert len(closed) == 4

    def test_open_positions_are_replaced_not_accumulated(self, db, xtb_export):
        import_export_file(db, xtb_export, "EUR_1234567.xlsx")
        import_export_file(db, xtb_export, "EUR_1234567.xlsx")

        assert len(db.execute(select(Position)).scalars().all()) == 2

    def test_manual_positions_survive_a_new_import(self, db, xtb_export):
        instrument = Instrument(broker_symbol="MC.FR", provider_symbol="MC.PA")
        db.add(instrument)
        db.flush()
        db.add(
            Position(
                instrument_id=instrument.id, source=Source.MANUAL, quantity=3, avg_price=700.0
            )
        )
        db.commit()

        import_export_file(db, xtb_export, "EUR_1234567.xlsx")

        manual = db.execute(
            select(Position).where(Position.source == Source.MANUAL)
        ).scalars().all()
        assert len(manual) == 1
        assert manual[0].instrument.broker_symbol == "MC.FR"


class TestMultipleAccounts:
    """One export covers one account: importing the PEA must not empty the brokerage account."""

    def test_both_accounts_coexist(self, db, xtb_export, xtb_pea_export):
        import_export_file(db, xtb_export, "EUR_1234567.xlsx")
        import_export_file(db, xtb_pea_export, "PEA_7654321.xlsx")

        positions = db.execute(select(Position)).scalars().all()
        by_account = {}
        for position in positions:
            by_account.setdefault(position.account, []).append(position)

        assert set(by_account) == {"My Trades", "PEA"}
        assert len(by_account["My Trades"]) == 2
        assert len(by_account["PEA"]) == 1

    def test_reimporting_one_account_leaves_the_other_intact(
        self, db, xtb_export, xtb_pea_export
    ):
        import_export_file(db, xtb_export, "EUR_1234567.xlsx")
        import_export_file(db, xtb_pea_export, "PEA_7654321.xlsx")
        import_export_file(db, xtb_export, "EUR_1234567.xlsx")

        positions = db.execute(select(Position)).scalars().all()
        accounts = [p.account for p in positions]

        assert accounts.count("PEA") == 1
        assert accounts.count("My Trades") == 2


class TestCategoryDrivenMapping:
    def test_cfd_is_never_mapped(self, db):
        content = build_xtb_workbook(
            [
                (
                    "Open Positions",
                    [["Account number", 1]],
                    OPEN_HEADERS,
                    [
                        ["My Trades", "US 500", "US500", "CFD", None, 1.0, 5000.0, None,
                         5000.0, None, None, None, 0.0, 0.0, 0.0, None, None, None],
                    ],
                )
            ]
        )
        import_export_file(db, content, "cfd.xlsx")

        instrument = db.execute(
            select(Instrument).where(Instrument.broker_symbol == "US500")
        ).scalar_one()
        assert instrument.provider_symbol is None
        assert instrument.category == "CFD"

    def test_stock_named_like_a_commodity_is_still_mapped(self, db):
        """"GOLD.US" is Barrick Gold: the broker category outranks the name."""
        content = build_xtb_workbook(
            [
                (
                    "Open Positions",
                    [["Account number", 1]],
                    OPEN_HEADERS,
                    [
                        ["My Trades", "Barrick Gold", "GOLD.US", "STOCK", None, 10.0, 200.0,
                         None, 18.0, None, None, None, 11.0, 20.0, 20.0, None, None, None],
                    ],
                )
            ]
        )
        import_export_file(db, content, "gold.xlsx")

        instrument = db.execute(
            select(Instrument).where(Instrument.broker_symbol == "GOLD.US")
        ).scalar_one()
        assert instrument.provider_symbol == "GOLD"
        assert instrument.mapping_status == MappingStatus.RESOLVED

    def test_cfd_is_not_reported_as_a_problem(self, db):
        """A CFD having no mapping is expected: do not report it as a problem."""
        content = build_xtb_workbook(
            [
                (
                    "Open Positions",
                    [["Account number", 1]],
                    OPEN_HEADERS,
                    [
                        ["My Trades", "US 500", "US500", "CFD", None, 1.0, 5000.0, None,
                         5000.0, None, None, None, 0.0, 0.0, 0.0, None, None, None],
                    ],
                )
            ]
        )
        batch = import_export_file(db, content, "cfd.xlsx")

        assert not any(w["code"] == MessageCode.UNRESOLVED_SYMBOLS for w in batch.warnings)


class TestOverrides:
    def test_override_is_used_when_creating_an_instrument(self, db):
        db.add(SymbolOverride(broker_symbol="ERICB.SE", provider_symbol="ERIC-B.ST"))
        db.commit()

        content = build_xtb_workbook(
            [
                (
                    "Open Positions",
                    [["Account number", 1]],
                    OPEN_HEADERS,
                    [
                        ["My Trades", "Ericsson", "ERICB.SE", "STOCK", None, 100.0, 6000.0,
                         None, 60.0, None, None, None, 1.0, 60.0, 60.0, None, None, None],
                    ],
                )
            ]
        )
        import_export_file(db, content, "report.xlsx")

        instrument = db.execute(
            select(Instrument).where(Instrument.broker_symbol == "ERICB.SE")
        ).scalar_one()
        assert instrument.provider_symbol == "ERIC-B.ST"
        assert instrument.mapping_status == MappingStatus.MANUAL


class TestWarnings:
    def test_unmappable_stock_is_surfaced(self, db):
        content = build_xtb_workbook(
            [
                (
                    "Open Positions",
                    [["Account number", 1]],
                    OPEN_HEADERS,
                    [
                        # A CVR code: neither a normal ticker nor a derivative.
                        ["My Trades", "CVR", "US592CVR0133", "STOCK", None, 1.0, 0.0, None,
                         0.0, None, None, None, 0.0, 0.0, 0.0, None, None, None],
                    ],
                )
            ]
        )
        batch = import_export_file(db, content, "cvr.xlsx")

        warning = next(w for w in batch.warnings if w["code"] == MessageCode.UNRESOLVED_SYMBOLS)
        assert warning["params"]["count"] == 1
        assert warning["params"]["symbols"] == ["US592CVR0133"]


class TestIsinShapedSymbols:
    def test_a_broker_symbol_that_is_an_isin_is_recorded_as_one(self, db):
        """Not an inference: the ticker field literally contains an ISIN."""
        content = build_xtb_workbook(
            [
                (
                    "Open Positions",
                    [["Account number", 1]],
                    OPEN_HEADERS,
                    [
                        ["My Trades", "CVR", "US592CVR0133", "STOCK", None, 1.0, 0.0, None,
                         0.0, None, None, None, 0.0, 0.0, 0.0, None, None, None],
                    ],
                )
            ]
        )
        import_export_file(db, content, "cvr.xlsx")

        instrument = db.execute(
            select(Instrument).where(Instrument.broker_symbol == "US592CVR0133")
        ).scalar_one()
        assert instrument.isin == "US592CVR0133"

    def test_an_ordinary_ticker_gets_no_isin(self, db):
        content = build_xtb_workbook(
            [
                (
                    "Open Positions",
                    [["Account number", 1]],
                    OPEN_HEADERS,
                    [
                        ["My Trades", "Apple", "AAPL.US", "STOCK", None, 1.0, 200.0, None,
                         180.0, None, None, None, 11.0, 20.0, 20.0, None, None, None],
                    ],
                )
            ]
        )
        import_export_file(db, content, "aapl.xlsx")

        instrument = db.execute(
            select(Instrument).where(Instrument.broker_symbol == "AAPL.US")
        ).scalar_one()
        assert instrument.isin is None


class TestIsinBackfill:
    def test_reimport_repairs_an_instrument_created_before_isin_detection(self, db):
        """Otherwise the row shows "needs fixing" forever with nothing to fix."""
        legacy = Instrument(broker_symbol="US592CVR0133", mapping_status=MappingStatus.UNRESOLVED)
        db.add(legacy)
        db.commit()
        assert legacy.isin is None

        content = build_xtb_workbook(
            [
                (
                    "Open Positions",
                    [["Account number", 1]],
                    OPEN_HEADERS,
                    [
                        ["My Trades", "CVR", "US592CVR0133", "STOCK", None, 1.0, 0.0, None,
                         0.0, None, None, None, 0.0, 0.0, 0.0, None, None, None],
                    ],
                )
            ]
        )
        import_export_file(db, content, "cvr.xlsx")

        assert legacy.isin == "US592CVR0133"


class TestNonTradableInstruments:
    """A non-transferable CVR has no ticker, no listing and no market.

    Reporting it as a retrieval failure would be permanently misleading: there is
    nothing to retrieve, and no provider anywhere could change that.
    """

    def test_a_cvr_is_marked_as_having_no_price(self, db):
        from app.ingest.service import detect_not_priceable

        assert detect_not_priceable("US592CVR0133", "CONTRA METSERA INC CVR") == "corporate_action"

    @pytest.mark.parametrize(
        ("symbol", "name"),
        [
            ("US592CVR0133", "CONTRA METSERA INC CVR"),
            ("FR0000000001", "ACME RIGHTS"),
            ("US0000000002", "SOMETHING WHEN ISSUED"),
        ],
    )
    def test_corporate_action_artefacts_are_recognised(self, symbol, name):
        from app.ingest.service import detect_not_priceable

        assert detect_not_priceable(symbol, name) is not None

    @pytest.mark.parametrize(
        ("symbol", "name"),
        [
            # A real company with a ticker, whatever its name contains.
            ("CVR.US", "CVR Energy Inc"),
            ("RIGHT.US", "Rights Corp"),
            ("AAPL.US", "Apple"),
            # An ISIN-shaped symbol alone is not enough: it may be a normal holding.
            ("US592CVR0133", "Some Ordinary Company"),
        ],
    )
    def test_tradable_instruments_are_left_alone(self, symbol, name):
        from app.ingest.service import detect_not_priceable

        assert detect_not_priceable(symbol, name) is None

    def test_import_flags_it(self, db):
        content = build_xtb_workbook(
            [
                (
                    "Open Positions",
                    [["Account number", 1]],
                    OPEN_HEADERS,
                    [
                        ["My Trades", "CONTRA METSERA INC CVR", "US592CVR0133", "STOCK", None,
                         1.0, 0.01, None, 0.01, None, None, None, 0.0, 0.0, 0.0, None, None, None],
                    ],
                )
            ]
        )
        import_export_file(db, content, "cvr.xlsx")

        instrument = db.execute(
            select(Instrument).where(Instrument.broker_symbol == "US592CVR0133")
        ).scalar_one()
        assert instrument.not_priceable_reason == "corporate_action"
