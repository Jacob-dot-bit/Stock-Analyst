"""Tests for `app/providers/llm.py` — the configurable commentary client."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx

from app.providers.llm import OpenAICompatibleClient, build_llm_client


def _client_returning(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _settings(**overrides) -> SimpleNamespace:
    base = dict(
        llm_provider="perplexity",
        llm_api_key=None,
        llm_model="deepseek-chat",
        llm_base_url="https://api.deepseek.com",
        perplexity_api_key=None,
        perplexity_model="sonar",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class TestOpenAICompatibleClient:
    def test_parses_content_and_builds_request(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["auth"] = request.headers.get("Authorization")
            captured["body"] = json.loads(request.content)
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "A summary."}}], "model": "deepseek-chat"}
            )

        client = OpenAICompatibleClient(
            api_key="dk", base_url="https://api.deepseek.com", model="deepseek-chat",
            client=_client_returning(handler),
        )
        result = client.ask_about("AAPL", name="Apple", sector="Technology")

        assert captured["url"] == "https://api.deepseek.com/chat/completions"
        assert captured["auth"] == "Bearer dk"
        assert captured["body"]["model"] == "deepseek-chat"
        assert captured["body"]["messages"][0]["role"] == "system"
        assert "Apple (AAPL)" in captured["body"]["messages"][1]["content"]
        assert result.content == "A summary."
        assert result.citations == []
        assert result.model == "deepseek-chat"

    def test_non_200_raises_provider_unavailable(self):
        from app.providers.base import ProviderUnavailable

        client = OpenAICompatibleClient(
            api_key="dk", base_url="https://api.deepseek.com", model="deepseek-chat",
            client=_client_returning(lambda r: httpx.Response(401, text="bad key")),
        )
        try:
            client.ask_about("AAPL")
        except ProviderUnavailable as exc:
            assert "401" in str(exc)
        else:
            raise AssertionError("expected ProviderUnavailable")


class TestBuildLlmClient:
    def test_openai_compatible_when_configured(self):
        client = build_llm_client(
            _settings(llm_provider="openai_compatible", llm_api_key="dk")
        )
        assert client.name == "openai_compatible"

    def test_defaults_to_perplexity_without_openai_compatible_key(self):
        client = build_llm_client(_settings(perplexity_api_key="pk"))
        assert client.name == "perplexity"
        assert client.is_enabled()

    def test_perplexity_fallback_when_provider_is_perplexity(self):
        client = build_llm_client(
            _settings(llm_provider="perplexity", llm_api_key="dk", perplexity_api_key="pk")
        )
        assert client.name == "perplexity"
