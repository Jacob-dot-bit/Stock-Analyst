"""Login, sessions, service tokens and the check run before every route."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import passwords, service, totp
from app.auth.dependency import CSRF_HEADER, CSRF_VALUE, SESSION_COOKIE
from app.auth.models import AuthAccount, AuthSession
from app.config import get_settings
from app.db import Base, get_db
from app.main import app

USER = "jakub"
PASSWORD = "un mot de passe assez long"


@pytest.fixture
def db_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def auth_on(monkeypatch):
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    monkeypatch.setenv("AUTH_FAILURE_DELAY_S", "0")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client(db_factory):
    def override_get_db():
        session = db_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    # https: the session cookie is Secure, and the client only sends it back over https.
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def account(db_factory):
    with db_factory() as db:
        service.set_password(db, USER, PASSWORD)


def _login(client, **overrides):
    body = {"username": USER, "password": PASSWORD} | overrides
    return client.post("/api/auth/login", json=body)


class TestPasswords:
    def test_round_trip(self):
        stored = passwords.hash_password("correct horse battery")
        assert stored.startswith("scrypt$")
        assert passwords.verify_password("correct horse battery", stored)
        assert not passwords.verify_password("correct horse batterY", stored)

    def test_same_password_gives_different_hashes(self):
        assert passwords.hash_password("x" * 12) != passwords.hash_password("x" * 12)

    def test_garbage_hash_is_refused_not_raised(self):
        assert not passwords.verify_password("anything", "not-a-hash")

    def test_short_password_is_refused(self, db_factory):
        with db_factory() as db, pytest.raises(ValueError):
            service.set_password(db, USER, "short")


class TestTotp:
    # RFC 6238 appendix B, SHA-1 test vectors (8 digits there; the last 6 here).
    SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # base32 of "12345678901234567890"

    @pytest.mark.parametrize(
        ("when", "expected"),
        [(59, "287082"), (1111111109, "081804"), (1234567890, "005924"), (2000000000, "279037")],
    )
    def test_rfc_vectors(self, when, expected):
        assert totp.code_for(self.SECRET, now=when) == expected

    def test_window_is_one_step_each_side(self):
        now = 1_700_000_000
        assert totp.matching_step(self.SECRET, totp.code_for(self.SECRET, now - 30), now) is not None
        assert totp.matching_step(self.SECRET, totp.code_for(self.SECRET, now + 30), now) is not None
        assert totp.matching_step(self.SECRET, totp.code_for(self.SECRET, now - 90), now) is None

    def test_malformed_codes(self):
        assert totp.matching_step(self.SECRET, "12345") is None
        assert totp.matching_step(self.SECRET, "abcdef") is None


class TestRequiredMode:
    def test_api_refused_without_session(self, client, account, auth_on):
        response = client.get("/api/portfolio")
        assert response.status_code == 401
        assert response.json()["detail"] == "auth.required"

    def test_login_sets_a_strict_secure_httponly_cookie(self, client, account, auth_on):
        response = _login(client)
        assert response.status_code == 204
        cookie = response.headers["set-cookie"].lower()
        for attribute in ("httponly", "secure", "samesite=strict", "path=/"):
            assert attribute in cookie

    def test_session_opens_the_api(self, client, account, auth_on):
        _login(client)
        assert client.get("/api/portfolio").status_code == 200
        me = client.get("/api/auth/me").json()
        assert me == {"username": USER, "via": "session", "totp_enabled": False}

    def test_wrong_password_and_wrong_name_look_the_same(self, client, account, auth_on):
        a = _login(client, password="pas le bon mot de passe")
        b = _login(client, username="quelquun")
        assert a.status_code == b.status_code == 401
        assert a.json() == b.json() == {"detail": "auth.invalidCredentials"}

    def test_lockout_after_five_failures(self, client, account, auth_on):
        for _ in range(5):
            assert _login(client, password="mauvais mot de passe").status_code == 401
        locked = _login(client)  # even the right password
        assert locked.status_code == 429
        assert locked.json()["detail"] == "auth.locked"
        assert int(locked.headers["retry-after"]) > 0

    def test_lockout_ends(self, client, account, auth_on, db_factory):
        for _ in range(5):
            _login(client, password="mauvais mot de passe")
        with db_factory() as db:
            db.get(AuthAccount, 1).locked_until = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()
        assert _login(client).status_code == 204

    def test_success_resets_the_failure_count(self, client, account, auth_on):
        for _ in range(4):
            _login(client, password="mauvais mot de passe")
        assert _login(client).status_code == 204
        for _ in range(4):
            _login(client, password="mauvais mot de passe")
        assert _login(client).status_code == 204

    def test_logout_ends_the_session(self, client, account, auth_on):
        _login(client)
        token = client.cookies.get(SESSION_COOKIE)
        assert client.post("/api/auth/logout").status_code == 204
        client.cookies.set(SESSION_COOKIE, token)  # an old copy of the cookie
        assert client.get("/api/portfolio").status_code == 401

    def test_idle_session_expires(self, client, account, auth_on, db_factory):
        _login(client)
        with db_factory() as db:
            session = db.query(AuthSession).one()
            session.last_seen_at = datetime.now(UTC) - timedelta(days=7, minutes=1)
            db.commit()
        assert client.get("/api/portfolio").status_code == 401

    def test_session_has_an_absolute_end(self, client, account, auth_on, db_factory):
        _login(client)
        with db_factory() as db:
            db.query(AuthSession).one().expires_at = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()
        assert client.get("/api/portfolio").status_code == 401

    def test_password_change_closes_sessions(self, client, account, auth_on, db_factory):
        _login(client)
        with db_factory() as db:
            service.set_password(db, USER, "un autre mot de passe long")
        assert client.get("/api/portfolio").status_code == 401

    def test_write_with_session_needs_the_csrf_header(self, client, account, auth_on):
        _login(client)
        refused = client.post("/api/journal", json={})
        assert refused.status_code == 403
        assert refused.json()["detail"] == "auth.csrfHeaderMissing"
        passed = client.post("/api/journal", json={}, headers={CSRF_HEADER: CSRF_VALUE})
        assert passed.status_code not in (401, 403)

    def test_no_account_yet(self, client, auth_on):
        assert _login(client).status_code == 503


class TestTotpLogin:
    @pytest.fixture
    def secret(self, db_factory, account):
        with db_factory() as db:
            secret = service.start_totp(db)
            # Confirm with the previous step's code, so the current one is still unused.
            assert service.confirm_totp(db, totp.code_for(secret, now=datetime.now(UTC).timestamp() - 30))
        return secret

    def test_password_alone_asks_for_the_code(self, client, secret, auth_on):
        response = _login(client)
        assert response.status_code == 401
        assert response.json()["detail"] == "auth.totpRequired"
        assert client.get("/api/portfolio").status_code == 401

    def test_right_code_logs_in(self, client, secret, auth_on):
        assert _login(client, code=totp.code_for(secret)).status_code == 204
        assert client.get("/api/auth/me").json()["totp_enabled"] is True

    def test_wrong_code_counts_as_a_failure(self, client, secret, auth_on):
        wrong = "000000" if totp.code_for(secret) != "000000" else "111111"
        for _ in range(5):
            assert _login(client, code=wrong).status_code == 401
        assert _login(client, code=totp.code_for(secret)).status_code == 429

    def test_a_code_works_only_once(self, client, secret, auth_on):
        code = totp.code_for(secret)
        assert _login(client, code=code).status_code == 204
        client.cookies.clear()
        assert _login(client, code=code).status_code == 401

    def test_unconfirmed_secret_is_not_required(self, client, db_factory, account, auth_on):
        with db_factory() as db:
            service.start_totp(db)
        assert _login(client).status_code == 204


class TestServiceTokens:
    @pytest.fixture
    def tokens(self, db_factory, account):
        with db_factory() as db:
            return {
                "read": service.add_service_token(db, "export", "read"),
                "write": service.add_service_token(db, "hermes-gate", "write"),
            }

    def test_read_token_can_read(self, client, tokens, auth_on):
        response = client.get("/api/portfolio", headers={"Authorization": f"Bearer {tokens['read']}"})
        assert response.status_code == 200

    def test_read_token_cannot_write(self, client, tokens, auth_on):
        response = client.post("/api/journal", json={}, headers={"Authorization": f"Bearer {tokens['read']}"})
        assert response.status_code == 403
        assert response.json()["detail"] == "auth.readOnlyToken"

    def test_write_token_needs_no_csrf_header(self, client, tokens, auth_on):
        response = client.post("/api/journal", json={}, headers={"Authorization": f"Bearer {tokens['write']}"})
        assert response.status_code not in (401, 403)

    def test_unknown_token(self, client, tokens, auth_on):
        response = client.get("/api/portfolio", headers={"Authorization": "Bearer sat_inconnu"})
        assert response.status_code == 401

    def test_revoked_token(self, client, tokens, auth_on, db_factory):
        with db_factory() as db:
            assert service.revoke_service_token(db, "export")
        response = client.get("/api/portfolio", headers={"Authorization": f"Bearer {tokens['read']}"})
        assert response.status_code == 401

    def test_me_names_the_token(self, client, tokens, auth_on):
        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tokens['write']}"}).json()
        assert me["via"] == "token:hermes-gate"

    def test_bad_scope(self, db_factory):
        with db_factory() as db, pytest.raises(ValueError):
            service.add_service_token(db, "x", "admin")


class TestJournalOnlyMode:
    """AUTH_REQUIRED=false (the default for now): nothing is refused, all is logged."""

    def test_unauthenticated_call_passes_and_is_logged(self, client, account, caplog):
        with caplog.at_level("WARNING", logger="stock_analyst.auth"):
            assert client.get("/api/portfolio").status_code == 200
        assert "refuserait GET /api/portfolio" in caplog.text

    def test_me_still_says_not_logged_in(self, client, account):
        assert client.get("/api/auth/me").status_code == 401


class TestStillLoopbackOnly:
    def test_a_valid_token_from_outside_is_still_refused(self, db_factory, account, auth_on):
        with db_factory() as db:
            token = service.add_service_token(db, "x", "write")

        def override_get_db():
            session = db_factory()
            try:
                yield session
            finally:
                session.close()

        async def call():
            transport = httpx.ASGITransport(app=app, client=("203.0.113.5", 1234))
            async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as c:
                return await c.get("/api/portfolio", headers={"Authorization": f"Bearer {token}"})

        app.dependency_overrides[get_db] = override_get_db
        try:
            assert asyncio.run(call()).status_code == 403
        finally:
            app.dependency_overrides.clear()


class TestDockerBridge:
    """The sandbox reaches two routes over the docker bridge; with the login
    required it needs a token there too, and the token opens nothing else."""

    @pytest.fixture
    def bridge_call(self, db_factory):
        def override_get_db():
            session = db_factory()
            try:
                yield session
            finally:
                session.close()

        def call(method, path, token=None):
            async def go():
                transport = httpx.ASGITransport(app=app, client=("172.17.0.5", 40000))
                headers = {"Authorization": f"Bearer {token}"} if token else {}
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
                    return await c.request(method, path, headers=headers)

            app.dependency_overrides[get_db] = override_get_db
            try:
                return asyncio.run(go())
            finally:
                app.dependency_overrides.clear()

        return call

    @pytest.fixture
    def sandbox_token(self, db_factory, account):
        with db_factory() as db:
            return service.add_service_token(db, "sandbox", "write")

    def test_without_token_refused(self, bridge_call, account, auth_on):
        assert bridge_call("GET", "/api/settings/api-keys").status_code == 401
        assert bridge_call("POST", "/api/prices/refresh").status_code == 401

    def test_with_token_passes(self, bridge_call, sandbox_token, auth_on):
        assert bridge_call("GET", "/api/settings/api-keys", sandbox_token).status_code == 200

    def test_token_opens_no_other_route(self, bridge_call, sandbox_token, auth_on):
        assert bridge_call("GET", "/api/portfolio", sandbox_token).status_code == 403
