"""Tests for `PerplexityClient.ask_about`. All network calls are mocked."""

from __future__ import annotations

import httpx
import pytest

from app.providers.base import ProviderUnavailable, RateLimited
from app.providers.perplexity import Citation, PerplexityClient
from tests.test_providers import client_returning


def sonar_payload(content: str = "A concise summary.", citations: list[str] | None = None, search_results=None) -> dict:
    payload = {
        "model": "sonar",
        "choices": [{"message": {"content": content}}],
    }
    if search_results is not None:
        payload["search_results"] = search_results
    if citations is not None:
        payload["citations"] = citations
    return payload


class TestAskAbout:
    def test_parses_content_and_search_results_citations(self):
        client = PerplexityClient(
            api_key="key",
            client=client_returning(
                lambda r: httpx.Response(
                    200,
                    json=sonar_payload(
                        search_results=[{"url": "https://example.com/a", "title": "Article A"}]
                    ),
                )
            ),
        )

        commentary = client.ask_about("AAPL", name="Apple Inc.")

        assert commentary.content == "A concise summary."
        assert commentary.model == "sonar"
        assert commentary.citations == [Citation(url="https://example.com/a", title="Article A")]

    def test_falls_back_to_citations_field_when_no_search_results(self):
        client = PerplexityClient(
            api_key="key",
            client=client_returning(
                lambda r: httpx.Response(200, json=sonar_payload(citations=["https://example.com/b"]))
            ),
        )

        commentary = client.ask_about("AAPL")

        assert len(commentary.citations) == 1
        assert commentary.citations[0].url == "https://example.com/b"
        assert commentary.citations[0].title is None

    def test_max_tokens_included_only_when_passed(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json=sonar_payload())

        client = PerplexityClient(api_key="key", client=client_returning(handler))
        client.ask_about("AAPL", max_tokens=16)
        assert captured["body"]["max_tokens"] == 16

        client.ask_about("AAPL")
        assert "max_tokens" not in captured["body"]

    def test_429_raises_rate_limited(self):
        client = PerplexityClient(api_key="key", client=client_returning(lambda r: httpx.Response(429)))

        with pytest.raises(RateLimited):
            client.ask_about("AAPL")

    def test_non_2xx_raises_provider_unavailable(self):
        client = PerplexityClient(
            api_key="key", client=client_returning(lambda r: httpx.Response(401, text="unauthorized"))
        )

        with pytest.raises(ProviderUnavailable):
            client.ask_about("AAPL")
