"""Configurable LLM for qualitative commentary.

Generalizes the Perplexity-only setup: any OpenAI-compatible endpoint (DeepSeek,
OpenAI, Groq, OpenRouter, ...) is now a first-class provider via `llm_provider`,
`llm_api_key`, `llm_model` and `llm_base_url`, while Perplexity (with its
citations) stays available as the default. One instrument at a time, on explicit
request only — never a scoring input (see providers/perplexity.py).
"""

from __future__ import annotations

import httpx

from app.config import Settings
from app.providers.base import ProviderUnavailable, RateLimited
from app.providers.perplexity import _SYSTEM_PROMPT, Commentary, PerplexityClient


class OpenAICompatibleClient:
    """Any chat-completions endpoint speaking the OpenAI wire format."""

    name = "openai_compatible"

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = client

    def is_enabled(self) -> bool:
        return bool(self.api_key)

    def ask_about(
        self,
        symbol: str,
        name: str | None = None,
        sector: str | None = None,
        *,
        max_tokens: int | None = None,
    ) -> Commentary:
        subject = f"{name} ({symbol})" if name else symbol
        question = f"Give a qualitative research summary of {subject}"
        if sector:
            question += f", a company in the {sector} sector"
        question += "."

        body: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens

        client = self._client or httpx.Client(timeout=60.0)
        owns_client = self._client is None
        try:
            try:
                response = client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=body,
                )
            except httpx.HTTPError as exc:
                raise ProviderUnavailable(str(exc)) from exc

            if response.status_code == 429:
                raise RateLimited("LLM rate limit")
            if response.status_code >= 400:
                raise ProviderUnavailable(f"HTTP {response.status_code}: {response.text[:200]}")

            try:
                data = response.json()
            except ValueError as exc:
                raise ProviderUnavailable(f"invalid JSON response: {exc}") from exc
        finally:
            if owns_client:
                client.close()

        choice = (data.get("choices") or [{}])[0]
        content = choice.get("message", {}).get("content", "")
        return Commentary(content=content, citations=[], model=data.get("model", self.model))


#: Any commentary client — Perplexity or an OpenAI-compatible endpoint. The
#: `get_commentary` service is duck-typed over this union (is_enabled + ask_about).
CommentaryClient = PerplexityClient | OpenAICompatibleClient


def build_llm_client(settings: Settings) -> CommentaryClient:
    """The active commentary client from settings: OpenAI-compatible when
    `llm_provider` says so and a key is present, Perplexity otherwise (the
    backward-compatible default)."""
    if settings.llm_provider == "openai_compatible" and settings.llm_api_key:
        return OpenAICompatibleClient(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
        )
    return PerplexityClient(api_key=settings.perplexity_api_key or "", model=settings.perplexity_model)
