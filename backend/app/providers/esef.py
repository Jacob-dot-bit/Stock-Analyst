"""European company fundamentals from ESEF filings (filings.xbrl.org).

The EU has required listed companies to file their annual financial reports in
XBRL (the "European Single Electronic Format", ESEF) since fiscal year 2020.
XBRL International — the standards body behind XBRL itself — maintains a free,
public repository of these filings at filings.xbrl.org, with a real JSON API.
No key, no signup, no rate-limit tier to hit.

Added specifically because SEC EDGAR (`providers/edgar.py`) cannot reach
European companies that don't file with the SEC at all — confirmed live for
four real holdings (Air Liquide, LVMH, Dassault Systèmes, Air France KLM), none
of which are SEC filers under any discoverable ticker. This is a second,
additive source, not a replacement: SEC EDGAR stays primary (`fundamentals/
service.py` tries it first), this is the fallback for whatever it can't
answer. See DEVLOG "Decision 3t.1".

## No ticker system — only a Legal Entity Identifier (LEI)

Unlike EDGAR, there is no per-market ticker index here. Every ESEF filer is
identified by its LEI, resolved from the company's registered name via the
entity list (`GET /api/entities`, ~7,300 entities). The full list is fetched
once and cached in-process, the same discipline `EdgarProvider._load_index()`
already uses for the SEC ticker index.

## Searching by name needs a stricter rule than verifying one

`edgar.names_match` accepts a single shared token — correct once a ticker has
already narrowed the field to one candidate, and dangerous when searching a
~7,300-entity index from scratch: confirmed live, `names_match("Air Liquide",
"Air Products & Chemicals, Inc.")` returns `True`, purely on the shared word
"air". `resolve()` below instead mirrors `edgar.find_by_name`'s stricter rule
(exact token-set match wins; else a single candidate containing every
significant word; else refuse as ambiguous), reusing `edgar._name_tokens`
directly rather than re-deriving it.

## One filing per fiscal year, not one call for the whole history

SEC's `companyfacts` endpoint returns a company's entire reported history in
one response. ESEF has no equivalent — each fiscal year's annual report is a
separate filing (`GET /api/entities/{lei}/filings`), each with its own XBRL-JSON
export. `fetch()` pulls the most recent `MAX_FILINGS` filings and merges them,
newest first (a year already supplied by a more recent filing is not
overwritten by an older one, since restatements in later filings are the more
authoritative figure — same principle `edgar._extract` already applies for
same-tag conflicts).

## A concept appears many times per filing — only one of them is real

Confirmed live: one filing's JSON repeats a concept like `ifrs-full:ProfitLoss`
under several different dimensional breakdowns (segment, equity component,
etc.) alongside the one genuine consolidated total — 22 `ProfitLoss` facts in
one real filing, only 2 of them the actual total. The two are told apart by
their `dimensions` keys: the consolidated total has exactly `{concept, entity,
period, unit}`; anything with an extra key is a sub-total. Only the former is
ever kept.

## Same concept tags as SEC's IFRS filers — reused, not reinvented

`edgar.IFRS_CONCEPT_TAGS` (built for SEC's 20-F/IFRS foreign filers, e.g.
TotalEnergies) already lists the exact XBRL tag names ESEF filings use —
confirmed live against real filings. Imported directly rather than duplicated.

## XBRL period dates are the exclusive end, not the reported date

A duration fact's period is `"start/end"`; an instant fact's is a single
datetime. Both report the *day after* the actual period end — confirmed live,
a FY2024 (calendar year) balance-sheet figure carries period
`"2025-01-01T00:00:00"`, not `"2024-12-31"`. `_parse_fact` subtracts one day
from whichever end is reported before using it as `fiscal_year`/`period_end`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from app.providers.base import ProviderUnavailable, SymbolNotFound, Throttle
from app.providers.edgar import IFRS_CONCEPT_TAGS, AnnualFigure, _name_tokens

ENTITIES_URL = "https://filings.xbrl.org/api/entities"
FILINGS_BASE = "https://filings.xbrl.org"

#: How many of an entity's most recent filings to fetch. Matches the observed
#: real depth (Dassault Systèmes has 6, spanning 2020-2025) without unbounded
#: requests for an entity with a much longer filing history.
MAX_FILINGS = 6

#: A fact's `dimensions` keys when it is the real consolidated total rather
#: than a sub-total broken out along an extra dimensional axis.
_PURE_DIMENSION_KEYS = frozenset({"concept", "entity", "period", "unit"})


@dataclass
class EsefFundamentals:
    lei: str
    company_name: str
    #: concept -> figures, oldest first — same shape as `edgar.Fundamentals`.
    concepts: dict[str, list[AnnualFigure]] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)

    def latest(self, concept: str) -> AnnualFigure | None:
        figures = self.concepts.get(concept)
        return figures[-1] if figures else None


class EsefProvider:
    name = "esef"

    def __init__(
        self,
        min_interval_seconds: float = 0.3,
        timeout_seconds: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._throttle = Throttle(min_interval_seconds)
        self._timeout = timeout_seconds
        self._client = client
        self._entity_index: list[dict[str, Any]] | None = None

    def is_enabled(self) -> bool:
        # No key, no signup — free and open by design. Unlike EdgarProvider,
        # never disabled.
        return True

    def _get(self, url: str, params: dict | None = None) -> Any:
        client = self._client or httpx.Client(timeout=self._timeout)
        owns_client = self._client is None
        try:
            self._throttle.wait()
            try:
                response = client.get(url, params=params)
            except httpx.HTTPError as exc:
                raise ProviderUnavailable(str(exc)) from exc

            if response.status_code == 404:
                raise SymbolNotFound(url)
            if response.status_code >= 400:
                raise ProviderUnavailable(f"HTTP {response.status_code}")

            try:
                return response.json()
            except ValueError as exc:
                raise ProviderUnavailable("malformed JSON response") from exc
        finally:
            if owns_client:
                client.close()

    def _load_entities(self) -> list[dict[str, Any]]:
        if self._entity_index is None:
            entities: list[dict[str, Any]] = []
            page = 1
            while True:
                payload = self._get(ENTITIES_URL, params={"page[size]": 200, "page[number]": page})
                entities.extend(payload.get("data") or [])
                total = (payload.get("meta") or {}).get("count", len(entities))
                if len(entities) >= total:
                    break
                page += 1
            self._entity_index = entities
        return self._entity_index

    def resolve(self, name: str) -> tuple[str, str]:
        """Map a registered company name to `(lei, registrant_name)`.

        See the module docstring: deliberately stricter than
        `edgar.names_match` (a single shared token is not enough here), and
        refuses ambiguity outright rather than guessing between candidates —
        the same trade-off `edgar.find_by_name` already made for exactly this
        reason (Decision 3a.1).
        """
        wanted = _name_tokens(name)
        if not wanted:
            raise SymbolNotFound(f"'{name}' has no significant words to search on")

        exact: list[dict[str, Any]] = []
        contains: list[dict[str, Any]] = []
        for entity in self._load_entities():
            registrant = str(entity.get("attributes", {}).get("name") or "")
            tokens = _name_tokens(registrant)
            if not tokens:
                continue
            if tokens == wanted:
                exact.append(entity)
            elif wanted <= tokens:
                contains.append(entity)

        for candidates in (exact, contains):
            # `entity["id"]` is filings.xbrl.org's own internal numeric row
            # id, not usable against the real API — the identifier every
            # other endpoint actually expects (LEI, or a national scheme
            # identifier when no LEI is registered) is `attributes.identifier`.
            leis = {c.get("attributes", {}).get("identifier") for c in candidates}
            if len(leis) == 1:
                best = candidates[0]
                return (
                    str(best["attributes"]["identifier"]),
                    str(best.get("attributes", {}).get("name") or ""),
                )
            if len(candidates) > 1:
                raise SymbolNotFound(f"'{name}' matches more than one ESEF entity ambiguously")

        raise SymbolNotFound(f"'{name}' not found in the ESEF filing index")

    def fetch(self, name: str) -> EsefFundamentals:
        """Fetch and normalise one company's annual figures from its most
        recent ESEF filings."""
        lei, registrant = self.resolve(name)

        filings_payload = self._get(f"{ENTITIES_URL}/{lei}/filings")
        filings = sorted(
            filings_payload.get("data") or [],
            key=lambda f: f.get("attributes", {}).get("period_end") or "",
            reverse=True,
        )[:MAX_FILINGS]

        concepts: dict[str, list[AnnualFigure]] = {}
        for filing in filings:
            json_url = filing.get("attributes", {}).get("json_url")
            if not json_url:
                continue
            try:
                payload = self._get(f"{FILINGS_BASE}{json_url}")
            except (ProviderUnavailable, SymbolNotFound):
                continue
            _merge_filing(concepts, payload.get("facts") or {})

        for series in concepts.values():
            series.sort(key=lambda f: f.fiscal_year)

        result = EsefFundamentals(lei=lei, company_name=registrant, concepts=concepts)
        result.missing = [c for c in IFRS_CONCEPT_TAGS if c not in concepts]
        return result


def _index_pure_facts(facts: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    by_concept: dict[str, list[dict[str, Any]]] = {}
    for fact in facts.values():
        dims = fact.get("dimensions") or {}
        if set(dims.keys()) != _PURE_DIMENSION_KEYS:
            continue
        concept = dims.get("concept")
        if concept:
            by_concept.setdefault(concept, []).append(fact)
    return by_concept


def _merge_filing(concepts: dict[str, list[AnnualFigure]], facts: dict[str, Any]) -> None:
    by_concept = _index_pure_facts(facts)
    for concept_name, tags in IFRS_CONCEPT_TAGS.items():
        series = concepts.setdefault(concept_name, [])
        for tag in tags:
            for fact in by_concept.get(f"ifrs-full:{tag}", []):
                figure = _parse_fact(fact, tag)
                if figure is None:
                    continue
                # A more recent filing (processed earlier, since callers pass
                # newest-first) already supplied this year — its figure is
                # the more authoritative one, so an older filing's restated
                # or comparative value for the same year is not added.
                if any(existing.fiscal_year == figure.fiscal_year for existing in series):
                    continue
                series.append(figure)
        if not series:
            del concepts[concept_name]


def _parse_fact(fact: dict[str, Any], tag: str) -> AnnualFigure | None:
    dims = fact.get("dimensions") or {}
    value = fact.get("value")
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None

    period = str(dims.get("period") or "")
    end_str = period.split("/")[-1] if "/" in period else period
    try:
        reported_end = datetime.strptime(end_str[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    # XBRL periods report the exclusive end (the day *after* the real period
    # end) — see the module docstring.
    period_end: date = reported_end - timedelta(days=1)

    unit = str(dims.get("unit") or "")
    currency = unit.split(":")[-1] if ":" in unit else unit
    if not currency:
        return None

    return AnnualFigure(period_end.year, period_end, value, tag, currency)
