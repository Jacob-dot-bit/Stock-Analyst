"""Canonical instrument identity via OpenFIGI — free, keyless (a key only
raises rate limits, it doesn't gate access), no payment. See
https://www.openfigi.com/api/documentation.

Deliberately not a `providers/base.py::PriceProvider` — like
`providers/wikidata.py`, this answers "what security is this," not "what
does it cost" or "what are its fundamentals," a different axis entirely
from the ProviderChain/quote-fetching machinery those use.

This app already evaluated OpenFIGI once and rejected it, for a different
need (DEVLOG "Decision 2c.3": resolving an ISIN for Frankfurt pricing —
OpenFIGI returns FIGIs, not ISINs, so it didn't fill that gap). The need
here is different: a stable cross-reference to recognise the same
real-world instrument under two different broker symbols (e.g. a US
listing held, a London listing later watchlisted), for which the FIGI
itself — specifically the *share-class* FIGI, shared across every
exchange listing of the same security — is exactly the right key. See
DEVLOG "Decision 3u.76".
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

MAPPING_URL = "https://api.openfigi.com/v3/mapping"


@dataclass(frozen=True)
class FigiJob:
    """One instrument to resolve. `isin`, when known, takes priority over
    ticker + currency — it's unambiguous where a bare ticker often isn't."""

    isin: str | None
    ticker: str | None
    currency: str | None


@dataclass(frozen=True)
class FigiMatch:
    figi: str
    share_class_figi: str | None
    name: str | None


def map_instruments(
    jobs: list[FigiJob], api_key: str | None, max_jobs_per_request: int, timeout: float = 15.0
) -> list[FigiMatch | None]:
    """One `FigiMatch | None` per job, same order and length as `jobs`.

    `None` for a job with zero matches, a **genuinely ambiguous** match
    (see `_resolve_match`) — never picks "the first of several," an honest
    gap beats a confidently wrong cross-reference feeding a duplicate
    warning — or any HTTP/parse/network failure. A failure on one chunk
    never discards results already collected from an earlier chunk in the
    same call.
    """
    results: list[FigiMatch | None] = []
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-OPENFIGI-APIKEY"] = api_key

    for start in range(0, len(jobs), max_jobs_per_request):
        chunk = jobs[start : start + max_jobs_per_request]
        body = [_job_payload(job) for job in chunk]
        try:
            response = httpx.post(MAPPING_URL, json=body, headers=headers, timeout=timeout)
            if response.status_code != 200:
                results.extend([None] * len(chunk))
                continue
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            results.extend([None] * len(chunk))
            continue

        for row in payload:
            results.append(_resolve_match(row.get("data") or []))

    return results


def _resolve_match(data: list[dict]) -> FigiMatch | None:
    """A bare ISIN lookup returns one row per exchange/vendor feed for the
    *same* security (e.g. 275 rows for Apple's ISIN) — plain row count is
    not an ambiguity signal. A handful of synthetic CFD-style rows (e.g.
    ticker "AAPLGBX" on exchange "X1") carry no `shareClassFIGI` at all;
    those are dropped before judging agreement. What's left is ambiguous
    only if those rows disagree on `shareClassFIGI` — the field this app
    actually keys duplicate-detection on (see module docstring) — which
    means genuinely different real-world securities, not just different
    listings of the same one.
    """
    candidates = [row for row in data if row.get("shareClassFIGI")]
    if not candidates:
        return None
    share_class_figis = {row["shareClassFIGI"] for row in candidates}
    if len(share_class_figis) != 1:
        return None
    share_class_figi = share_class_figis.pop()
    primary = next((row for row in candidates if row.get("figi") == row.get("compositeFIGI")), candidates[0])
    figi = primary.get("figi")
    if not figi:
        return None
    return FigiMatch(figi=figi, share_class_figi=share_class_figi, name=primary.get("name"))


def _job_payload(job: FigiJob) -> dict:
    if job.isin:
        return {"idType": "ID_ISIN", "idValue": job.isin}
    payload: dict = {"idType": "TICKER", "idValue": job.ticker}
    if job.currency:
        payload["currency"] = job.currency
    return payload
