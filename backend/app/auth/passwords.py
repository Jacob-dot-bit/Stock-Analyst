"""Password hashing with the standard library's scrypt.

No new dependency: ``hashlib.scrypt`` is a memory-hard KDF, which is what a
password hash needs. The stored string carries its own parameters, so they can
be raised later without invalidating existing hashes.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

#: scrypt cost parameters. n=2**15, r=8 needs 32 MiB of memory per hash and
#: takes roughly 50-100 ms on a small server: slow enough to make guessing
#: expensive, fast enough for one login.
_N = 2**15
_R = 8
_P = 1
_DKLEN = 32
_MAXMEM = 64 * 1024 * 1024

MIN_PASSWORD_LENGTH = 12


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def hash_password(password: str) -> str:
    """Return ``scrypt$n$r$p$salt$hash`` for ``password``."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN, maxmem=_MAXMEM
    )
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check of ``password`` against a string from ``hash_password``."""
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
            maxmem=_MAXMEM,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected)
