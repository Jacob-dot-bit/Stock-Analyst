"""Backup and restore for the local SQLite database.

A personal, single-user, local-only app (see `main.py`'s loopback-only
middleware) has no server-side redundancy at all: the one `.db` file *is*
the portfolio's entire history, and there had been no way to recover it
short of the OS's own file history, if any. Requested as the top item of
the roadmap established in DEVLOG "Decision 3u.28"'s addendum, once
dividends/accounts/allocation targets/manual corrections made clear how
much now lives in that one file.

**A backup is a plain timestamped copy of the `.db` file** — nothing more
sophisticated, and no `.env`/API keys ever touch it, since only the
database file is ever read or written here.

**Restore refuses a schema mismatch rather than guessing.** A backup taken
before a later migration would otherwise silently load an older schema
underneath newer application code, corrupting reads/writes in ways that
surface much later and far from the actual cause. `alembic_version` is
compared byte-for-byte between the backup and the live database; anything
but an exact match is rejected. No "upgrade the backup first" attempt —
that would mean running migrations against a file the user hasn't chosen
to keep, on the way to maybe not using it, for one command that's already
capable of just re-running `alembic upgrade head` on its own copy later.
"""

from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.config import BACKUP_DIR, get_settings
from app.db import engine

#: Filename prefix + timestamp format — sorts lexicographically in the same
#: order as chronologically, so `sorted()` on filenames alone is enough.
#: Microsecond precision, not just seconds: two backups requested within the
#: same second (a double-click, a script) would otherwise collide on the
#: same filename and the second `shutil.copy2` would silently overwrite the
#: first — found by a flaky-looking test failure, not by inspection.
_FILENAME_PREFIX = "stock_analyst_"
_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%S%fZ"

#: Oldest backups beyond this count are pruned on each new backup — keeps
#: disk usage bounded without the user needing to manage files by hand.
#: Never prunes the backup just created, and never touches anything outside
#: BACKUP_DIR.
MAX_BACKUPS = 10


@dataclass
class BackupInfo:
    filename: str
    created_at: datetime
    size_bytes: int


def _live_db_path() -> Path:
    url = get_settings().database_url
    if not url.startswith("sqlite:///"):
        raise ValueError("Backup is only supported for a local SQLite database.")
    return Path(url.removeprefix("sqlite:///"))


def _read_alembic_version(db_path: Path) -> str | None:
    """Reads `alembic_version` directly via `sqlite3`, not through the app's
    own SQLAlchemy engine — this must work on an arbitrary backup file that
    was never `engine`'s target, and must never register a connection
    against the live engine's pool."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        return row[0] if row else None
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()


def create_backup() -> BackupInfo:
    """Copies the live database to a new timestamped file in BACKUP_DIR,
    then prunes anything beyond MAX_BACKUPS (oldest first)."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    db_path = _live_db_path()

    timestamp = datetime.now(UTC).strftime(_TIMESTAMP_FORMAT)
    filename = f"{_FILENAME_PREFIX}{timestamp}.db"
    destination = BACKUP_DIR / filename
    shutil.copy2(db_path, destination)

    existing = sorted(BACKUP_DIR.glob(f"{_FILENAME_PREFIX}*.db"))
    for stale in existing[: max(0, len(existing) - MAX_BACKUPS)]:
        stale.unlink()

    stat = destination.stat()
    return BackupInfo(filename=filename, created_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC), size_bytes=stat.st_size)


def list_backups() -> list[BackupInfo]:
    if not BACKUP_DIR.exists():
        return []
    infos = []
    for path in BACKUP_DIR.glob(f"{_FILENAME_PREFIX}*.db"):
        stat = path.stat()
        infos.append(
            BackupInfo(filename=path.name, created_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC), size_bytes=stat.st_size)
        )
    infos.sort(key=lambda b: b.created_at, reverse=True)
    return infos


class BackupNotFoundError(Exception):
    pass


class SchemaMismatchError(Exception):
    def __init__(self, backup_version: str | None, live_version: str | None):
        self.backup_version = backup_version
        self.live_version = live_version
        super().__init__(
            f"Backup schema version ({backup_version}) does not match the live "
            f"database's ({live_version})."
        )


def _resolve_backup_path(filename: str) -> Path:
    """Resolves `filename` strictly inside BACKUP_DIR — rejects any path
    that would escape it (`../`, an absolute path, a symlink target
    elsewhere), since this name arrives from an API request."""
    candidate = (BACKUP_DIR / filename).resolve()
    if candidate.parent != BACKUP_DIR.resolve() or not candidate.is_file():
        raise BackupNotFoundError(filename)
    return candidate


def restore_backup(filename: str) -> None:
    """Restores `filename` over the live database. Refuses on any schema
    version mismatch (`SchemaMismatchError`) or an unresolvable filename
    (`BackupNotFoundError`) — never guesses, never partially restores.

    `engine.dispose()` closes every pooled connection first: SQLite holds
    its file lock through the connection, and a stale pooled connection
    would otherwise keep pointing at file content that no longer exists
    once the copy below lands. The next request opens a fresh connection
    against the restored file.
    """
    backup_path = _resolve_backup_path(filename)
    db_path = _live_db_path()

    backup_version = _read_alembic_version(backup_path)
    live_version = _read_alembic_version(db_path) if db_path.exists() else None
    if backup_version != live_version:
        raise SchemaMismatchError(backup_version, live_version)

    engine.dispose()
    shutil.copy2(backup_path, db_path)
