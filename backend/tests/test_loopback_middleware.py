"""This API has no authentication — the loopback-only middleware is the one real
access boundary it has. See DEVLOG "Decision 3k.1".

Starlette's `TestClient` always presents as the fixed host "testclient" (its own
in-process transport convention), so it can't be used to simulate a real remote
client. `httpx.ASGITransport` accepts an explicit `client=(host, port)` instead —
no `pytest-asyncio`/`anyio` plugin needed, `asyncio.run()` drives the one call.
"""

from __future__ import annotations

import asyncio

import httpx

from app.main import app


def _get(client_host: str) -> httpx.Response:
    async def call() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, client=(client_host, 12345))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get("/api/health")

    return asyncio.run(call())


class TestLoopbackOnlyMiddleware:
    def test_rejects_a_non_loopback_client(self):
        response = _get("203.0.113.5")
        assert response.status_code == 403

    def test_allows_ipv4_loopback(self):
        assert _get("127.0.0.1").status_code == 200

    def test_allows_ipv6_loopback(self):
        assert _get("::1").status_code == 200
