"""Tests for the settings/provider-status endpoints.

`update_api_keys` (`PUT /api/settings/api-keys`) writes to the real project
`.env` file — deliberately not exercised here, since a test that mutates the
developer's real `.env` is exactly the kind of side effect this suite must
never have. What's covered is everything that doesn't touch the filesystem:
the provider listing and the key-verification endpoint (with SEC EDGAR itself
mocked out, the same way `test_edgar.py` avoids a real network call).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.providers.base import ProviderUnavailable


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


class TestProviderList:
    def test_sec_user_agent_appears_even_though_its_not_a_price_provider(self, client):
        """EDGAR isn't in the price-provider chain (`get_provider_chain`) —
        it's a separate registry for fundamentals — so it must be appended
        manually or it never gets a card on the Settings page at all. See
        DEVLOG "Decision 3s.1"."""
        response = client.get("/api/settings/providers")
        assert response.status_code == 200
        body = response.json()

        by_name = {p["name"]: p for p in body}
        assert "sec_user_agent" in by_name
        entry = by_name["sec_user_agent"]
        assert entry["has_api_key"] is True
        # `isolate_credentials` (conftest.py, autouse) always clears
        # SEC_USER_AGENT, so this must report disabled in every test run.
        assert entry["enabled"] is False
        assert entry["description"]
        assert entry["signup_url"]

class TestVerifySecUserAgent:
    def test_no_key_configured_or_supplied_reports_nothing_to_test(self, client):
        response = client.post(
            "/api/settings/verify-key", json={"provider": "sec_user_agent", "api_key": None}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["valid"] is False
        assert "nothing to test" in body["message"].lower() or "to test" in body["message"].lower()

    def test_accepted_key_reports_success(self, client, monkeypatch):
        class FakeEdgarProvider:
            def __init__(self, user_agent, min_interval_seconds=0):
                self.user_agent = user_agent

            def resolve(self, ticker, expected_name=None):
                return "0000320193", "Apple Inc."

        monkeypatch.setattr("app.routers.settings.EdgarProvider", FakeEdgarProvider)

        response = client.post(
            "/api/settings/verify-key",
            json={"provider": "sec_user_agent", "api_key": "Test User test@example.com"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["valid"] is True
        assert "Apple Inc." in body["message"]

    def test_rejected_key_reports_the_real_reason(self, client, monkeypatch):
        class FakeEdgarProvider:
            def __init__(self, user_agent, min_interval_seconds=0):
                self.user_agent = user_agent

            def resolve(self, ticker, expected_name=None):
                raise ProviderUnavailable("SEC EDGAR refused the request")

        monkeypatch.setattr("app.routers.settings.EdgarProvider", FakeEdgarProvider)

        response = client.post(
            "/api/settings/verify-key", json={"provider": "sec_user_agent", "api_key": "bad"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["valid"] is False
        assert "SEC EDGAR refused the request" in body["message"]
