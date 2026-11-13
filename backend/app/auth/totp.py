"""Time-based one-time codes (RFC 6238), as shown by any authenticator app.

SHA-1, 6 digits, 30-second steps: the defaults every authenticator app uses
when it scans an ``otpauth://`` link without extra parameters.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP_SECONDS = 30
DIGITS = 6
#: Codes from one step before or after are accepted too, for a phone clock
#: that is a few seconds off.
WINDOW = 1


def new_secret() -> str:
    """A random 160-bit secret, base32 without padding (what apps expect)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _code_at(secret: str, step: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10**DIGITS).zfill(DIGITS)


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // STEP_SECONDS)


def code_for(secret: str, now: float | None = None) -> str:
    return _code_at(secret, current_step(now))


def matching_step(secret: str, code: str, now: float | None = None) -> int | None:
    """The time step ``code`` belongs to, within the window, or ``None``.

    The caller stores the step of the last accepted code and refuses any code
    from that step or earlier, so a code seen once can't be replayed.
    """
    code = code.strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    base = current_step(now)
    for step in range(base - WINDOW, base + WINDOW + 1):
        if hmac.compare_digest(_code_at(secret, step), code):
            return step
    return None


def provisioning_uri(secret: str, account: str, issuer: str = "Stock Analyst") -> str:
    """``otpauth://`` link to scan or paste into an authenticator app."""
    label = quote(f"{issuer}:{account}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}"
