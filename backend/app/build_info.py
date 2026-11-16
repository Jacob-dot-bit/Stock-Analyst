"""Which commit the running backend was started from.

Deployment is ``git pull`` then a service restart, so the checkout itself is
the build: no build step writes a version file. Read once at import time —
a ``git pull`` without a restart must keep showing the old commit, since
that is the code actually running.
"""

from __future__ import annotations

import os
import subprocess
from functools import lru_cache

from app.config import PROJECT_ROOT


@lru_cache(maxsize=1)
def build_info() -> dict[str, str | None]:
    """Short hash and committer date (ISO 8601) of HEAD, or ``None`` each.

    ``STOCK_ANALYST_COMMIT`` overrides the hash for a copy deployed without
    its ``.git`` directory.
    """
    override = os.environ.get("STOCK_ANALYST_COMMIT")
    if override:
        return {"commit": override[:12], "committed_at": None}
    try:
        out = subprocess.run(
            [
                "git",
                # The service may run as another user than the checkout's
                # owner; git then refuses the repository ("dubious ownership").
                "-c",
                f"safe.directory={PROJECT_ROOT}",
                "-C",
                str(PROJECT_ROOT),
                "log",
                "-1",
                "--format=%h%n%cI",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "committed_at": None}
    if len(out) != 2:
        return {"commit": None, "committed_at": None}
    return {"commit": out[0], "committed_at": out[1]}
