"""Tests for `app/ingest/mintos_transactions_import.py`'s pure parsing and
`app/ingest/service.py::import_mintos_transactions_file`'s persistence.

Deliberately does not commit a copy of the user's real Mintos account-
statement export as a test fixture — same personal-data reasoning as the
other Mintos/Amundi test modules. The real file (150,000 rows, 2025-01-01
to 2026-09-08) was cross-checked manually during development (DEVLOG
"Decision 3u.47"): summing exactly the income/cost types this module
recognises gave a real cumulative interest and cost figure for that
window — combined with the periodic PDF's own pre-2025 interest/fee
transactions, a total net gain against the current value that worked out
to a plausible multi-year P2P yield (low double-digit percent) — the
strongest evidence the categorisation is right, not just plausible-looking.
"""

from __future__ import annotations

import io
from datetime import date, datetime
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.ingest.mintos_investments_import import ParsedMintosInvestmentsSnapshot
from app.ingest.mintos_transactions_import import (
    ParsedMintosTransactionsExport,
    parse_mintos_transactions_export,
)
from app.ingest.service import import_mintos_investments_file, import_mintos_transactions_file
from app.models import Instrument, Position, Transaction, TxType


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    yield session
    session.close()


_HEADER = ["Date", "ID de transaction :", "Détails", "Mouvement", "Solde", "Devise", "Type de paiement"]


def _row(when: str, amount: float, payment_type: str) -> list[str]:
    return [when, "tx-id", "détail", str(amount), "100.0", "EUR", payment_type]


def _csv(rows: list[list[str]]) -> bytes:
    buffer = io.StringIO()
    buffer.write(",".join(_HEADER) + "\n")
    for row in rows:
        buffer.write(",".join(f'"{c}"' if "," in c else c for c in row) + "\n")
    return buffer.getvalue().encode("utf-8")


class TestParseMintosTransactionsExport:
    def test_sums_income_and_cost_separately(self):
        content = _csv(
            [
                _row("2025-01-13 15:15:02", 0.05, "Intérêt perçu"),
                _row("2025-02-01 10:00:00", 0.02, "Bonus"),
                _row("2025-03-01 10:00:00", -0.01, "Tax withholding"),
            ]
        )

        result = parse_mintos_transactions_export(content, "20260908-account-statement.csv")

        assert result.income_total == pytest.approx(0.07)
        assert result.cost_total == pytest.approx(-0.01)
        assert result.net_gain == pytest.approx(0.06)
        assert result.period_start == date(2025, 1, 13)
        assert result.period_end == date(2025, 3, 1)
        assert result.transaction_count == 3

    def test_deposits_are_tracked_but_excluded_from_income(self):
        content = _csv(
            [
                _row("2025-01-13 15:15:02", 200.0, "Dépôts"),
                _row("2025-01-14 10:00:00", 0.05, "Intérêt perçu"),
            ]
        )

        result = parse_mintos_transactions_export(content, "20260908-account-statement.csv")

        assert result.deposits_total == pytest.approx(200.0)
        assert result.income_total == pytest.approx(0.05)

    def test_a_templated_card_deposit_label_still_counts_as_a_deposit(self):
        content = _csv(
            [_row("2025-01-13 15:15:02", 100.0, "Dépôt par carte %REFERENCE%, après des frais de %FEE_AMOUNT% %FEE_ABBREVIATION%")]
        )

        result = parse_mintos_transactions_export(content, "20260908-account-statement.csv")

        assert result.deposits_total == pytest.approx(100.0)

    def test_internal_principal_churn_is_ignored_entirely(self):
        """Decision 3u.39's ruling: `Investissement`/`Principal perçu`-type
        rows are internal auto-invest churn, not real income or deposits —
        must not contribute to any bucket."""
        content = _csv(
            [
                _row("2025-01-13 15:15:02", -500.0, "Investissement"),
                _row("2025-01-14 10:00:00", 480.0, "Principal perçu"),
            ]
        )

        result = parse_mintos_transactions_export(content, "20260908-account-statement.csv")

        assert result.income_total == 0.0
        assert result.cost_total == 0.0
        assert result.deposits_total == 0.0
        assert result.transaction_count == 2  # still counted for period_start/end, just uncategorised

    def test_core_etf_90_rows_are_ignored(self):
        content = _csv([_row("2025-01-13 15:15:02", 4000.00, "Paiement ETF entrant")])

        result = parse_mintos_transactions_export(content, "20260908-account-statement.csv")

        assert result.income_total == 0.0

    def test_no_rows_is_a_warning(self):
        content = _csv([])

        result = parse_mintos_transactions_export(content, "20260908-account-statement.csv")

        assert result.is_empty
        assert result.warnings

    def test_missing_expected_columns_is_a_warning(self):
        content = b"Foo,Bar\n1,2\n"

        result = parse_mintos_transactions_export(content, "20260908-account-statement.csv")

        assert result.is_empty
        assert result.warnings

    def test_unreadable_content_is_a_warning_not_a_crash(self):
        result = parse_mintos_transactions_export(b"\xff\xfe not utf-8 at all", "20260908-account-statement.csv")

        assert result.is_empty
        assert result.warnings


def _p2p_instrument(db) -> Instrument:
    instrument = Instrument(broker_symbol="MINTOS-CORE-P2P", category="P2P", not_priceable_reason="p2p_aggregate", currency="EUR")
    db.add(instrument)
    db.flush()
    return instrument


class TestImportMintosTransactionsFilePersistence:
    def test_updates_an_existing_positions_gain_fields(self, db):
        instrument = _p2p_instrument(db)
        db.add(
            Position(
                instrument_id=instrument.id, source="IMPORT", account="Mintos Core P2P",
                quantity=1, avg_price=3000.00, broker_market_value=3000.00, currency="EUR",
            )
        )
        db.commit()

        parsed = ParsedMintosTransactionsExport(
            period_start=date(2025, 1, 1), period_end=date(2026, 9, 8),
            income_total=500.00, cost_total=-50.00, transaction_count=150000,
        )
        with patch("app.ingest.service.parse_mintos_transactions_export", return_value=parsed):
            import_mintos_transactions_file(db, b"fake", "20260908-account-statement.csv")

        position = db.execute(select(Position)).scalar_one()
        assert position.broker_net_pl == pytest.approx(450.00)
        assert position.performance_note == {
            "code": "performance.mintosInterestIncome",
            "params": {"since": "2025-01-01"},
        }
        # The value itself is untouched by this importer.
        assert position.broker_market_value == 3000.00

    def test_combines_with_pre_period_periodic_pdf_interest_without_double_counting(self, db):
        """The exact scenario this feature was built for: quarterly PDFs
        already recorded real interest for periods before this CSV's own
        coverage starts — the total must include both, not just the CSV's
        own window."""
        instrument = _p2p_instrument(db)
        db.add(
            Position(
                instrument_id=instrument.id, source="IMPORT", account="Mintos Core P2P",
                quantity=1, avg_price=3000.00, broker_market_value=8000.00, currency="EUR",
            )
        )
        # Pre-existing periodic-PDF-derived interest/fee, all before the
        # CSV's period_start — `raw["period_start"]` shaped exactly like
        # `mintos_import.py`'s own real output: a *full datetime* string
        # ("2024-04-01T00:00:00"), not a plain date. A real bug found live
        # 2026-09-08: reading this back with `date.fromisoformat` (which
        # only accepts a plain date) crashed the whole import — fixed with
        # `datetime.fromisoformat(...).date()`, which accepts both shapes.
        db.add_all(
            [
                Transaction(
                    type=TxType.P2P_INTEREST, instrument_id=instrument.id, account="Mintos Core P2P",
                    executed_at=datetime(2024, 6, 30), amount=5.00, external_id="pdf-q2-2024-interest",
                    raw={"period_start": "2024-04-01T00:00:00", "period_end": "2024-06-30T00:00:00"},
                ),
                Transaction(
                    type=TxType.P2P_FEE, instrument_id=instrument.id, account="Mintos Core P2P",
                    executed_at=datetime(2024, 6, 30), amount=-1.00, external_id="pdf-q2-2024-fee",
                    raw={"period_start": "2024-04-01T00:00:00", "period_end": "2024-06-30T00:00:00"},
                ),
            ]
        )
        db.commit()

        parsed = ParsedMintosTransactionsExport(
            period_start=date(2025, 1, 1), period_end=date(2026, 9, 8),
            income_total=500.00, cost_total=-50.00, transaction_count=150000,
        )
        with patch("app.ingest.service.parse_mintos_transactions_export", return_value=parsed):
            import_mintos_transactions_file(db, b"fake", "20260908-account-statement.csv")

        position = db.execute(select(Position)).scalar_one()
        # 5.00 - 1.00 (pre-period) + 500.00 - 50.00 (this file) = 454.00
        assert position.broker_net_pl == pytest.approx(454.00)
        # "Since" reflects the earliest known period_start (2024-04-01),
        # not this file's own (2025-01-01) — the whole point of combining
        # both sources.
        assert position.performance_note["params"]["since"] == "2024-04-01"

    def test_reimporting_the_same_file_does_not_duplicate_transactions(self, db):
        instrument = _p2p_instrument(db)
        db.add(
            Position(
                instrument_id=instrument.id, source="IMPORT", account="Mintos Core P2P",
                quantity=1, avg_price=3000.00, broker_market_value=3000.00, currency="EUR",
            )
        )
        db.commit()

        parsed = ParsedMintosTransactionsExport(
            period_start=date(2025, 1, 1), period_end=date(2026, 9, 8),
            income_total=500.00, cost_total=-50.00, transaction_count=150000,
        )
        with patch("app.ingest.service.parse_mintos_transactions_export", return_value=parsed):
            import_mintos_transactions_file(db, b"fake", "20260908-account-statement.csv")
            batch2 = import_mintos_transactions_file(db, b"fake", "20260908-account-statement.csv")

        assert batch2.transactions_inserted == 0
        txns = db.execute(select(Transaction)).scalars().all()
        assert len(txns) == 2  # one interest, one fee — not duplicated

    def test_no_existing_position_means_nothing_to_attach_the_gain_to(self, db):
        """Not a crash — just nothing to update, since no value has ever
        been imported for this account yet."""
        parsed = ParsedMintosTransactionsExport(
            period_start=date(2025, 1, 1), period_end=date(2026, 9, 8),
            income_total=500.00, cost_total=-50.00, transaction_count=150000,
        )
        with patch("app.ingest.service.parse_mintos_transactions_export", return_value=parsed):
            batch = import_mintos_transactions_file(db, b"fake", "20260908-account-statement.csv")

        assert batch.positions_found == 0
        assert db.execute(select(Position)).scalars().all() == []

    def test_an_empty_parse_creates_nothing(self, db):
        parsed = ParsedMintosTransactionsExport()  # no dates at all
        with patch("app.ingest.service.parse_mintos_transactions_export", return_value=parsed):
            batch = import_mintos_transactions_file(db, b"fake", "bad.csv")

        assert batch.transactions_inserted == 0
        assert db.execute(select(Transaction)).scalars().all() == []


class TestGainSurvivesALaterValueOnlyImport:
    """Real, user-caught data-loss bug found live 2026-09-08: a real gain
    computed here got silently wiped the moment a PDF or Investments
    snapshot was re-imported afterward, because
    `_recompute_mintos_p2p_position` deleted and recreated the Position
    row from scratch, with no knowledge that this importer had separately
    set `broker_net_pl`/`performance_note` on it. Confirmed against the
    real database: batches for a transactions CSV (correctly setting
    `broker_net_pl`) were followed by a re-import of the same Investments
    snapshot file, after which the live position showed `broker_net_pl:
    null` again — a real gain the user had already provided the data for,
    reporting as "unknown." See DEVLOG "Bug 3u.52"."""

    def test_reimporting_the_investments_snapshot_does_not_wipe_the_gain(self, db):
        instrument = _p2p_instrument(db)
        db.add(
            Position(
                instrument_id=instrument.id, source="IMPORT", account="Mintos Core P2P",
                quantity=1, avg_price=8000.00, broker_market_value=8000.00, currency="EUR",
            )
        )
        db.commit()

        transactions_parsed = ParsedMintosTransactionsExport(
            period_start=date(2025, 1, 1), period_end=date(2026, 9, 8),
            income_total=500.00, cost_total=-50.00, transaction_count=150000,
        )
        with patch("app.ingest.service.parse_mintos_transactions_export", return_value=transactions_parsed):
            import_mintos_transactions_file(db, b"fake-csv", "20260908-account-statement.csv")

        position = db.execute(select(Position)).scalar_one()
        assert position.broker_net_pl == pytest.approx(450.00)  # sanity check before the regression trigger

        investments_parsed = ParsedMintosInvestmentsSnapshot(
            as_of=date(2026, 9, 8), total_invested=8000.00, positions_found=500
        )
        with patch("app.ingest.service.parse_mintos_investments_export", return_value=investments_parsed):
            import_mintos_investments_file(db, b"fake-xlsx", "Investments-08-09-2026.xlsx")

        position = db.execute(select(Position)).scalar_one()
        assert position.broker_market_value == 8000.00  # the re-import's own job: unaffected
        assert position.broker_net_pl == pytest.approx(450.00)  # must survive, not reset to None
        assert position.performance_note == {
            "code": "performance.mintosInterestIncome",
            "params": {"since": "2025-01-01"},
        }
