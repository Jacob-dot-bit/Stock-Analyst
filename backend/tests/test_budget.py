"""Tests for the budget view (`app/budget/`) and the bank lines the bank
import now keeps for it. Made-up names, labels and amounts in the shape of a
Monabanq export (see `test_bank_import.py`). See DEVLOG "Step 3u.92".
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.budget.categories import categorize, merchant
from app.budget.service import budget_operations, budget_summary
from app.db import Base, get_db
from app.ingest.bank_import import parse_bank_export
from app.ingest.service import import_bank_file
from app.main import app
from app.models import BankOperation, Transaction, TxType
from tests.test_bank_import import CURRENT, OPERATIONS, SAVINGS, _export


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    yield db
    db.close()


def _months(*rows: tuple) -> dict[tuple, list[tuple]]:
    return {CURRENT: list(rows)}


#: Three months of a current account, then a few days of a fourth.
BUDGET = {
    CURRENT: [
        ("2026-07-01", "VIR SEPA ACME INDUSTRIES SAS 0000123456", None, 2100),
        ("2026-07-02", "PRLV SEPA FREE MOBILE FM-123456-01 ECH/020726", -19.99, None),
        ("2026-07-03", "PRLV SEPA NETFLIX.COM 1234567", -13.49, None),
        ("2026-07-05", "PAIEMENT CB 0407 PARIS CARREFOUR MARKET CARTE 1234", -62.10, None),
        ("2026-07-06", "PAIEMENT CB 0507 PARIS LE PETIT BISTROT CARTE 1234", -28.50, None),
        ("2026-07-10", "VIR SEPA XTB S.A", -300, None),
        ("2026-07-12", "VIR VERS LIVRET A", -200, None),
        ("2026-07-15", "PAIEMENT CB 1407 PARIS AMAZON PAYMENTS CARTE 1234", -45.00, None),
        ("2026-07-20", "RETRAIT DAB 1907 PARIS CARTE 1234", -40, None),
        ("2026-07-22", "PAIEMENT CB 2107 PARIS MYSTERE SARL CARTE 1234", -12.00, None),
        ("2026-08-01", "VIR SEPA ACME INDUSTRIES SAS 0000123457", None, 2100),
        ("2026-08-02", "PRLV SEPA FREE MOBILE FM-123456-01 ECH/020826", -19.99, None),
        ("2026-08-03", "PRLV SEPA NETFLIX.COM 1234567", -13.49, None),
        ("2026-08-05", "PAIEMENT CB 0408 PARIS CARREFOUR MARKET CARTE 1234", -80.00, None),
        ("2026-08-09", "AVOIR CB 0808 PARIS AMAZON PAYMENTS CARTE 1234", None, 45.00),
        ("2026-08-14", "VIR SEPA A MARC DUPONT REMBOURSEMENT WEEKEND", -60, None),
        ("2026-09-01", "VIR SEPA ACME INDUSTRIES SAS 0000123458", None, 2150),
        ("2026-09-02", "PRLV SEPA FREE MOBILE FM-123456-01 ECH/020926", -19.99, None),
        ("2026-09-03", "PRLV SEPA NETFLIX.COM 1234567", -13.49, None),
        ("2026-09-04", "PRLV SEPA DGFIP IMPOT PAS 123456789", -150, None),
        ("2026-09-10", "VIR SEPA MINTOS MARKETPLACE AS", -100, None),
        ("2026-09-25", "VIR SEPA 0123 EPARGNE PERSO", -500, None),
        ("2026-10-02", "PRLV SEPA FREE MOBILE FM-123456-01 ECH/021026", -19.99, None),
        ("2026-10-04", "PAIEMENT CB 0310 PARIS CARREFOUR MARKET CARTE 1234", -30.00, None),
    ],
    SAVINGS: [
        ("2026-07-12", "VIR DE M JEAN EXEMPLE", None, 200),
        # Same amount as the 25/09 transfer from the current account, two
        # days later, with a label that says nothing: still my own money.
        ("2026-09-27", "VIR RECU 0123 EPARGNE PERSO", None, 500),
        ("2026-09-30", "INTERETS 3EME TRIMESTRE", None, 4.20),
    ],
}


def _import(db, operations=BUDGET, as_of="04/10/2026"):
    content = _export(as_of, {CURRENT: 1500.0, SAVINGS: 3000.0}, operations)
    return import_bank_file(db, content, "comptes.xlsx")


class TestMerchant:
    @pytest.mark.parametrize(
        ("label", "expected"),
        [
            ("PAIEMENT CB 0201 PARIS BOULANGERIE CARTE 1234", "PARIS BOULANGERIE"),
            ("PRLV SEPA FREE MOBILE FM-123456-01 ECH/020726", "FREE MOBILE"),
            ("VIR SEPA A MARC DUPONT REMBOURSEMENT WEEKEND", "MARC DUPONT REMBOURSEMENT WEEKEND"),
            ("RETRAIT DAB 1907 PARIS CARTE 1234", "PARIS"),
            ("PAIEMENT PSC 0101 MOB CANTINE EXEMPLE CARTE 1234", "CANTINE EXEMPLE"),
        ],
    )
    def test_no_card_number_nor_reference(self, label, expected):
        assert merchant(label) == expected


class TestCategorize:
    @pytest.mark.parametrize(
        ("label", "amount", "category", "kind"),
        [
            ("PAIEMENT CB 0201 PARIS CARREFOUR CITY CARTE 1234", -10, "groceries", "spending"),
            ("PRLV SEPA FREE MOBILE", -19.99, "telecom", "spending"),
            ("PRLV SEPA DGFIP IMPOT PAS", -150, "taxes", "spending"),
            ("RETRAIT DAB 1907 PARIS CARTE 1234", -40, "cash", "spending"),
            ("AVOIR CB 0808 AMAZON PAYMENTS CARTE 1234", 45, "shopping", "spending"),
            ("VIR SEPA CPAM DE PARIS", 25, "health_refund", "income"),
            ("INTERETS 2025", 12, "interest", "income"),
            ("VIR SEPA SALAIRE OCTOBRE", 2000, "salary", "income"),
            ("VIR SEPA A MARC DUPONT", -60, "transfers_out", "spending"),
            ("PAIEMENT CB 2107 PARIS MYSTERE SARL CARTE 1234", -12, "other", "spending"),
            # The hypermarket's name cut and glued, behind "MOB" (paid by phone).
            ("PAIEMENT PSC 0101 MOB CARREFHYPERXYZ CARTE 1234", -55, "groceries", "spending"),
            ("PAIEMENT CB 0101 CARREFMARKETABC CARTE 1234", -40, "groceries", "spending"),
            ("PAIEMENT CB 0101 VILLE GARAGE DU CENTRE CARTE 1234", -350, "vehicle", "spending"),
            ("PAIEMENT CB 0101 AUTO ECOLE EXEMPLE CARTE 1234", -443, "vehicle", "spending"),
            ("PAIEMENT CB 0101 ROUBAIX OVHCLOUD CARTE 1234", -6, "subscriptions", "spending"),
            ("PAIEMENT CB 0101 CZ BRNO KIWI.COM CARTE 1234", -120, "travel", "spending"),
            ("PAIEMENT CB 0101 VILLE HELLO ASSO CARTE 1234", -20, "leisure", "spending"),
            ("PAIEMENT CB 0101 VILLE CROUSABCDEF CARTE 1234", -3.3, "restaurants", "spending"),
            ("PAIEMENT CB 0101 VILLE DAFY MOTO CARTE 1234", -90, "vehicle", "spending"),
            ("PAIEMENT CB 0101 VILLE EXEMPLE CENTRE AUTO CARTE 1234", -80, "vehicle", "spending"),
            ("PRLV SEPA ECOLE EXEMPLE FRAIS DE SCOLARITE", -600, "education", "spending"),
            # Benefits paid back: negative income, not spending.
            ("PAIEMENT CB 0101 VILLE CAF VILLE CARTE 1234", -500, "benefits", "income"),
            # A PayPal transfer in is money received, not a negative purchase.
            ("VIR SEPA PAYPAL EUROPE", 870, "other_income", "income"),
            ("AVOIR CB 0101 PAYPAL CARTE 1234", 20, "shopping", "spending"),
            # Labels cut at a fixed width.
            ("VIR SEPA LV RIGA CROWDCUBE MINTO", -515, "investment", "investment"),
            ("VIR SEPA 12345678 - INVES", -500, "investment", "investment"),
        ],
    )
    def test_rules(self, label, amount, category, kind):
        found = categorize(label, amount)
        assert (found.category, found.kind) == (category, kind)

    def test_broker_and_own_transfers_are_neither_spending_nor_income(self):
        assert categorize("VIR SEPA XTB S.A", -300, broker="XTB").kind == "investment"
        assert categorize("VIR AMUNDI VIRT PARTICIPATION", 150, broker="Amundi").category == "salary"
        assert categorize("VIR LIVRET A", -100, own_transfer=True).kind == "internal"


class TestLocalRules:
    def test_parsed_and_checked_first(self, tmp_path, monkeypatch):
        from app.budget import categories

        rules = tmp_path / "budget_rules.txt"
        rules.write_text(
            "# mes mots-clés\n"
            "insurance: Courtier Exemple, ASSUREUR X\n"
            "groceries: VILLE EXEMPLE  # une supérette sans nom\n"
            "nope: IGNORED\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(categories, "LOCAL_RULES_PATH", rules)
        monkeypatch.setattr(categories, "_local_cache", None)

        assert categorize("PRLV SEPA COURTIER EXEMPLE 123", -59).category == "insurance"
        assert categorize("PAIEMENT CB 0101 VILLE EXEMPLE CARTE 1234", -12).category == "groceries"
        # Still a refund only when it looks like one.
        assert categorize("VIR SEPA ASSUREUR X INDEMNISATION", 300).category == "other_income"
        assert categorize("PAIEMENT CB 0101 IGNORED CARTE 1234", -5).category == "other"

    def test_no_file_no_rule(self, tmp_path, monkeypatch):
        from app.budget import categories

        monkeypatch.setattr(categories, "LOCAL_RULES_PATH", tmp_path / "absent.txt")
        assert categories.local_rules() == ()


class TestImportKeepsEveryLine:
    def test_every_line_and_own_transfers_flagged(self, session):
        batch = _import(session, OPERATIONS, "12/11/2026")

        lines = session.query(BankOperation).all()
        assert len(lines) == 14
        own = {line.label for line in lines if line.own_transfer}
        assert own == {"VIR LIVRET A", "VIR DE M JEAN EXEMPLE"}
        brokers = [line for line in lines if line.broker]
        assert len(brokers) == 9
        # The ledger still holds only the broker transfers.
        assert {t.type for t in session.query(Transaction)} == {TxType.BROKER_TRANSFER}
        kept = next(w for w in batch.warnings if w["code"] == "import.bankOperationsKept")
        assert kept["params"] == {"count": 14, "inserted": 14}

    def test_overlapping_export_adds_nothing_twice(self, session):
        _import(session, OPERATIONS, "12/11/2026")
        batch = _import(session, OPERATIONS, "12/11/2026")

        assert session.query(BankOperation).count() == 14
        kept = next(w for w in batch.warnings if w["code"] == "import.bankOperationsKept")
        assert kept["params"]["inserted"] == 0

    def test_holder_name_read_from_the_account_label(self):
        parsed = parse_bank_export(_export("12/11/2026", {CURRENT: 1.0, SAVINGS: 1.0}, OPERATIONS), "c.xlsx")
        assert parsed.holders == {"JEAN EXEMPLE"}


class TestSummary:
    def test_months_income_spending_invested(self, session):
        _import(session)

        summary = budget_summary(session, months=12)

        assert summary["as_of"] == date(2026, 10, 4)
        months = {m["month"]: m for m in summary["months"]}
        assert list(months) == ["2026-07", "2026-08", "2026-09", "2026-10"]
        assert months["2026-10"]["partial"] is True
        assert months["2026-07"]["partial"] is False

        july = months["2026-07"]
        assert july["income"] == 2100
        assert july["spending"] == pytest.approx(19.99 + 13.49 + 62.10 + 28.50 + 45 + 40 + 12)
        assert july["invested"] == 300
        assert july["categories"]["salary"] == 2100
        assert "internal" not in july["categories"]

        august = months["2026-08"]
        # The Amazon refund lowers shopping, it is not income.
        assert august["categories"]["shopping"] == -45
        assert august["income"] == 2100
        assert august["categories"]["transfers_out"] == 60

        september = months["2026-09"]
        # 500 out of the current account and 500 into the savings book two
        # days later: paired, neither spending nor income.
        assert september["spending"] == pytest.approx(19.99 + 13.49 + 150)
        assert september["income"] == pytest.approx(2150 + 4.20)
        assert september["invested"] == 100

    def test_salary_spotted_from_a_label_that_says_nothing(self, session):
        _import(session)

        ops = budget_operations(session, days=200)["operations"]

        acme = [op for op in ops if op["merchant"].startswith("ACME")]
        assert {op["category"] for op in acme} == {"salary"}

    def test_averages_over_full_months_only(self, session):
        _import(session)

        averages = budget_summary(session)["averages"]

        assert averages["months"] == 3
        assert averages["income"] == pytest.approx((2100 + 2100 + 2154.20) / 3, abs=0.01)

    def test_recurring_payments(self, session):
        _import(session)

        recurring = {r["merchant"]: r for r in budget_summary(session)["recurring"]}

        assert set(recurring) == {"FREE MOBILE", "NETFLIX.COM"}
        assert recurring["FREE MOBILE"]["monthly"] == 19.99
        assert recurring["FREE MOBILE"]["last"] == date(2026, 10, 2)

    def test_to_sort_lists_what_no_rule_knows(self, session):
        _import(session)

        to_sort = budget_summary(session)["to_sort"]

        assert [m["merchant"] for m in to_sort] == ["PARIS MYSTERE SARL"]

    def test_empty(self, session):
        assert budget_summary(session)["months"] == []
        assert budget_operations(session)["operations"] == []


class TestApi:
    @pytest.fixture
    def client(self, session):
        app.dependency_overrides[get_db] = lambda: session
        yield TestClient(app)
        app.dependency_overrides.clear()

    def test_summary_and_operations(self, client, session):
        _import(session)

        summary = client.get("/api/budget/summary?months=3").json()
        assert [m["month"] for m in summary["months"]] == ["2026-08", "2026-09", "2026-10"]

        ops = client.get("/api/budget/operations?days=40&category=telecom").json()
        assert [(o["date"], o["merchant"], o["amount"]) for o in ops["operations"]] == [
            ("2026-10-02", "FREE MOBILE", -19.99),
            ("2026-09-02", "FREE MOBILE", -19.99),
        ]
        assert "CARTE" not in str(client.get("/api/budget/operations?days=200").json())

    def test_one_month(self, client, session):
        _import(session)

        ops = client.get("/api/budget/operations?month=2026-08").json()

        assert ops["since"] == "2026-08-01"
        assert {o["date"][:7] for o in ops["operations"]} == {"2026-08"}
        assert len(ops["operations"]) == 6
        groceries = client.get("/api/budget/operations?month=2026-07&category=groceries").json()
        assert [o["amount"] for o in groceries["operations"]] == [-62.1]

    @pytest.mark.parametrize("month", ["2026-13", "2026-8", "août", "2026-08-01"])
    def test_bad_month_refused(self, client, month):
        assert client.get(f"/api/budget/operations?month={month}").status_code == 422

    def test_unknown_category_refused(self, client):
        assert client.get("/api/budget/operations?category=nope").status_code == 422
