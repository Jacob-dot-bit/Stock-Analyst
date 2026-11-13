"""The check run before every API route.

A request passes with either a browser session (cookie) or a service token
(``Authorization: Bearer``). It comes on top of the loopback-only middleware in
``app/main.py``, not instead of it: both must agree.

``AUTH_REQUIRED=false`` keeps the check but only logs what it would refuse.
That is how this lands on a running install: deploy, watch the log for callers
that don't identify themselves yet, give them a token, then turn it on.
"""

from __future__ import annotations

import logging

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth import service
from app.config import get_settings
from app.db import get_db

logger = logging.getLogger("stock_analyst.auth")

SESSION_COOKIE = "sa_session"

#: Header the frontend adds to every request. A page on another site can't set
#: a custom header on a cross-site request without a CORS preflight, which this
#: API refuses, so its presence on a cookie-authenticated write proves the
#: request comes from our own pages.
CSRF_HEADER = "X-Requested-With"
CSRF_VALUE = "stock-analyst"

#: Reachable without being logged in.
PUBLIC_ROUTES = frozenset({("POST", "/api/auth/login"), ("POST", "/api/auth/logout")})

UNAUTHENTICATED = "auth.required"
FORBIDDEN_SCOPE = "auth.readOnlyToken"
CSRF_MISSING = "auth.csrfHeaderMissing"


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()
    return None


def _refuse(request: Request, status: int, code: str, why: str) -> None:
    if get_settings().auth_required:
        raise HTTPException(status_code=status, detail=code)
    logger.warning("auth (journal seul) : refuserait %s %s : %s", request.method, request.url.path, why)


def require_auth(request: Request, db: Session = Depends(get_db)) -> None:
    method = request.method.upper()
    if (method, request.url.path) in PUBLIC_ROUTES:
        return

    token = _bearer(request)
    if token is not None:
        caller = service.check_service_token(db, token)
        if caller is None:
            _refuse(request, 401, UNAUTHENTICATED, "jeton de service inconnu")
            return
        request.state.auth = caller
        if not caller.allows(method):
            _refuse(request, 403, FORBIDDEN_SCOPE, f"jeton « {caller.name} » en lecture seule")
        return

    if service.check_session(db, request.cookies.get(SESSION_COOKIE)):
        request.state.auth = "session"
        if method not in service.READ_METHODS and request.headers.get(CSRF_HEADER) != CSRF_VALUE:
            _refuse(request, 403, CSRF_MISSING, f"en-tête {CSRF_HEADER} absent")
        return

    _refuse(request, 401, UNAUTHENTICATED, "ni session ni jeton")
