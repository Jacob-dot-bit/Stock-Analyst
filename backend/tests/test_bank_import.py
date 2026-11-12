"""Tests for `app/ingest/bank_import.py` and `service.import_bank_file`.

The real Monabanq export is not committed: it holds my name, my account
numbers and three years of card payments. It was checked by hand during
development: the net paid to Amundi from the bank matches the voluntary
payments total of the Amundi operations journal (Step 3u.90). See DEVLOG
"Step 3u.91". The workbooks below are built in the same shape, with made-up
names and numbers.
"""

from __future__ import annotations

import io
from datetime import date, datetime

import openpyxl
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.ingest.bank_import import broker_of, parse_bank_export
from app.ingest.detect import FileKind, detect_file
from app.ingest.service import import_bank_file
from app.models import Instrument, Position, Transaction, TxType

CURRENT = ("COMPTE COURANT M JEAN EXEMPLE", "14690 00001 11112222333", "Cpt 00001 11112222333")
SAVINGS = ("LIVRET A M JEAN EXEMPLE", "14690 00001 44445555666", "Cpt 00001 44445555666")


def _d(day: str) -> datetime:
    return datetime.strptime(day, "%Y-%m-%d")


def _export(as_of: str, balances: dict[tuple, float], operations: dict[tuple, list[tuple]]) -> bytes:
    """`operations[account]` rows are (date, label, debit, credit)."""
    wb = openpyxl.Workbook()
    summary = wb.active
    summary.title = "Vos comptes"
    summary.append([f"Votre situation financière au {as_of}"])
    summary.append([])
    summary.append(["Compte", "R.I.B.", "Solde", "Dev"])
    for account, balance in balances.items():
        summary.append([account[0], account[1], balance, "EUR"])
    for account in balances:
        sheet = wb.create_sheet(account[2])
        sheet.append([f"Situation de votre compte {account[0]} (EUR) au {as_of}"])
        sheet.append([f"R.I.B. : {account[1]}"])
        sheet.append([None, None, None, "Solde initial : ", None, None, "EUR"])
        sheet.append(["Liste de vos comptes"])
        sheet.append(["Date", "Valeur", "Libellé", "Débit", "Crédit", "Solde", "Dev"])
        for day, label, debit, credit in operations.get(account, []):
            sheet.append([_d(day), _d(day), label, debit, credit, None, "EUR"])
        sheet.append([])
        sheet.append([None, None, None, f"Solde au {as_of} : ", None, balances[account], "EUR"])
    hidden = wb.create_sheet("hidden_data")
    hidden.append(["Nombre de compte"])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


OPERATIONS = {
    CURRENT: [
        ("2025-01-03", "PAIEMENT CB 0201 PARIS BOULANGERIE CARTE 1234", -4.2, None),
        ("2025-01-10", "VIR SEPA XTB S.A", -500, None),
        ("2025-01-10", "PAIEMENT CB 0901 PL WARSZAWA XTB.COM CARTE 1234", -50, None),
        ("2025-01-10", "PAIEMENT CB 0901 PL WARSZAWA XTB.COM CARTE 1234", -50, None),
        ("2025-02-01", "VIR SEPA 12345678 - INVESTOR", -200, None),
        ("2025-03-01", "VIR SEPA MINTOS MARKETPLACE AS", -300, None),
        ("2025-03-05", "PRLV SEPA AMUNDI ESR R-1 PREL VERST VOL O-1", -1000, None),
        ("2025-03-20", "VIR AMUNDI ESR 2 AMUNDI-TC RETOUR VV", None, 1000),
        ("2025-05-31", "VIR AMUNDI ESR R-3 VIRT PARTICIPATION O-3", None, 150.5),
        ("2025-09-02", "VIR XTB SA 399700 XTB SA", None, 250),
        ("2025-09-03", "VIR LIVRET A", None, 100),
        ("2025-09-05", "PRLV SEPA FREE MOBILE", -19.99, None),
    ],
    SAVINGS: [
        ("2025-04-30", "VIR DE M JEAN EXEMPLE", None, 200),
        ("2025-12-31", "INTERETS 2025", None, 12.34),
    ],
}


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()


@pytest.fixture
def content() -> bytes:
    return _export("12/11/2026", {CURRENT: 1234.56, SAVINGS: 2000.0}, OPERATIONS)


class TestBrokerOf:
    @pytest.mark.parametrize(
        ("label", "broker"),
        [
            ("VIR SEPA XTB S.A", "XTB"),
            ("PAIEMENT CB 0101 PL WARSZAWA XTB.COM CARTE 0000", "XTB"),
            ("VIR INST XTB SPOLKA AKCYJNA 0000000000000000", "XTB"),
            ("VIR SEPA MINTOS MARKETPLACE AS", "Mintos"),
            ("VIR SEPA 12345678 - INVESTO", "Mintos"),
            ("PRLV SEPA AMUNDI ESR PREL VERST VOL O-000000001", "Amundi"),
            ("VIR LIVRET A", None),
            ("PRLV SEPA LSA COURTAGE LSA COUR 123 PRELEVEMENT LSA-COURTAGE", None),
            ("PAIEMENT CB 0101 PARIS SUPERMARCHE CARTE 0000", None),
        ],
    )
    def test_label(self, label, broker):
        assert broker_of(label) == broker


class TestParse:
    def test_accounts_and_balances(self, content):
        parsed = parse_bank_export(content, "comptes.xlsx")

        assert parsed.as_of == date(2026, 11, 12)
        assert [(a.label, a.symbol, a.balance) for a in parsed.accounts] == [
            ("Monabanq Compte Courant", "MONABANQ-COMPTE-COURANT-2333", 1234.56),
            ("Monabanq Livret A", "MONABANQ-LIVRET-A-5666", 2000.0),
        ]
        assert parsed.accounts[0].first_operation == date(2025, 1, 3)

    def test_only_broker_transfers_are_kept(self, content):
        parsed = parse_bank_export(content, "comptes.xlsx")

        assert parsed.operations_read == 14
        assert [(t.broker, t.amount, t.kind) for t in parsed.transfers] == [
            ("XTB", -500.0, "deposit"),
            ("XTB", -50.0, "deposit"),
            ("XTB", -50.0, "deposit"),
            ("Mintos", -200.0, "deposit"),
            ("Mintos", -300.0, "deposit"),
            ("Amundi", -1000.0, "deposit"),
            ("Amundi", 1000.0, "withdrawal"),
            ("Amundi", 150.5, "payout"),
            ("XTB", 250.0, "withdrawal"),
        ]

    def test_not_a_bank_export(self):
        wb = openpyxl.Workbook()
        wb.active.append(["Something else"])
        buffer = io.BytesIO()
        wb.save(buffer)

        parsed = parse_bank_export(buffer.getvalue(), "x.xlsx")

        assert parsed.is_empty
        assert parsed.warnings[0].code == "import.noTableRecognised"


class TestDetect:
    def test_recognised_by_its_first_cell(self, content):
        assert detect_file(content) == FileKind.BANK_STATEMENT


class TestImport:
    def test_cash_positions_and_transfers(self, content):
        db = _session()

        batch = import_bank_file(db, content, "comptes.xlsx")

        positions = {p.account: p for p in db.execute(select(Position)).scalars()}
        assert set(positions) == {"Monabanq Compte Courant", "Monabanq Livret A"}
        current = positions["Monabanq Compte Courant"]
        assert current.broker_market_value == 1234.56
        assert current.broker_net_pl is None
        assert current.value_as_of == date(2026, 11, 12)
        assert current.opened_at == datetime(2025, 1, 3)
        instrument = db.get(Instrument, current.instrument_id)
        assert (instrument.category, instrument.not_priceable_reason) == ("CASH", "bank_account")

        transfers = db.execute(select(Transaction)).scalars().all()
        assert len(transfers) == 9
        assert {t.type for t in transfers} == {TxType.BROKER_TRANSFER}
        assert batch.transactions_inserted == 9
        totals = next(w for w in batch.warnings if w["code"] == "import.bankBrokerTransfers")
        assert totals["params"]["totals"] == (
            "Amundi -1000.00 +1000.00 = 0.00; Mintos -500.00 +0.00 = -500.00; XTB -600.00 +250.00 = -350.00"
        )

    def test_reimport_adds_nothing_and_keeps_two_identical_card_payments(self, content):
        db = _session()
        import_bank_file(db, content, "comptes.xlsx")

        again = import_bank_file(db, content, "comptes.xlsx")

        assert again.transactions_inserted == 0
        assert db.query(Position).count() == 2
        assert db.query(Transaction).filter(Transaction.comment.like("%XTB.COM%")).count() == 2

    def test_newer_export_replaces_the_balance(self, content):
        db = _session()
        import_bank_file(db, content, "comptes.xlsx")

        later = _export("20/11/2026", {CURRENT: 900.0, SAVINGS: 2000.0}, OPERATIONS)
        import_bank_file(db, later, "comptes.xlsx")

        current = db.execute(select(Position).where(Position.account == "Monabanq Compte Courant")).scalar_one()
        assert (current.broker_market_value, current.value_as_of) == (900.0, date(2026, 11, 20))
        assert current.opened_at == datetime(2025, 1, 3)

    def test_older_export_keeps_the_newer_balance(self, content):
        db = _session()
        import_bank_file(db, content, "comptes.xlsx")

        older = _export("01/10/2026", {CURRENT: 50.0, SAVINGS: 2000.0}, OPERATIONS)
        batch = import_bank_file(db, older, "comptes.xlsx")

        current = db.execute(select(Position).where(Position.account == "Monabanq Compte Courant")).scalar_one()
        assert current.broker_market_value == 1234.56
        kept = next(w for w in batch.warnings if w["code"] == "import.bankBalanceKept")
        assert "Monabanq Compte Courant (2026-11-12)" in kept["params"]["accounts"]
