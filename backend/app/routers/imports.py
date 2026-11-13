"""Broker-file import endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.ingest.service import (
    import_amundi_file,
    import_amundi_operations_file,
    import_amundi_synthese_file,
    import_bank_file,
    import_export_file,
    import_mintos_file,
    import_mintos_investments_file,
    import_mintos_transactions_file,
    import_mintos_tax_report_file,
    import_tax_notice_file,
)
from app.ingest.detect import FileKind, detect_file
from app.messages import MessageCode
from app.models import ImportBatch, Lot, MintosTaxReport, Position, TaxNotice, Transaction
from app.schemas import ImportBatchOut, ImportPreviewOut, MessageOut

router = APIRouter(prefix="/api/imports", tags=["imports"])

#: Raised from 25MB (DEVLOG "Decision 3u.47") once a real Mintos full
#: "account-statement" export (every individual transaction, not the
#: quarterly aggregate PDF) came in at ~32MB for one real account over
#: ~20 months — a legitimate file, not something to reject.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def _check_upload_size(content: bytes) -> None:
    if not content:
        raise HTTPException(status_code=400, detail="Empty file.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"File too large ({MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit).")


#: Importer and fallback filename per recognised file. The filename matters
#: only to the XTB parser, which picks .xlsx or .csv reading from it.
_IMPORTERS = {
    FileKind.XTB: (import_export_file, "export.xlsx"),
    FileKind.MINTOS_STATEMENT: (import_mintos_file, "mintos-statement.pdf"),
    FileKind.MINTOS_INVESTMENTS: (import_mintos_investments_file, "Investments.xlsx"),
    FileKind.MINTOS_ACCOUNT_STATEMENT: (import_mintos_transactions_file, "account-statement.csv"),
    FileKind.AMUNDI_STATEMENT: (import_amundi_file, "amundi-statement.pdf"),
    FileKind.AMUNDI_SYNTHESE: (import_amundi_synthese_file, "Synthese.xlsb"),
    FileKind.AMUNDI_OPERATIONS: (import_amundi_operations_file, "ExportOperations.xlsb"),
    FileKind.BANK_STATEMENT: (import_bank_file, "comptes.xlsx"),
    FileKind.TAX_NOTICE: (import_tax_notice_file, "avis-impot.pdf"),
    FileKind.MINTOS_TAX_REPORT: (import_mintos_tax_report_file, "mintos-tax-report.pdf"),
}


def _fallback_name(kind: FileKind, content: bytes) -> str:
    if kind == FileKind.XTB and not content.startswith(b"PK"):
        return "export.csv"
    return _IMPORTERS[kind][1]


def _detected(kind: FileKind) -> MessageOut:
    return MessageOut(code=f"{MessageCode.FILE_DETECTED}.{kind.value}")


@router.post("/auto", response_model=ImportBatchOut)
async def import_auto(file: UploadFile = File(...), db: Session = Depends(get_db)) -> ImportBatchOut:
    """Import any supported export — XTB, the three Mintos files or the
    three Amundi ones, or a bank account export. The content decides which importer runs (`ingest/detect.py`).
    The only upload route: the per-broker ones went in Step 3u.93. See DEVLOG "Step 3u.87".
    """
    content = await file.read()
    _check_upload_size(content)

    kind = detect_file(content)
    if kind is None:
        raise HTTPException(status_code=400, detail="Not a recognised broker export.")
    importer = _IMPORTERS[kind][0]
    batch = importer(db, content, file.filename or _fallback_name(kind, content))
    out = ImportBatchOut.model_validate(batch)
    out.warnings.insert(0, _detected(kind))
    return out


@router.post("/auto/preview", response_model=ImportPreviewOut)
async def preview_auto(file: UploadFile = File(...), db: Session = Depends(get_db)) -> ImportPreviewOut:
    """Dry-run any supported export: detection, then the same parse/dedup
    logic as a real import, rolled back instead of committed. The detected
    file type is the first line of the report."""
    content = await file.read()
    _check_upload_size(content)

    kind = detect_file(content)
    if kind is None:
        return ImportPreviewOut(
            filename=file.filename or "",
            positions_found=0,
            transactions_found=0,
            transactions_inserted=0,
            warnings=[MessageOut(code=MessageCode.FILE_NOT_RECOGNISED)],
            sections=[],
            accounts=[],
        )
    importer = _IMPORTERS[kind][0]
    preview = ImportPreviewOut(**importer(db, content, file.filename or _fallback_name(kind, content), commit=False))
    preview.warnings.insert(0, _detected(kind))
    return preview


@router.get("", response_model=list[ImportBatchOut])
def list_imports(db: Session = Depends(get_db)) -> list[ImportBatchOut]:
    batches = db.execute(
        select(ImportBatch).order_by(ImportBatch.imported_at.desc()).limit(20)
    ).scalars()
    return [ImportBatchOut.model_validate(b) for b in batches]


@router.delete("/{import_id}", status_code=status.HTTP_204_NO_CONTENT)
def undo_import(import_id: int, db: Session = Depends(get_db)) -> Response:
    """Delete everything a given import created — only ever allowed for the most
    recent import. See DEVLOG "Decision 3h.1" for why: Lot/Transaction dedup is
    keyed globally on (external_id, type), so a row's import_batch_id records
    which import first inserted it, not which import owns it. Undoing anything
    but the newest import risks deleting data a later import's export still
    supports, just deduped away rather than re-inserted.
    """
    batch = db.get(ImportBatch, import_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Import not found.")

    latest_id = db.execute(select(func.max(ImportBatch.id))).scalar_one()
    if import_id != latest_id:
        raise HTTPException(
            status_code=400,
            detail="Only the most recent import can be undone. Undo newer imports first.",
        )

    db.execute(delete(Position).where(Position.import_batch_id == import_id))
    db.execute(delete(Lot).where(Lot.import_batch_id == import_id))
    db.execute(delete(Transaction).where(Transaction.import_batch_id == import_id))
    db.execute(delete(TaxNotice).where(TaxNotice.import_batch_id == import_id))
    db.execute(delete(MintosTaxReport).where(MintosTaxReport.import_batch_id == import_id))
    db.delete(batch)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
