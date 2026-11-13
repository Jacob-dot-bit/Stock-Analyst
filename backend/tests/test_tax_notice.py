"""Income tax notice import (Step 3u.109). Every name, address and amount
here is made up; the layout follows the notice's printed lines."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.ingest.detect import FileKind, detect_file
from app.ingest.tax_notice_import import parse_tax_notice, parse_tax_notice_pages
from app.main import app

FIRST_PAGE = [
    "Impôt sur les revenus de 2024 AVIS_IR_RG",
    "CENTRE DES FINANCES PUBLIQUES",
    "DUPONT JEAN",
    "1 RUE DE L'EXEMPLE",
    "75000 PARIS",
    "Somme qu'il vous reste à payer",
    "312 €",
]
DETAIL_PAGE = [
    "Impôt sur les revenus de 2024",
    "Déclarant 1 - Nom de naissance : DUPONT",
    "Détail des revenus Déclar. 1 Total",
    "Salaires, pensions, rentes nets.............................. 21500 21500",
    "Déduction 10% ou frais réels................................ - 2150",
    "Revenus de capitaux mobiliers............................... 340",
    "Revenu brut global.............................................. 19690",
    "Revenu imposable............................................... 19690",
    "Impôt sur les revenus soumis au barème 14 1320",
    "IMPOT NET",
    "Total de l'impôt sur le revenu net........................... 1310",
    "CALCUL DU SOLDE DE VOTRE IMPOT POUR 2024 :",
    "Impôt sur le revenu 2024 dû 53: 312",
    "INFORMATIONS COMPLEMENTAIRES",
    "Revenu fiscal de référence 25.............................. 19690",
    "PLAFOND EPARGNE RETRAITE",
    "Plafond non utilisé pour les revenus de 2023........ + 4400",
    "Plafond pour les cotisations versées en 2025....... = 12900",
]
LAST_PAGE = [
    "Impôt sur les revenus de 2024",
    "PRELEVEMENT A LA SOURCE 2025",
    "Taux pour le foyer 6,20%",
]


def _pdf(pages: list[list[str]]) -> bytes:
    """A small PDF with one text line per row, readable by pdfplumber."""
    objects: list[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>", b""]
    font = 3
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    kids = []
    for lines in pages:
        body = "BT /F1 9 Tf 40 800 Td 12 TL " + " ".join(
            "({}) Tj T*".format(line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")) for line in lines
        ) + " ET"
        stream = body.encode("cp1252")
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        content = len(objects)
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents %d 0 R "
            b"/Resources << /Font << /F1 %d 0 R >> >> >>" % (content, font)
        )
        kids.append(len(objects))
    objects[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % k for k in kids),
        len(kids),
    )
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


NOTICE = _pdf([FIRST_PAGE, DETAIL_PAGE, LAST_PAGE])


class TestParse:
    def test_named_figures(self):
        parsed = parse_tax_notice_pages(["\n".join(p) for p in (FIRST_PAGE, DETAIL_PAGE, LAST_PAGE)])

        assert parsed.income_year == 2024
        figures = parsed.figures
        assert figures.gross_income == 19690
        assert figures.taxable_income == 19690
        assert figures.scale_tax == 1320
        assert figures.net_tax == 1310
        assert figures.tax_due == 312
        assert figures.reference_income == 19690
        assert figures.balance == 312
        assert figures.withholding_rate == pytest.approx(6.2)
        assert figures.retirement_ceiling == [12900]

    def test_lines_keep_section_sign_and_columns(self):
        parsed = parse_tax_notice_pages(["\n".join(p) for p in (FIRST_PAGE, DETAIL_PAGE, LAST_PAGE)])
        by_label = {line.label: line for line in parsed.lines}

        assert by_label["Salaires, pensions, rentes nets"].values == [21500, 21500]
        assert by_label["Déduction 10% ou frais réels"].values == [-2150]
        assert by_label["Revenu fiscal de référence"].section == "INFORMATIONS COMPLEMENTAIRES"
        assert by_label["Plafond non utilisé pour les revenus de 2023"].values == [4400]
        assert by_label["Revenus de capitaux mobiliers"].section == "Détail des revenus"

    def test_address_block_is_not_kept(self):
        parsed = parse_tax_notice_pages(["\n".join(p) for p in (FIRST_PAGE, DETAIL_PAGE, LAST_PAGE)])
        kept = " ".join(f"{line.section} {line.label}" for line in parsed.lines)

        assert "DUPONT" not in kept
        assert "PARIS" not in kept
        assert "EXEMPLE" not in kept

    def test_nothing_to_pay(self):
        first = ["Impôt sur les revenus de 2024", "Vous n'avez rien à payer au titre des revenus de 2024."]
        parsed = parse_tax_notice_pages(["\n".join(first), "\n".join(DETAIL_PAGE)])
        assert parsed.figures.balance == 0

    def test_notice_with_social_levies(self):
        """The newer title, cents on the first page next to a date, and the
        investment income lines."""
        first = ["Impôt et prélèvements sociaux sur les revenus de 2025", "Somme qu'il vous reste à payer",
                 "15/09/2026 418,00 €"]
        detail = [
            "Impôt et prélèvements sociaux sur les revenus de 2025",
            "Revenus de capitaux mobiliers déclarés............... 1210",
            "Plus-values de cession de valeurs mobilières....... 4380",
            "Total des prélèvements sociaux nets................ 702",
            "Revenu fiscal de référence 25.............................. 5590",
        ]
        parsed = parse_tax_notice_pages(["\n".join(first), "\n".join(detail)])

        assert parsed.income_year == 2025
        assert parsed.figures.balance == 418
        assert parsed.figures.investment_income == 1210
        assert parsed.figures.capital_gains == 4380
        assert parsed.figures.social_levies == 702

    def test_from_pdf(self):
        parsed = parse_tax_notice(NOTICE)
        assert parsed.income_year == 2024
        assert parsed.figures.reference_income == 19690
        assert parsed.figures.withholding_rate == pytest.approx(6.2)


class TestDetect:
    def test_tax_notice(self):
        assert detect_file(NOTICE) == FileKind.TAX_NOTICE

    def test_mentions_of_savings_do_not_make_it_amundi(self):
        # The notice speaks of retirement savings; it is still a notice.
        assert detect_file(_pdf([FIRST_PAGE, DETAIL_PAGE + ["Epargne salariale"]])) == FileKind.TAX_NOTICE


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


def _upload(client, content: bytes = NOTICE):
    return client.post("/api/imports/auto", files={"file": ("avis.pdf", content, "application/pdf")})


class TestImport:
    def test_import_then_read_back(self, client):
        response = _upload(client)
        assert response.status_code == 200
        codes = [w["code"] for w in response.json()["warnings"]]
        assert codes[:2] == ["import.detected.tax_notice", "import.taxNoticeKept"]

        notices = client.get("/api/tax/notices").json()
        assert [n["income_year"] for n in notices] == [2024]
        assert notices[0]["figures"]["net_tax"] == 1310
        one = client.get("/api/tax/notices/2024").json()
        assert any(line["label"] == "Revenu imposable" for line in one["lines"])
        assert client.get("/api/tax/notices/2019").status_code == 404

    def test_same_year_again_replaces(self, client):
        _upload(client)
        corrected = _pdf([FIRST_PAGE, [l.replace("1310", "1290") for l in DETAIL_PAGE], LAST_PAGE])
        response = _upload(client, corrected)
        assert "import.taxNoticeReplaced" in [w["code"] for w in response.json()["warnings"]]
        notices = client.get("/api/tax/notices").json()
        assert len(notices) == 1
        assert notices[0]["figures"]["net_tax"] == 1290

    def test_preview_keeps_nothing(self, client):
        response = client.post("/api/imports/auto/preview", files={"file": ("avis.pdf", NOTICE, "application/pdf")})
        assert response.status_code == 200
        assert client.get("/api/tax/notices").json() == []

    def test_undo_removes_it(self, client):
        batch = _upload(client).json()
        assert client.delete(f"/api/imports/{batch['id']}").status_code == 204
        assert client.get("/api/tax/notices").json() == []
