"""Tests for `app/ingest/amundi_operations_import.py` and
`service.import_amundi_operations_file`.

The real journal is not committed: its `Donnees` sheet holds the account
holder's name and postal address. It was checked by hand during development
(46 operations, May 2023 to November 2026): every fund's units add up to a
plausible holding, the employer match comes as its own ``ABD`` row, and an
arbitrage shows as a negative row on the source fund and a positive one on
the destination. See DEVLOG "Step 3u.88". No library writes .xlsb, so the
rows are fed to `parse_operations_rows` directly.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.ingest.amundi_import import ParsedAmundiExport, ParsedFund
from app.ingest.amundi_operations_import import (
    LedgerOp,
    fund_pools,
    parse_operations_rows,
)
from app.ingest.service import import_amundi_operations_file, import_amundi_synthese_file
from app.models import Position, Transaction, TxType

_FIELDS = [
    None, "opeIndCodeEntreprise", "opeIndLibelleEntreprise", "opeIndCodeEtablissement",
    "opeIndLibelleEtablissement", "opeIndFlagCommunicationEtab", "instDateComptabilisation",
    "opeIndLibelleCommunication", "instOrigineAvoirs", "instNomDispositif", "instNomFonds", "instVlReel",
    "instEchNombreDeParts", "instEchMontantBrut", "instEchDateEcheance", "opeColType", "opeColSousType",
    "opeColCadre", "opeIndType", "opeIndCasDeGestion", "instNaturePocheDispositif",
]

PEG = "Plan Epargne Groupe 5 ans"
PERCO = "PERCO LIBRE Exemple"
FUND_A = "FONDS ACTIONS EXEMPLE - E"
FUND_M = "FONDS MONETAIRE EXEMPLE"
FUND_P = "FONDS PERCO EXEMPLE"


def _serial(day: date) -> float:
    return float((day - date(1899, 12, 30)).days)


def _op(day, label, origin, dispositif, fund, nav, units, amount, op_type, subtype):
    return [None, "000000", "EMPLOYEUR EXEMPLE", None, None, False, _serial(day), label, origin, dispositif,
            fund, nav, units, amount, 48000.0, op_type, subtype, "NORMAL", op_type, subtype, None]


def _rows(*ops):
    return [[None, *range(1, 21)], _FIELDS, *ops, [None] * 21]


_JOURNAL = _rows(
    _op(date(2025, 3, 1), "Versement volontaire", "VV", PEG, FUND_A, 50.0, 20.0, 1000.0, "SOUS", "VVIND"),
    _op(date(2025, 3, 1), "Versement volontaire", "ABD", PEG, FUND_A, 50.0, 10.0, 500.0, "SOUS", "VVIND"),
    _op(date(2025, 5, 31), "participation", "RSP", PEG, FUND_M, 10.0, 30.0, 300.0, "SOUS", "RSP"),
    _op(date(2025, 6, 9), "Frais adresse invalide", None, PEG, FUND_M, 10.0, -2.0, -20.0, "RACH", "NPAI"),
    _op(date(2025, 8, 7), "Dividendes capitalisés", None, PEG, FUND_A, 60.0, 0.5, 30.0, "OST", "CAPIT"),
    _op(date(2025, 9, 24), "Arbitrage/Transfert", None, PEG, FUND_M, 10.0, -10.0, -100.0, "ARB", "LIBRE"),
    _op(date(2025, 9, 24), "Arbitrage/Transfert", None, PERCO, FUND_P, 20.0, 5.0, 100.0, "ARB", "LIBRE"),
)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    yield session
    session.close()


class TestParseOperations:
    def test_reads_every_operation_and_skips_blank_rows(self):
        result = parse_operations_rows(_JOURNAL)

        assert result.warnings == []
        assert len(result.operations) == 7
        first = result.operations[0]
        assert first.executed_on == date(2025, 3, 1)
        assert first.account == "Amundi PEG"
        assert (first.fund, first.units, first.amount, first.origin) == (FUND_A, 20.0, 1000.0, "VV")

    def test_perco_dispositif_goes_to_the_perco_account(self):
        result = parse_operations_rows(_JOURNAL)

        assert {op.account for op in result.operations if op.dispositif == PERCO} == {"Amundi PERCO"}

    def test_missing_columns_is_a_warning(self):
        result = parse_operations_rows([["foo", "bar"], [1, 2]])

        assert result.is_empty
        assert [w.code for w in result.warnings] == ["import.noTableRecognised"]

    def test_header_without_operations_is_a_warning(self):
        result = parse_operations_rows(_rows())

        assert [w.code for w in result.warnings] == ["import.nothingImportable"]


def _ledger(day, account, symbol, units, amount, origin, op_type, subtype=None):
    return LedgerOp(day, account, symbol, units, amount, origin, op_type, subtype)


class TestFundPools:
    def test_employer_match_is_kept_apart_from_own_money(self):
        pools = fund_pools([
            _ledger(date(2025, 1, 1), "PEG", "A", 10.0, 100.0, "VV", "SOUS"),
            _ledger(date(2025, 1, 1), "PEG", "A", 5.0, 50.0, "ABD", "SOUS"),
            _ledger(date(2025, 2, 1), "PEG", "A", 2.0, 30.0, "RSP", "SOUS"),
        ])

        assert (pools["A"].units, pools["A"].own, pools["A"].match) == (17.0, 130.0, 50.0)

    def test_arbitrage_moves_each_cost_in_proportion_not_the_value(self):
        pools = fund_pools([
            _ledger(date(2025, 1, 1), "PERCO", "A", 10.0, 100.0, "VV", "SOUS"),
            _ledger(date(2025, 1, 1), "PERCO", "A", 10.0, 100.0, "ABD", "SOUS"),
            # Half the units leave A, now worth 300 (a 50% gain), into B and C.
            _ledger(date(2025, 6, 1), "PERCO", "A", -10.0, -300.0, None, "ARB", "LIBRE"),
            _ledger(date(2025, 6, 1), "PERCO", "B", 20.0, 200.0, None, "ARB", "LIBRE"),
            _ledger(date(2025, 6, 1), "PERCO", "C", 5.0, 100.0, None, "ARB", "LIBRE"),
        ])

        assert (pools["A"].own, pools["A"].match) == (50.0, 50.0)
        # B got 2/3 of the 300, so 2/3 of the 50 own and 50 match that moved.
        assert (pools["B"].own, pools["B"].match) == (pytest.approx(33.33), pytest.approx(33.33))
        assert (pools["C"].own, pools["C"].match) == (pytest.approx(16.67), pytest.approx(16.67))

    def test_capitalised_dividends_and_address_fee_leave_costs_alone(self):
        pools = fund_pools([
            _ledger(date(2025, 1, 1), "PEG", "A", 10.0, 100.0, "VV", "SOUS"),
            _ledger(date(2025, 3, 1), "PEG", "A", 0.5, 6.0, None, "OST", "CAPIT"),
            _ledger(date(2025, 4, 1), "PEG", "A", -1.0, -20.0, None, "RACH", "NPAI"),
        ])

        assert (pools["A"].units, pools["A"].own, pools["A"].match) == (9.5, 100.0, 0.0)

    def test_redemption_removes_its_share_of_both_costs(self):
        pools = fund_pools([
            _ledger(date(2025, 1, 1), "PEG", "A", 10.0, 100.0, "VV", "SOUS"),
            _ledger(date(2025, 1, 1), "PEG", "A", 10.0, 100.0, "ABD", "SOUS"),
            _ledger(date(2026, 1, 1), "PEG", "A", -5.0, -80.0, None, "RACH", "LIBRE"),
        ])

        assert (pools["A"].units, pools["A"].own, pools["A"].match) == (15.0, 75.0, 75.0)


def _synthese(*funds: ParsedFund) -> ParsedAmundiExport:
    parsed = ParsedAmundiExport()
    parsed.as_of = date(2025, 11, 1)
    parsed.funds = list(funds)
    return parsed


def _import_journal(db, rows=_JOURNAL, name="ExportOperations.xlsb"):
    with patch("app.ingest.service.parse_amundi_operations_export", return_value=parse_operations_rows(rows)):
        return import_amundi_operations_file(db, b"journal", name)


def _positions(db) -> dict[float, Position]:
    return {p.quantity: p for p in db.execute(select(Position)).scalars()}


class TestImportOperations:
    def _holdings(self, db, quantity_a=30.5):
        parsed = _synthese(
            ParsedFund("Amundi PEG", FUND_A, 60.0, quantity_a, 1830.0, None),
            ParsedFund("Amundi PEG", FUND_M, 10.0, 18.0, 180.0, None),
            ParsedFund("Amundi PERCO", FUND_P, 22.0, 5.0, 110.0, None),
        )
        with patch("app.ingest.service.parse_amundi_synthese_export", return_value=parsed):
            import_amundi_synthese_file(db, b"synthese", "Synthese_20251101_100000.xlsb")

    def test_gain_is_value_minus_money_paid_in(self, db):
        self._holdings(db)

        batch = _import_journal(db)

        positions = _positions(db)
        # 1000 of own money; the 500 match and the dividend are gain.
        assert positions[30.5].broker_net_pl == pytest.approx(1830.0 - 1000.0)
        # 300 in; 10 of the 28 units (and so 10/28 of the cost) left by
        # arbitrage; the 20 address fee is a loss, not a withdrawal.
        assert positions[18.0].broker_net_pl == pytest.approx(180.0 - 300.0 * 18 / 28, abs=0.01)
        # The destination takes the cost that left, not the 100 of value.
        assert positions[5.0].broker_net_pl == pytest.approx(110.0 - 300.0 * 10 / 28, abs=0.01)
        assert positions[30.5].performance_note == {
            "code": "performance.amundiGainFromOperations",
            "params": {"since": "2025-03-01", "match": "500.00"},
        }
        assert batch.positions_found == 3
        assert batch.transactions_inserted == 7

    def test_reimport_inserts_nothing(self, db):
        _import_journal(db)
        batch = _import_journal(db, name="ExportOperations-again.xlsb")

        assert batch.transactions_inserted == 0
        assert db.execute(select(Transaction).where(Transaction.type == TxType.AMUNDI_OPERATION)).scalars().all().__len__() == 7

    def test_two_identical_rows_stay_two(self, db):
        same = _op(date(2025, 3, 1), "Versement volontaire", "VV", PEG, FUND_A, 50.0, 1.0, 50.0, "SOUS", "VVIND")
        batch = _import_journal(db, rows=_rows(same, list(same)))

        assert batch.transactions_inserted == 2

    def test_units_not_adding_up_keep_the_previous_figure_and_say_so(self, db):
        # 40 units held but the journal only explains 30.5: a payment before
        # the exported period is missing, so its sum would understate the cost.
        self._holdings(db, quantity_a=40.0)

        batch = _import_journal(db)

        assert _positions(db)[40.0].performance_note is None
        assert batch.warnings[-1]["code"] == "import.amundiOperationsNotApplied"
        assert FUND_A in batch.warnings[-1]["params"]["funds"]

    def test_a_later_synthese_keeps_the_exact_gain(self, db):
        self._holdings(db)
        _import_journal(db)

        newer = _synthese(ParsedFund("Amundi PEG", FUND_A, 70.0, 30.5, 2135.0, None))
        newer.as_of = date(2025, 12, 1)
        with patch("app.ingest.service.parse_amundi_synthese_export", return_value=newer):
            import_amundi_synthese_file(db, b"synthese-2", "Synthese_20251201_100000.xlsb")

        position = _positions(db)[30.5]
        assert position.broker_net_pl == pytest.approx(2135.0 - 1000.0)
        assert position.performance_note["code"] == "performance.amundiGainFromOperations"


class TestCatchUpOlderPosition:
    """The Synthese on file predates the journal's last payments."""

    def _older_holdings(self, db, quantity_a):
        parsed = _synthese(ParsedFund("Amundi PEG", FUND_A, 50.0, quantity_a, quantity_a * 50.0, None))
        parsed.as_of = date(2025, 4, 1)  # after the March payment, before the August dividend
        with patch("app.ingest.service.parse_amundi_synthese_export", return_value=parsed):
            import_amundi_synthese_file(db, b"old-synthese", "Synthese_20250401_100000.xlsb")

    def test_units_matching_at_its_date_bring_it_up_to_the_journal(self, db):
        self._older_holdings(db, quantity_a=30.0)

        batch = _import_journal(db)

        position = _positions(db)[30.5]
        assert position.value_as_of == date(2025, 8, 7)
        assert position.market_price == 60.0
        assert position.broker_market_value == pytest.approx(30.5 * 60.0)
        assert position.broker_net_pl == pytest.approx(30.5 * 60.0 - 1000.0)
        codes = [w["code"] for w in batch.warnings]
        assert "import.amundiPositionsUpdatedFromOperations" in codes
        assert "2025-04-01" in batch.warnings[codes.index("import.amundiPositionsUpdatedFromOperations")]["params"]["funds"]

    def test_units_not_matching_at_its_date_change_nothing(self, db):
        # 35 units on 2025-04-01 but the journal only explains 30 by then.
        self._older_holdings(db, quantity_a=35.0)

        batch = _import_journal(db)

        position = _positions(db)[35.0]
        assert position.value_as_of == date(2025, 4, 1)
        assert position.performance_note is None
        assert batch.warnings[-1]["code"] == "import.amundiOperationsNotApplied"
