"""Backup and restore for the local SQLite database — see
`app/backup/service.py` for the design (why restore refuses a schema
mismatch, why a backup is a plain file copy, retention). See DEVLOG
"Decision 3u.29".
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status

from app.backup.service import (
    BackupInfo,
    BackupNotFoundError,
    SchemaMismatchError,
    create_backup,
    list_backups,
    restore_backup,
)
from app.schemas import BackupOut

router = APIRouter(prefix="/api/backup", tags=["backup"])


def _out(info: BackupInfo) -> BackupOut:
    return BackupOut(filename=info.filename, created_at=info.created_at, size_bytes=info.size_bytes)


@router.post("", response_model=BackupOut, status_code=status.HTTP_201_CREATED)
def create_backup_endpoint() -> BackupOut:
    return _out(create_backup())


@router.get("", response_model=list[BackupOut])
def list_backups_endpoint() -> list[BackupOut]:
    return [_out(info) for info in list_backups()]


@router.post("/{filename}/restore", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def restore_backup_endpoint(filename: str) -> Response:
    try:
        restore_backup(filename)
    except BackupNotFoundError:
        raise HTTPException(status_code=404, detail="Backup not found.")
    except SchemaMismatchError as err:
        raise HTTPException(status_code=409, detail=str(err))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
