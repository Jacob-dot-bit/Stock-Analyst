"""Tests for `app/ingest/detect.py` and the single `/api/imports/auto` slot.

Every file is synthetic, built in memory: the real exports carry personal
data (see the other import test modules). The real Mintos account statement
of 2026-11-12 (185,641 rows, .xlsx) was checked by hand against the detector
and the parser during development — see DEVLOG "Step 3u.87".
"""

from __future__ import annotations

import io
import zipfile

import openpyxl
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.ingest.detect import FileKind, detect_file
from app.main import app
from scripts.make_demo_export import build_demo_workbook

_ACCOUNT_STATEMENT_HEADER = ["Date", "ID de transaction :", "Détails", "Mouvement", "Solde", "Devise", "Type de paiement"]


def _workbook(header: list[str], rows: list[list[object]]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(header)
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _pdf(text: str) -> bytes:
    """Smallest PDF pdfplumber can read text from — one page, one line."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
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


def _fake_xlsb() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.bin", b"\x83\x01\x00")
    return buffer.getvalue()


def _demo_xtb() -> bytes:
    buffer = io.BytesIO()
    build_demo_workbook().save(buffer)
    return buffer.getvalue()


class TestDetectFile:
    def test_xtb_report(self):
        assert detect_file(_demo_xtb()) == FileKind.XTB

    def test_mintos_investments(self):
        content = _workbook(["ID", "ISIN", "Montant investi", "Devise"], [["id", "LV1", 10.0, "EUR"]])
        assert detect_file(content) == FileKind.MINTOS_INVESTMENTS

    def test_mintos_account_statement_xlsx(self):
        content = _workbook(_ACCOUNT_STATEMENT_HEADER, [["2026-11-12 10:00:00", "t", "d", 0.05, 1.0, "EUR", "Bonus"]])
        assert detect_file(content) == FileKind.MINTOS_ACCOUNT_STATEMENT

    def test_mintos_account_statement_csv(self):
        content = ("﻿" + ",".join(_ACCOUNT_STATEMENT_HEADER) + "\n2026-11-12 10:00:00,t,d,0.05,1,EUR,Bonus\n").encode()
        assert detect_file(content) == FileKind.MINTOS_ACCOUNT_STATEMENT

    def test_amundi_synthese(self):
        assert detect_file(_fake_xlsb()) == FileKind.AMUNDI_SYNTHESE

    def test_mintos_pdf(self):
        assert detect_file(_pdf("Mintos Periodic statement of Financial instruments")) == FileKind.MINTOS_STATEMENT

    def test_amundi_pdf(self):
        assert detect_file(_pdf("Amundi Epargne Salariale - Releve annuel")) == FileKind.AMUNDI_STATEMENT

    @pytest.mark.parametrize("content", [_pdf("Some unrelated invoice"), b"\x00\x01binary junk", b"PK not a zip"])
    def test_anything_else_is_not_recognised(self, content):
        assert detect_file(content) is None

    def test_filename_plays_no_part(self):
        # Same bytes, whatever the name — detect_file never even sees it.
        content = _workbook(_ACCOUNT_STATEMENT_HEADER, [])
        assert detect_file(content) == FileKind.MINTOS_ACCOUNT_STATEMENT


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


class TestAutoImportApi:
    def test_preview_names_the_detected_file_first(self, client):
        content = _workbook(
            _ACCOUNT_STATEMENT_HEADER,
            [["2026-11-12 10:00:00", "t", "d", 0.05, 1.0, "EUR", "Intérêt perçu"]],
        )
        response = client.post(
            "/api/imports/auto/preview",
            files={"file": ("20261112-account-statement.xlsx", content)},
        )

        assert response.status_code == 200
        assert response.json()["warnings"][0]["code"] == "import.detected.mintos_account_statement"

    def test_xtb_through_the_single_slot_imports_positions(self, client):
        response = client.post("/api/imports/auto", files={"file": ("demo.xlsx", _demo_xtb())})

        assert response.status_code == 200
        body = response.json()
        assert body["warnings"][0]["code"] == "import.detected.xtb"
        assert body["positions_found"] > 0

    def test_unrecognised_file_preview_says_so(self, client):
        response = client.post("/api/imports/auto/preview", files={"file": ("x.bin", b"\x00\x01junk")})

        assert response.status_code == 200
        assert [w["code"] for w in response.json()["warnings"]] == ["import.fileNotRecognised"]

    def test_unrecognised_file_import_is_refused(self, client):
        response = client.post("/api/imports/auto", files={"file": ("x.bin", b"\x00\x01junk")})

        assert response.status_code == 400
