"""Perplexity Sonar qualitative synthesis — one instrument at a time, on
explicit request only. See DEVLOG "Decision 0.3": mass screening with this
provider is a deliberately rejected design, not an oversight. Never a scoring
input — it comments on the score, it never contributes to it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from app.providers.base import ProviderUnavailable, RateLimited

SONAR_URL = "https://api.perplexity.ai/chat/completions"

_SYSTEM_PROMPT = (
    "You are a financial research assistant. Given one publicly traded "
    "instrument, write a concise (max ~200 words) qualitative summary covering "
    "recent developments, competitive position, and notable risks. Do not give "
    "a buy/sell recommendation or a target price — the caller already has a "
    "separate, purely quantitative composite score; your role is commentary, "
    "not a second opinion on the score."
)


@dataclass(frozen=True)
class Citation:
    url: str
    title: str | None = None


@dataclass(frozen=True)
class Commentary:
    content: str
    citations: list[Citation] = field(default_factory=list)
    model: str = ""


class PerplexityClient:
    """No `Throttle` of its own: unlike `AlphaVantageProvider`, this is never
    part of the price-provider chain and every call is one explicit user
    action, never a batch — nothing to share a rate limiter with.
    """

    name = "perplexity"

    def __init__(self, api_key: str, model: str = "sonar", client: httpx.Client | None = None) -> None:
        self.api_key = api_key
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
        """One real call: ask Sonar about one instrument.

        `max_tokens` is exposed (not a second method) purely so `verify-key`
        can request a cheap, minimal-token real call through this exact same
        code path — see `routers/settings.py`'s "perplexity" branch.
        """
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

        client = self._client or httpx.Client(timeout=30.0)
        owns_client = self._client is None
        try:
            try:
                response = client.post(
                    SONAR_URL, headers={"Authorization": f"Bearer {self.api_key}"}, json=body
                )
            except httpx.HTTPError as exc:
                raise ProviderUnavailable(str(exc)) from exc

            if response.status_code == 429:
                raise RateLimited("Perplexity rate limit")
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

        citations = [
            Citation(url=item["url"], title=item.get("title"))
            for item in (data.get("search_results") or [])
            if item.get("url")
        ]
        if not citations:
            citations = [Citation(url=url) for url in (data.get("citations") or [])]

        return Commentary(content=content, citations=citations, model=data.get("model", self.model))
