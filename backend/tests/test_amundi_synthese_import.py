"""Tests for `app/ingest/amundi_synthese_import.py`'s pure parsing and
`app/ingest/service.py::import_amundi_synthese_file`'s persistence.

Deliberately does not commit a copy of the user's real Amundi Synthese
export as a test fixture — same personal-data reasoning as
`test_amundi_import.py` and `test_mintos_investments_import.py`. The real
file was cross-checked manually during development (DEVLOG "Decision
3u.44"): summing its `Montant évalué` column across every fund matched
the account's real total (reported by the user directly) closely.

`pyxlsb` has no writer (only a reader), so there is no way to build a
small synthetic `.xlsb` file the way the other importers' tests build a
synthetic `.xlsx`/PDF. Parsing tests here instead patch
`amundi_synthese_import.open_workbook` itself with a mock exposing the
same `.sheets`/`.get_sheet(...).rows()` shape `pyxlsb` returns, fed with
real-shaped row tuples (the actual header/field-name/data-row structure
observed in the real export) — exercising `parse_amundi_synthese_export`'s
own row-processing logic exactly as it runs, without touching the binary
file format at all.
"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.ingest.amundi_import import ParsedAmundiExport
from app.ingest.amundi_synthese_import import (
    _account_for_dispositif,
    _extract_filename_datetime,
    parse_amundi_synthese_export,
)
from app.ingest.service import import_amundi_file, import_amundi_synthese_file
from app.models import Instrument, Position

from tests.test_amundi_import import _fund


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    yield session
    session.close()


class TestExtractFilenameDatetime:
    def test_real_shaped_filename(self):
        assert _extract_filename_datetime("Synthese_20260908_104534.xlsb") == datetime(2026, 9, 8, 10, 45, 34)

    def test_no_match_returns_none(self):
        assert _extract_filename_datetime("export.xlsb") is None


class TestAccountForDispositif:
    def test_perco_label(self):
        assert _account_for_dispositif("PERCO LIBRE Entreprise") == "Amundi PERCO"

    def test_peg_label(self):
        assert _account_for_dispositif("Plan Epargne Groupe 5 ans") == "Amundi PEG"


def _fake_sheet(rows: list[list[object]]) -> MagicMock:
    sheet = MagicMock()
    sheet.rows.return_value = [[MagicMock(v=v) for v in row] for row in rows]
    sheet.__enter__ = MagicMock(return_value=sheet)
    sheet.__exit__ = MagicMock(return_value=False)
    return sheet


_HEADER = [
    None, "Libellé dispositif", None, "Libellé FCPE", "Échéance", "nombre de parts", "VL", "Montant évalué",
    "Montant Total de l'échéance",
]
_FIELD_HEADER = [
    "posSalLigneTotale", "posSalLibelleDispositif", "posSalLibelleEntreprise", "posSalLibelleFonds",
    "posSalDtEcheance", "posSalNbPartsEcheance", "posSalVl", "posSalMtBrutEcheance", "posSalTotalMtBrutEcheance",
]


def _fund_row(dispositif: str, fund: str, echeance: str, quantity: float, vl: float, value: float) -> list[object]:
    return [None, dispositif, "SOCIETE GENERIQUE", fund, echeance, quantity, vl, value, None]


def _total_row(echeance: str, value: float) -> list[object]:
    return [" Ligne Total", None, None, None, echeance, None, None, None, value]


class TestParseAmundiSyntheseExport:
    def test_sums_multiple_tranches_of_the_same_fund(self):
        rows = [
            _HEADER,
            _FIELD_HEADER,
            _fund_row("Plan Epargne Groupe 5 ans", "FONDS ACTIONNARIAT SALARIE", "01/06/2031", 68.0000, 56.0000, 4600.00),
            _total_row("01/06/2031", 4600.00),
            _fund_row("Plan Epargne Groupe 5 ans", "FONDS ACTIONNARIAT SALARIE", "01/06/2030", 145.0000, 56.0000, 9800.00),
            _total_row("01/06/2030", 9800.00),
        ]
        with patch("app.ingest.amundi_synthese_import.open_workbook") as mock_open:
            mock_wb = MagicMock()
            mock_wb.sheets = ["Donnees", "Mes avoirs par échéance"]
            mock_wb.get_sheet.return_value = _fake_sheet(rows)
            mock_wb.__enter__ = MagicMock(return_value=mock_wb)
            mock_wb.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_wb

            result = parse_amundi_synthese_export(b"fake", "Synthese_20260908_104534.xlsb")

        assert result.as_of == date(2026, 9, 8)
        assert len(result.funds) == 1
        fund = result.funds[0]
        assert fund.account == "Amundi PEG"
        assert fund.quantity == pytest.approx(68.0000 + 145.0000)
        assert fund.gross_value == pytest.approx(4600.00 + 9800.00)
        assert fund.unit_price == pytest.approx(56.0000)
        assert fund.estimated_gain_loss is None

    def test_separates_peg_and_perco_funds(self):
        rows = [
            _HEADER,
            _FIELD_HEADER,
            _fund_row("PERCO LIBRE Entreprise", "FONDS RETRAITE PERCO", "RETRAITE", 14.50000, 16.75000, 275.00),
            _total_row("RETRAITE", 275.00),
            _fund_row("Plan Epargne Groupe 5 ans", "FONDS MONETAIRE PEG", "01/06/2028", 18.5000, 10.75000, 310.00),
            _total_row("01/06/2028", 310.00),
        ]
        with patch("app.ingest.amundi_synthese_import.open_workbook") as mock_open:
            mock_wb = MagicMock()
            mock_wb.sheets = ["Donnees", "Mes avoirs par échéance"]
            mock_wb.get_sheet.return_value = _fake_sheet(rows)
            mock_wb.__enter__ = MagicMock(return_value=mock_wb)
            mock_wb.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_wb

            result = parse_amundi_synthese_export(b"fake", "Synthese_20260908_104534.xlsb")

        accounts = {f.account for f in result.funds}
        assert accounts == {"Amundi PERCO", "Amundi PEG"}

    def test_ligne_total_rows_are_not_double_counted(self):
        rows = [
            _HEADER,
            _FIELD_HEADER,
            _fund_row("Plan Epargne Groupe 5 ans", "FONDS MONETAIRE PEG", "01/06/2028", 20.0, 10.90, 240.0),
            _total_row("01/06/2028", 240.0),
        ]
        with patch("app.ingest.amundi_synthese_import.open_workbook") as mock_open:
            mock_wb = MagicMock()
            mock_wb.sheets = ["Donnees", "Mes avoirs par échéance"]
            mock_wb.get_sheet.return_value = _fake_sheet(rows)
            mock_wb.__enter__ = MagicMock(return_value=mock_wb)
            mock_wb.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_wb

            result = parse_amundi_synthese_export(b"fake", "Synthese_20260908_104534.xlsb")

        assert len(result.funds) == 1
        assert result.funds[0].gross_value == pytest.approx(240.0)

    def test_no_date_in_filename_is_a_warning(self):
        result = parse_amundi_synthese_export(b"fake", "Synthese.xlsb")

        assert result.is_empty
        assert result.warnings

    def test_missing_sheet_is_a_warning(self):
        with patch("app.ingest.amundi_synthese_import.open_workbook") as mock_open:
            mock_wb = MagicMock()
            mock_wb.sheets = ["Donnees"]
            mock_wb.__enter__ = MagicMock(return_value=mock_wb)
            mock_wb.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_wb

            result = parse_amundi_synthese_export(b"fake", "Synthese_20260908_104534.xlsb")

        assert result.is_empty
        assert result.warnings

    def test_unreadable_content_is_a_warning_not_a_crash(self):
        with patch("app.ingest.amundi_synthese_import.open_workbook", side_effect=ValueError("bad file")):
            result = parse_amundi_synthese_export(b"not really an xlsb", "Synthese_20260908_104534.xlsb")

        assert result.is_empty
        assert result.warnings


class TestImportAmundiSyntheseFilePersistence:
    """Persistence behaviour, independent of the .xlsb layer — patches
    `parse_amundi_synthese_export` with a synthetic `ParsedAmundiExport`,
    reusing the shared `_persist_amundi_export` path the PDF importer also
    uses (see `test_amundi_import.py`)."""

    def test_creates_a_position_from_a_synthese_snapshot(self, db):
        parsed = ParsedAmundiExport(
            as_of=date(2026, 9, 8),
            funds=[_fund("FONDS MONETAIRE PEG", "Amundi PEG", 18.5000, 10.75000, 310.00, None)],
        )
        with patch("app.ingest.service.parse_amundi_synthese_export", return_value=parsed):
            import_amundi_synthese_file(db, b"fake", "Synthese_20260908_104534.xlsb")

        position = db.execute(select(Position)).scalar_one()
        assert position.broker_market_value == 310.00
        assert position.quantity == pytest.approx(18.5000)
        # The date *this* fund's declared value is as of — distinct from
        # `opened_at` ("since held"), drives the freshness caveat in
        # `routers/portfolio.py`. See DEVLOG "Decision 3u.50".
        assert position.value_as_of == date(2026, 9, 8)
        instrument = db.get(Instrument, position.instrument_id)
        assert instrument.category == "FUND"

    def test_a_more_recent_synthese_supersedes_an_older_pdf(self, db):
        """The whole point of this new import path: a stale annual PDF
        must not keep winning once a fresher live snapshot exists."""
        pdf_parsed = ParsedAmundiExport(
            as_of=date(2025, 12, 31),
            funds=[_fund("FONDS ACTIONNARIAT SALARIE", "Amundi PEG", 150.0000, 32.00, 5800.00, 700.00)],
        )
        with patch("app.ingest.service.parse_amundi_statement", return_value=pdf_parsed):
            import_amundi_file(db, b"fake-pdf", "annual.pdf")

        position = db.execute(select(Position)).scalar_one()
        assert position.broker_market_value == 5800.00
        assert position.value_as_of == date(2025, 12, 31)

        synthese_parsed = ParsedAmundiExport(
            as_of=date(2026, 9, 8),
            funds=[_fund("FONDS ACTIONNARIAT SALARIE", "Amundi PEG", 220.0000, 56.0000, 15000.00, None)],
        )
        with patch("app.ingest.service.parse_amundi_synthese_export", return_value=synthese_parsed):
            import_amundi_synthese_file(db, b"fake-xlsb", "Synthese_20260908_104534.xlsb")

        position = db.execute(select(Position)).scalar_one()
        assert position.broker_market_value == pytest.approx(15000.00)
        assert position.value_as_of == date(2026, 9, 8)

    def test_an_older_synthese_does_not_regress_a_newer_pdf(self, db):
        synthese_parsed = ParsedAmundiExport(
            as_of=date(2024, 1, 1),
            funds=[_fund("FONDS MONETAIRE PEG", "Amundi PEG", 10.0, 10.0, 100.0, None)],
        )
        with patch("app.ingest.service.parse_amundi_synthese_export", return_value=synthese_parsed):
            import_amundi_synthese_file(db, b"fake-xlsb", "Synthese_20240101_000000.xlsb")

        pdf_parsed = ParsedAmundiExport(
            as_of=date(2025, 12, 31),
            funds=[_fund("FONDS MONETAIRE PEG", "Amundi PEG", 18.5000, 10.75000, 310.00, 25.00)],
        )
        with patch("app.ingest.service.parse_amundi_statement", return_value=pdf_parsed):
            import_amundi_file(db, b"fake-pdf", "annual.pdf")

        assert db.execute(select(Position)).scalar_one().broker_market_value == 310.00

    def test_a_fresh_synthese_does_not_reset_since_to_today(self, db):
        """`opened_at` ("Depuis" in the UI) must reflect this fund's
        earliest recorded snapshot, not this import's own as-of date -- a
        fresh live Synthese import making it look like the position was
        just opened today was a real, user-caught bug. See DEVLOG
        "Decision 3u.49"."""
        pdf_parsed = ParsedAmundiExport(
            as_of=date(2023, 12, 31),
            funds=[_fund("FONDS MONETAIRE PEG", "Amundi PEG", 18.5000, 9.80, 285.00, 6.00)],
        )
        with patch("app.ingest.service.parse_amundi_statement", return_value=pdf_parsed):
            import_amundi_file(db, b"fake-pdf", "annual-2023.pdf")

        synthese_parsed = ParsedAmundiExport(
            as_of=date(2026, 9, 8),
            funds=[_fund("FONDS MONETAIRE PEG", "Amundi PEG", 18.5000, 10.75000, 310.00, None)],
        )
        with patch("app.ingest.service.parse_amundi_synthese_export", return_value=synthese_parsed):
            import_amundi_synthese_file(db, b"fake-xlsb", "Synthese_20260908_104534.xlsb")

        position = db.execute(select(Position)).scalar_one()
        assert position.broker_market_value == 310.00  # the fresh value still wins
        assert position.opened_at == datetime(2023, 12, 31)  # but "since" stays the real start


class TestAmundiProRataFallbackGain:
    """When a fund's gain isn't disclosed by its source (always true for
    the Synthese export — Decision 3u.44), fall back to a pro-rata share
    of the account's (current value − known contributions), clearly
    labelled via `performance_note` — never presented as an ordinary,
    unqualified P&L. See DEVLOG "Decision 3u.47"."""

    def test_fallback_gain_when_contributions_are_known(self, db):
        # Seed real contribution history via a prior PDF import.
        pdf_parsed = ParsedAmundiExport(
            as_of=date(2023, 12, 31),
            funds=[_fund("FONDS MONETAIRE PEG", "Amundi PEG", 10.0, 10.0, 100.0, 10.0)],
            aggregate_totals={"Amundi PEG": {"versements_volontaires": 100.0, "abondement_net": 50.0}},
        )
        with patch("app.ingest.service.parse_amundi_statement", return_value=pdf_parsed):
            import_amundi_file(db, b"fake-pdf", "annual-2023.pdf")

        # A later Synthese snapshot, no gain data, higher value.
        synthese_parsed = ParsedAmundiExport(
            as_of=date(2026, 9, 8),
            funds=[_fund("FONDS MONETAIRE PEG", "Amundi PEG", 20.0, 15.0, 300.0, None)],
        )
        with patch("app.ingest.service.parse_amundi_synthese_export", return_value=synthese_parsed):
            import_amundi_synthese_file(db, b"fake-xlsb", "Synthese_20260908_104534.xlsb")

        position = db.execute(select(Position)).scalar_one()
        # contributions = 100 + 50 = 150; account value = 300 -> gain = 150
        assert position.broker_net_pl == pytest.approx(150.0)
        assert position.broker_net_pl_pct == pytest.approx(100.0)
        assert position.performance_note == {
            "code": "performance.amundiApproximateGain",
            "params": {"account": "Amundi PEG", "since": "2023-12-31"},
        }

    def test_fallback_gain_is_split_pro_rata_across_multiple_funds(self, db):
        # Both funds' quantities change between the two imports, so neither
        # qualifies for the exact per-fund snapshot calculation (Decision
        # 3u.48) -- this test stays isolated to the pure pro-rata path.
        pdf_parsed = ParsedAmundiExport(
            as_of=date(2023, 12, 31),
            funds=[_fund("FUND A", "Amundi PEG", 1.0, 100.0, 100.0, 0.0), _fund("FUND B", "Amundi PEG", 2.0, 50.0, 100.0, 0.0)],
            aggregate_totals={"Amundi PEG": {"versements_volontaires": 100.0}},
        )
        with patch("app.ingest.service.parse_amundi_statement", return_value=pdf_parsed):
            import_amundi_file(db, b"fake-pdf", "annual-2023.pdf")

        # Later Synthese: FUND A worth 3x FUND B, no gain data for either.
        synthese_parsed = ParsedAmundiExport(
            as_of=date(2026, 9, 8),
            funds=[
                _fund("FUND A", "Amundi PEG", 3.0, 100.0, 300.0, None),
                _fund("FUND B", "Amundi PEG", 1.0, 100.0, 100.0, None),
            ],
        )
        with patch("app.ingest.service.parse_amundi_synthese_export", return_value=synthese_parsed):
            import_amundi_synthese_file(db, b"fake-xlsb", "Synthese_20260908_104534.xlsb")

        positions = {
            db.get(Instrument, p.instrument_id).name: p
            for p in db.execute(select(Position)).scalars().all()
        }
        # account value = 400, contributions = 100 -> account gain = 300,
        # split 3:1 by value share -> A gets 225, B gets 75.
        assert positions["FUND A"].broker_net_pl == pytest.approx(225.0)
        assert positions["FUND B"].broker_net_pl == pytest.approx(75.0)
        assert positions["FUND A"].broker_net_pl + positions["FUND B"].broker_net_pl == pytest.approx(300.0)

    def test_no_fallback_without_any_known_contributions(self, db):
        """No prior PDF import at all — nothing to approximate from, so
        the gain stays honestly unknown rather than guessed at."""
        synthese_parsed = ParsedAmundiExport(
            as_of=date(2026, 9, 8),
            funds=[_fund("FONDS MONETAIRE PEG", "Amundi PEG", 20.0, 15.0, 300.0, None)],
        )
        with patch("app.ingest.service.parse_amundi_synthese_export", return_value=synthese_parsed):
            import_amundi_synthese_file(db, b"fake-xlsb", "Synthese_20260908_104534.xlsb")

        position = db.execute(select(Position)).scalar_one()
        assert position.broker_net_pl is None
        assert position.performance_note is None

    def test_a_real_disclosed_gain_is_never_overridden_by_the_fallback(self, db):
        """The annual PDF's own real gain figure must win outright — the
        fallback only ever fills a genuine gap, never second-guesses a
        real disclosed figure."""
        pdf_parsed = ParsedAmundiExport(
            as_of=date(2023, 12, 31),
            funds=[_fund("FONDS MONETAIRE PEG", "Amundi PEG", 10.0, 10.0, 100.0, 10.0)],
            aggregate_totals={"Amundi PEG": {"versements_volontaires": 500.0}},  # would imply a large loss if used
        )
        with patch("app.ingest.service.parse_amundi_statement", return_value=pdf_parsed):
            import_amundi_file(db, b"fake-pdf", "annual-2023.pdf")

        position = db.execute(select(Position)).scalar_one()
        assert position.broker_net_pl == pytest.approx(10.0)
        assert position.performance_note is None


class TestAmundiRealGainSinceSnapshot:
    """When a fund's current source discloses no gain (always true for the
    Synthese export) but that same fund's quantity hasn't changed since a
    prior import that *did* disclose one, the exact gain since that
    snapshot is used instead of the cruder account-level pro-rata. See
    DEVLOG "Decision 3u.48"."""

    def test_unchanged_quantity_uses_exact_gain_since_last_disclosed_snapshot(self, db):
        pdf_parsed = ParsedAmundiExport(
            as_of=date(2024, 12, 31),
            funds=[_fund("FONDS MONETAIRE PEG", "Amundi PEG", 18.5000, 8.90, 260.00, 6.50)],
        )
        with patch("app.ingest.service.parse_amundi_statement", return_value=pdf_parsed):
            import_amundi_file(db, b"fake-pdf", "annual-2024.pdf")

        # Same quantity, no gain disclosed, worth more now.
        synthese_parsed = ParsedAmundiExport(
            as_of=date(2026, 9, 8),
            funds=[_fund("FONDS MONETAIRE PEG", "Amundi PEG", 18.5000, 10.90, 290.00, None)],
        )
        with patch("app.ingest.service.parse_amundi_synthese_export", return_value=synthese_parsed):
            import_amundi_synthese_file(db, b"fake-xlsb", "Synthese_20260908_104534.xlsb")

        position = db.execute(select(Position)).scalar_one()
        # 2024 cost basis = 260.00 - 6.50 = 253.50; gain now = 290.00 - 253.50
        assert position.broker_net_pl == pytest.approx(36.5)
        assert position.performance_note == {
            "code": "performance.amundiRealGainSinceSnapshot",
            "params": {"since": "2024-12-31"},
        }

    def test_changed_quantity_falls_back_to_pro_rata_instead_of_exact(self, db):
        pdf_parsed = ParsedAmundiExport(
            as_of=date(2024, 12, 31),
            funds=[_fund("FONDS MONETAIRE PEG", "Amundi PEG", 20.0, 10.0, 200.0, 6.50)],
            aggregate_totals={"Amundi PEG": {"versements_volontaires": 195.0}},
        )
        with patch("app.ingest.service.parse_amundi_statement", return_value=pdf_parsed):
            import_amundi_file(db, b"fake-pdf", "annual-2024.pdf")

        # A new contribution changed the quantity -- the 2024 snapshot no
        # longer isolates this fund's own price movement, so it must not
        # be trusted for an exact calculation.
        synthese_parsed = ParsedAmundiExport(
            as_of=date(2026, 9, 8),
            funds=[_fund("FONDS MONETAIRE PEG", "Amundi PEG", 25.0, 10.0, 250.0, None)],
        )
        with patch("app.ingest.service.parse_amundi_synthese_export", return_value=synthese_parsed):
            import_amundi_synthese_file(db, b"fake-xlsb", "Synthese_20260908_104534.xlsb")

        position = db.execute(select(Position)).scalar_one()
        # pro-rata: contributions=195, value=250 -> gain=55
        assert position.broker_net_pl == pytest.approx(55.0)
        assert position.performance_note["code"] == "performance.amundiApproximateGain"

    def test_exact_and_fallback_gains_coexist_within_the_same_account(self, db):
        """One fund's quantity stays put (exact anchor available) while a
        sibling fund's changes (falls back to pro-rata) -- each fund's
        note must reflect its own calculation, not the account's."""
        pdf_parsed = ParsedAmundiExport(
            as_of=date(2024, 12, 31),
            funds=[
                _fund("STABLE FUND", "Amundi PEG", 1.0, 100.0, 100.0, 10.0),
                _fund("GROWING FUND", "Amundi PEG", 1.0, 100.0, 100.0, 0.0),
            ],
            aggregate_totals={"Amundi PEG": {"versements_volontaires": 180.0}},
        )
        with patch("app.ingest.service.parse_amundi_statement", return_value=pdf_parsed):
            import_amundi_file(db, b"fake-pdf", "annual-2024.pdf")

        synthese_parsed = ParsedAmundiExport(
            as_of=date(2026, 9, 8),
            funds=[
                _fund("STABLE FUND", "Amundi PEG", 1.0, 100.0, 100.0, None),
                _fund("GROWING FUND", "Amundi PEG", 2.0, 100.0, 200.0, None),
            ],
        )
        with patch("app.ingest.service.parse_amundi_synthese_export", return_value=synthese_parsed):
            import_amundi_synthese_file(db, b"fake-xlsb", "Synthese_20260908_104534.xlsb")

        positions = {
            db.get(Instrument, p.instrument_id).name: p
            for p in db.execute(select(Position)).scalars().all()
        }
        # STABLE FUND: unchanged quantity -> exact gain since 2024-12-31
        # (cost basis 100 - 10 = 90, still worth 100 -> gain 10).
        assert positions["STABLE FUND"].broker_net_pl == pytest.approx(10.0)
        assert positions["STABLE FUND"].performance_note["code"] == "performance.amundiRealGainSinceSnapshot"
        # GROWING FUND: quantity changed -> pro-rata of (account value 300
        # - contributions 180 = 120), by value share (200/300 -> 80).
        assert positions["GROWING FUND"].broker_net_pl == pytest.approx(80.0)
        assert positions["GROWING FUND"].performance_note["code"] == "performance.amundiApproximateGain"
