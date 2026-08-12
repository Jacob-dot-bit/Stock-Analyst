"""Broker-file import endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.ingest.service import import_export_file
from app.models import ImportBatch
from app.schemas import ImportBatchOut

router = APIRouter(prefix="/api/imports", tags=["imports"])

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


@router.post("/xtb", response_model=ImportBatchOut)
async def import_xtb(
    file: UploadFile = File(...), db: Session = Depends(get_db)
) -> ImportBatchOut:
    """Import an xStation report (Account history → Export).

    The import is idempotent: transactions are deduplicated on the broker operation
    id, and open positions replace the previous snapshot of the same account.
    """
    content = await file.read()

    if not content:
        raise HTTPException(status_code=400, detail="Empty file.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (25 MB limit).")

    batch = import_export_file(db, content, file.filename or "export")
    return ImportBatchOut.model_validate(batch)


@router.get("", response_model=list[ImportBatchOut])
def list_imports(db: Session = Depends(get_db)) -> list[ImportBatchOut]:
    batches = db.execute(
        select(ImportBatch).order_by(ImportBatch.imported_at.desc()).limit(20)
    ).scalars()
    return [ImportBatchOut.model_validate(b) for b in batches]
