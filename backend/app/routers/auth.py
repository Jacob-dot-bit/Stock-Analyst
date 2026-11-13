"""Login and logout for the browser."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import service
from app.auth.dependency import SESSION_COOKIE
from app.config import get_settings
from app.db import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)
    code: str | None = Field(default=None, max_length=16)


class Status(BaseModel):
    required: bool
    configured: bool


class Me(BaseModel):
    username: str | None
    via: str
    totp_enabled: bool


@router.post("/login", status_code=204)
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)) -> Response:
    settings = get_settings()
    try:
        token = service.login(db, body.username, body.password, body.code)
    except service.LoginError as err:
        if err.code == service.LOCKED:
            raise HTTPException(
                status_code=429,
                detail=err.code,
                headers={"Retry-After": str(err.retry_after or 60)},
            ) from err
        if err.code == service.INVALID_CREDENTIALS and settings.auth_failure_delay_s > 0:
            # Slows down guessing; the route is sync, so this blocks one worker
            # thread, not the server.
            time.sleep(settings.auth_failure_delay_s)
        status = 503 if err.code == service.NOT_CONFIGURED else 401
        raise HTTPException(status_code=status, detail=err.code) from err

    response = Response(status_code=204)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.auth_session_max_days * 86400,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="strict",
        path="/",
    )
    return response


@router.post("/logout", status_code=204)
def logout(request: Request, db: Session = Depends(get_db)) -> Response:
    service.logout(db, request.cookies.get(SESSION_COOKIE))
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/me", response_model=Me)
def me(request: Request, db: Session = Depends(get_db)) -> Me:
    account = service.get_account(db)
    auth = getattr(request.state, "auth", None)
    if auth is None:
        # Only reachable while AUTH_REQUIRED=false: say so instead of
        # pretending to be logged in.
        raise HTTPException(status_code=401, detail="auth.required")
    via = "session" if auth == "session" else f"token:{auth.name}"
    return Me(
        username=account.username if account else None,
        via=via,
        totp_enabled=bool(account and account.totp_enabled),
    )


@router.get("/status", response_model=Status)
def status(db: Session = Depends(get_db)) -> Status:
    """Whether the login page should be shown, readable before logging in.

    Says nothing about the account beyond whether one exists.
    """
    return Status(required=get_settings().auth_required, configured=service.get_account(db) is not None)
