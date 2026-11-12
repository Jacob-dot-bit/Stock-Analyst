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
)
from app.ingest.detect import FileKind, detect_file
from app.messages import MessageCode
from app.models import ImportBatch, Lot, Position, Transaction
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
        raise HTTPException(status_code=413, detail="File too large (25 MB limit).")


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
    three Amundi ones, or a bank account export. The content decides which importer runs (`ingest/detect.py`);
    the per-broker endpoints below stay for scripts that already call them.
    See DEVLOG "Step 3u.87".
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


@router.post("/xtb", response_model=ImportBatchOut)
async def import_xtb(
    file: UploadFile = File(...), db: Session = Depends(get_db)
) -> ImportBatchOut:
    """Import an xStation report (Account history → Export).

    The import is idempotent: transactions are deduplicated on the broker operation
    id, and open positions replace the previous snapshot of the same account.
    """
    content = await file.read()
    _check_upload_size(content)

    batch = import_export_file(db, content, file.filename or "export")
    return ImportBatchOut.model_validate(batch)


@router.post("/xtb/preview", response_model=ImportPreviewOut)
async def preview_xtb(
    file: UploadFile = File(...), db: Session = Depends(get_db)
) -> ImportPreviewOut:
    """Dry-run an xStation report: the same parse/dedup logic as a real import,
    rolled back instead of committed — so the counts shown are exactly what a
    real import would do. See DEVLOG "Decision 3h.1".
    """
    content = await file.read()
    _check_upload_size(content)

    summary = import_export_file(db, content, file.filename or "export", commit=False)
    return ImportPreviewOut(**summary)


@router.post("/mintos", response_model=ImportBatchOut)
async def import_mintos(file: UploadFile = File(...), db: Session = Depends(get_db)) -> ImportBatchOut:
    """Import a Mintos "Periodic statement of Financial instruments" PDF.

    No cumulative export exists — Mintos only provides one PDF per calendar
    quarter, so every quarterly file the user has must be imported
    separately (any order — everything here is deduplicated on a
    content-derived key, and Core ETF 90 holdings are always recomputed
    from every fill persisted so far, not just this file). See DEVLOG
    "Decision 3u.39".
    """
    content = await file.read()
    _check_upload_size(content)

    batch = import_mintos_file(db, content, file.filename or "mintos-statement.pdf")
    return ImportBatchOut.model_validate(batch)


@router.post("/mintos/preview", response_model=ImportPreviewOut)
async def preview_mintos(file: UploadFile = File(...), db: Session = Depends(get_db)) -> ImportPreviewOut:
    """Dry-run a Mintos statement — same parse/dedup logic as a real import,
    rolled back instead of committed."""
    content = await file.read()
    _check_upload_size(content)

    summary = import_mintos_file(db, content, file.filename or "mintos-statement.pdf", commit=False)
    return ImportPreviewOut(**summary)


@router.post("/mintos-investments", response_model=ImportBatchOut)
async def import_mintos_investments(file: UploadFile = File(...), db: Session = Depends(get_db)) -> ImportBatchOut:
    """Import Mintos's "Investments" .xlsx export (from the "My investments"
    page) — a live, point-in-time snapshot of the Mintos Core P2P
    portfolio's true current value, unlike the quarterly PDF statement
    (`/mintos` above) which can be weeks or months stale by the time it's
    imported. Complements, does not replace, that PDF import — the P2P
    aggregate always shows whichever snapshot (from either source) is
    dated latest. Idempotent: re-importing the same file (same "as of"
    date, from its filename) is a no-op. See DEVLOG "Decision 3u.43".
    """
    content = await file.read()
    _check_upload_size(content)

    batch = import_mintos_investments_file(db, content, file.filename or "Investments.xlsx")
    return ImportBatchOut.model_validate(batch)


@router.post("/mintos-investments/preview", response_model=ImportPreviewOut)
async def preview_mintos_investments(file: UploadFile = File(...), db: Session = Depends(get_db)) -> ImportPreviewOut:
    """Dry-run a Mintos Investments export — same parse/dedup logic as a
    real import, rolled back instead of committed."""
    content = await file.read()
    _check_upload_size(content)

    summary = import_mintos_investments_file(db, content, file.filename or "Investments.xlsx", commit=False)
    return ImportPreviewOut(**summary)


@router.post("/mintos-transactions", response_model=ImportBatchOut)
async def import_mintos_transactions(file: UploadFile = File(...), db: Session = Depends(get_db)) -> ImportBatchOut:
    """Import Mintos's full "account-statement" .csv export — real
    interest/bonus/fee/tax transactions, used to compute a real net gain
    (income minus costs) for the Mintos Core P2P position that doesn't
    depend on knowing a complete deposit history. Complements the value
    from `/mintos` or `/mintos-investments` — this endpoint only updates
    the gain/performance figures, never the position's value. See DEVLOG
    "Decision 3u.47".
    """
    content = await file.read()
    _check_upload_size(content)

    batch = import_mintos_transactions_file(db, content, file.filename or "account-statement.csv")
    return ImportBatchOut.model_validate(batch)


@router.post("/mintos-transactions/preview", response_model=ImportPreviewOut)
async def preview_mintos_transactions(file: UploadFile = File(...), db: Session = Depends(get_db)) -> ImportPreviewOut:
    """Dry-run a Mintos account-statement export — same parse/dedup logic
    as a real import, rolled back instead of committed."""
    content = await file.read()
    _check_upload_size(content)

    summary = import_mintos_transactions_file(db, content, file.filename or "account-statement.csv", commit=False)
    return ImportPreviewOut(**summary)


@router.post("/amundi", response_model=ImportBatchOut)
async def import_amundi(file: UploadFile = File(...), db: Session = Depends(get_db)) -> ImportBatchOut:
    """Import an Amundi ESR "Relevé annuel de situation" PDF.

    An annual snapshot, not a transaction ledger — each of the user's yearly
    statements must be imported separately. Safe in any order: an older
    statement never regresses current positions, but is still fully
    persisted. See DEVLOG "Decision 3u.39".
    """
    content = await file.read()
    _check_upload_size(content)

    batch = import_amundi_file(db, content, file.filename or "amundi-statement.pdf")
    return ImportBatchOut.model_validate(batch)


@router.post("/amundi/preview", response_model=ImportPreviewOut)
async def preview_amundi(file: UploadFile = File(...), db: Session = Depends(get_db)) -> ImportPreviewOut:
    """Dry-run an Amundi statement — same parse/dedup logic as a real
    import, rolled back instead of committed."""
    content = await file.read()
    _check_upload_size(content)

    summary = import_amundi_file(db, content, file.filename or "amundi-statement.pdf", commit=False)
    return ImportPreviewOut(**summary)


@router.post("/amundi-synthese", response_model=ImportBatchOut)
async def import_amundi_synthese(file: UploadFile = File(...), db: Session = Depends(get_db)) -> ImportBatchOut:
    """Import Amundi's "Synthese_YYYYMMDD_HHMMSS.xlsb" export (downloaded
    directly from the ESR portal) — a live snapshot of every fund holding,
    unlike the annual PDF statement (`/amundi` above) which can be many
    months stale by the time it's imported. Complements, does not replace,
    that PDF import — positions always reflect whichever export (from
    either source) is dated latest. See DEVLOG "Decision 3u.44".
    """
    content = await file.read()
    _check_upload_size(content)

    batch = import_amundi_synthese_file(db, content, file.filename or "Synthese.xlsb")
    return ImportBatchOut.model_validate(batch)


@router.post("/amundi-synthese/preview", response_model=ImportPreviewOut)
async def preview_amundi_synthese(file: UploadFile = File(...), db: Session = Depends(get_db)) -> ImportPreviewOut:
    """Dry-run an Amundi Synthese export — same parse/dedup logic as a
    real import, rolled back instead of committed."""
    content = await file.read()
    _check_upload_size(content)

    summary = import_amundi_synthese_file(db, content, file.filename or "Synthese.xlsb", commit=False)
    return ImportPreviewOut(**summary)


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
    db.delete(batch)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
