"""Tests for the Mintos importer — `app/ingest/mintos_import.py`'s pure
parsing/replay logic, and `app/ingest/service.py::import_mintos_file`'s
persistence (dedup, average-cost replay, the P2P aggregate).

Deliberately does not commit a copy of the user's real Mintos statement PDFs
as test fixtures — they carry real personal data (name, investor ID). The
PDF-table-extraction layer (`parse_mintos_statement`) was instead verified
manually against the real files during development (see DEVLOG "Decision
3u.39") — every parsed figure cross-checked against the statement's own
displayed numbers, and `compute_average_cost_positions`'s replay result
cross-checked against Mintos's own reported "Realized Return" for the
period. Tests here cover the two layers that don't need a real PDF: the
pure replay function, and the persistence layer via a synthetic
`ParsedMintosExport` (patching the parse step, matching this project's
existing convention of testing service persistence and file parsing as
separate concerns).
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.ingest.mintos_import import ParsedMintosExport, ParsedPeriod, compute_average_cost_positions
from app.ingest.service import import_mintos_file
from app.models import Instrument, Lot, Position, Transaction, TxType


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    yield session
    session.close()


def _fill(isin: str, side: str, units: float, price: float, when: str, total: float | None = None) -> dict:
    dt = datetime.strptime(when, "%Y-%m-%d %H:%M:%S")
    return {
        "external_id": f"{isin}-{side}-{when}",
        "broker_symbol": isin,
        "executed_at": dt,
        "side": side,
        "units": units,
        "unit_price": price,
        "total_consideration": total if total is not None else round(units * price, 2),
        "gain_loss": None,
        "currency": "EUR",
        "raw": None,
    }


class TestComputeAverageCostPositions:
    def test_single_buy_produces_one_open_position(self):
        txns = [_fill("ISIN1", "BUY", 100, 10.0, "2024-01-01 00:00:00")]
        holdings = compute_average_cost_positions(txns)
        assert holdings.positions["ISIN1"]["quantity"] == 100
        assert holdings.positions["ISIN1"]["avg_price"] == 10.0
        assert len(holdings.lots) == 1
        assert "close_price" not in holdings.lots[0]

    def test_two_buys_average_the_cost(self):
        txns = [
            _fill("ISIN1", "BUY", 100, 10.0, "2024-01-01 00:00:00"),
            _fill("ISIN1", "BUY", 100, 20.0, "2024-02-01 00:00:00"),
        ]
        holdings = compute_average_cost_positions(txns)
        assert holdings.positions["ISIN1"]["quantity"] == 200
        assert holdings.positions["ISIN1"]["avg_price"] == pytest.approx(15.0)

    def test_full_sell_closes_the_position(self):
        txns = [
            _fill("ISIN1", "BUY", 100, 10.0, "2024-01-01 00:00:00"),
            _fill("ISIN1", "SELL", 100, 15.0, "2024-02-01 00:00:00"),
        ]
        holdings = compute_average_cost_positions(txns)
        assert "ISIN1" not in holdings.positions
        assert len(holdings.lots) == 1
        assert holdings.lots[0]["close_price"] == 15.0

    def test_partial_sell_splits_the_lot_fifo(self):
        txns = [
            _fill("ISIN1", "BUY", 100, 10.0, "2024-01-01 00:00:00"),
            _fill("ISIN1", "SELL", 40, 15.0, "2024-02-01 00:00:00"),
        ]
        holdings = compute_average_cost_positions(txns)
        # Average cost is unchanged by a sale — a sale realises a gain/loss
        # against it, it does not change what the remainder was paid for.
        assert holdings.positions["ISIN1"]["quantity"] == 60
        assert holdings.positions["ISIN1"]["avg_price"] == 10.0
        closed = [lot for lot in holdings.lots if "close_price" in lot]
        assert len(closed) == 1
        assert closed[0]["quantity"] == 40

    def test_sell_closes_oldest_lot_first(self):
        txns = [
            _fill("ISIN1", "BUY", 50, 10.0, "2024-01-01 00:00:00"),
            _fill("ISIN1", "BUY", 50, 20.0, "2024-02-01 00:00:00"),
            _fill("ISIN1", "SELL", 50, 15.0, "2024-03-01 00:00:00"),
        ]
        holdings = compute_average_cost_positions(txns)
        # The *position*'s average cost is a standard weighted-average-cost
        # figure — unaffected by which specific lot a sale happens to close
        # (that would be FIFO cost basis, a different, deliberately not-used
        # convention here) — so it stays the blended (10+20)/2 = 15 even
        # though the FIFO *lot* being closed below is the cheaper one.
        assert holdings.positions["ISIN1"]["quantity"] == 50
        assert holdings.positions["ISIN1"]["avg_price"] == pytest.approx(15.0)
        closed = [lot for lot in holdings.lots if "close_price" in lot]
        assert len(closed) == 1
        assert closed[0]["open_price"] == 10.0  # the older (Jan) lot, not the Feb one

    def test_multiple_isins_are_independent(self):
        txns = [
            _fill("ISIN1", "BUY", 100, 10.0, "2024-01-01 00:00:00"),
            _fill("ISIN2", "BUY", 50, 5.0, "2024-01-02 00:00:00"),
        ]
        holdings = compute_average_cost_positions(txns)
        assert set(holdings.positions) == {"ISIN1", "ISIN2"}


def _p2p_period(start: str, end: str, opening: float, investments: float, repayments: float, closing: float, **kw) -> ParsedPeriod:
    return ParsedPeriod(
        period_start=datetime.strptime(start, "%Y-%m-%d"),
        period_end=datetime.strptime(end, "%Y-%m-%d"),
        opening_balance=opening,
        investments=investments,
        repayments=repayments,
        sale=0.0,
        closing_balance=closing,
        **kw,
    )


class TestImportMintosFilePersistence:
    """Persistence behaviour, independent of the PDF layer — patches
    `parse_mintos_statement` with a synthetic `ParsedMintosExport`."""

    def test_etf_buy_creates_a_position_and_an_open_lot(self, db):
        parsed = ParsedMintosExport(etf_transactions=[_fill("IE00TEST0001", "BUY", 10, 100.0, "2024-01-01 00:00:00")])
        with patch("app.ingest.service.parse_mintos_statement", return_value=parsed):
            import_mintos_file(db, b"fake", "test.pdf")

        position = db.execute(select(Position)).scalar_one()
        assert position.quantity == 10
        assert position.avg_price == 100.0
        assert position.account == "Mintos ETF"
        lot = db.execute(select(Lot)).scalar_one()
        assert lot.lot_type == "OPEN"

    def test_reimporting_the_same_file_does_not_duplicate(self, db):
        parsed = ParsedMintosExport(etf_transactions=[_fill("IE00TEST0001", "BUY", 10, 100.0, "2024-01-01 00:00:00")])
        with patch("app.ingest.service.parse_mintos_statement", return_value=parsed):
            import_mintos_file(db, b"fake", "test.pdf")
            batch2 = import_mintos_file(db, b"fake", "test.pdf")

        assert batch2.transactions_inserted == 0
        assert len(db.execute(select(Transaction)).scalars().all()) == 1
        assert len(db.execute(select(Position)).scalars().all()) == 1

    def test_holdings_recomputed_across_two_separate_imports(self, db):
        """A sell in a *later* import must correctly close a lot opened in
        an *earlier* one — the scenario `_recompute_mintos_etf_holdings`
        exists for, since Mintos never sends a cumulative export."""
        first = ParsedMintosExport(etf_transactions=[_fill("IE00TEST0001", "BUY", 100, 10.0, "2024-01-01 00:00:00")])
        second = ParsedMintosExport(etf_transactions=[_fill("IE00TEST0001", "SELL", 100, 15.0, "2024-04-01 00:00:00")])
        with patch("app.ingest.service.parse_mintos_statement", side_effect=[first, second]):
            import_mintos_file(db, b"fake1", "q1.pdf")
            import_mintos_file(db, b"fake2", "q2.pdf")

        assert db.execute(select(Position)).scalars().all() == []
        closed_lots = db.execute(select(Lot).where(Lot.lot_type == "CLOSED")).scalars().all()
        assert len(closed_lots) == 1
        assert closed_lots[0].close_price == 15.0

    def test_p2p_period_creates_flows_and_a_snapshot(self, db):
        parsed = ParsedMintosExport(
            p2p_period=_p2p_period("2024-04-01", "2024-06-30", 0.0, 2000.0, -300.0, 1700.0, interest_received=7.0)
        )
        with patch("app.ingest.service.parse_mintos_statement", return_value=parsed):
            import_mintos_file(db, b"fake", "test.pdf")

        types = {t.type for t in db.execute(select(Transaction)).scalars().all()}
        assert TxType.P2P_INVESTMENT in types
        assert TxType.P2P_PRINCIPAL_REPAYMENT in types
        assert TxType.P2P_INTEREST in types
        assert TxType.P2P_SNAPSHOT in types
        # Zero fee this period must not create a spurious P2P_FEE row.
        assert TxType.P2P_FEE not in types

        position = db.execute(select(Position)).scalar_one()
        assert position.broker_market_value == 1700.0
        assert position.account == "Mintos Core P2P"
        instrument = db.get(Instrument, position.instrument_id)
        assert instrument.category == "P2P"
        assert instrument.not_priceable_reason == "p2p_aggregate"

    def test_p2p_position_always_reflects_the_latest_period_regardless_of_import_order(self, db):
        older = ParsedMintosExport(p2p_period=_p2p_period("2024-04-01", "2024-06-30", 0.0, 1000.0, 0.0, 1000.0))
        newer = ParsedMintosExport(p2p_period=_p2p_period("2024-07-01", "2024-09-30", 1000.0, 500.0, -200.0, 1300.0))
        with patch("app.ingest.service.parse_mintos_statement", side_effect=[newer, older]):
            import_mintos_file(db, b"fake-newer", "q3.pdf")
            import_mintos_file(db, b"fake-older", "q2.pdf")  # imported second, but an OLDER period

        position = db.execute(select(Position)).scalar_one()
        assert position.broker_market_value == 1300.0  # still the newer period's closing balance
