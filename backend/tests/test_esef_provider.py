"""Tests for the ESEF fundamentals provider (filings.xbrl.org).

Fixture entities/facts are shaped after real data pulled live from the API
while building this provider — including a real, confirmed-live mistake this
code has to avoid: `edgar.names_match` alone matches "Air Liquide" against
"Air Products & Chemicals, Inc." on the shared word "air", which is why
`resolve()` uses the stricter `find_by_name`-style rule instead. That case is
tested directly (`test_a_single_shared_word_is_not_enough_to_match`), not just
asserted in a docstring.
"""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from app.providers.base import SymbolNotFound
from app.providers.esef import EsefProvider


def client_returning(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


ENTITIES = [
    {"id": "1", "attributes": {"name": "DASSAULT SYSTEMES", "identifier": "96950065LBWY0APQIM86"}},
    {
        "id": "2",
        "attributes": {
            "name": "L'AIR LIQUIDE SOCIETE ANONYME POUR L'ETUDE ET L'EXPLOITATION DES PROCEDES GEORGES CLAUDE",
            "identifier": "969500MMPQVHK671GT54",
        },
    },
    # A real decoy: shares the single word "air" with "Air Liquide", which is
    # exactly the false positive `names_match` alone produces.
    {"id": "3", "attributes": {"name": "AIR PRODUCTS AND CHEMICALS INC", "identifier": "US0000AIRPRODUCTS01"}},
    # Two entities that would BOTH satisfy a "contains every word" search for
    # the same query — must refuse as ambiguous rather than pick one. Neither
    # name's token set is exactly equal to the query's (which would make it a
    # unique exact match instead), only a proper superset of it.
    {"id": "4", "attributes": {"name": "GENERIC EUROPE NORTHERN SERVICES", "identifier": "AMBIGUOUS0000000001"}},
    {"id": "5", "attributes": {"name": "GENERIC EUROPE SOUTHERN SERVICES", "identifier": "AMBIGUOUS0000000002"}},
]

FILINGS = {
    "data": [
        {
            "attributes": {
                "period_end": "2024-12-31",
                "json_url": "/96950065LBWY0APQIM86/2024-12-31/report.json",
            }
        },
        {
            "attributes": {
                "period_end": "2023-12-31",
                "json_url": "/96950065LBWY0APQIM86/2023-12-31/report.json",
            }
        },
        # No JSON representation — must be skipped, not crash.
        {"attributes": {"period_end": "2020-12-31", "json_url": None}},
    ]
}

FACTS_2024 = {
    "facts": {
        # The real consolidated total for FY2024 — duration period.
        "profit_2024": {
            "value": "1198100000.0",
            "dimensions": {
                "concept": "ifrs-full:ProfitLoss",
                "entity": "scheme:96950065LBWY0APQIM86",
                "period": "2024-01-01T00:00:00/2025-01-01T00:00:00",
                "unit": "iso4217:EUR",
            },
        },
        # A segment-dimensioned sub-total for the same concept and period —
        # must be excluded, not summed or mistaken for the total.
        "profit_2024_segment": {
            "value": "999999999.0",
            "dimensions": {
                "concept": "ifrs-full:ProfitLoss",
                "entity": "scheme:96950065LBWY0APQIM86",
                "period": "2024-01-01T00:00:00/2025-01-01T00:00:00",
                "unit": "iso4217:EUR",
                "ifrs-full:ComponentsOfEquityAxis": "ifrs-full:RetainedEarningsMember",
            },
        },
        # Balance-sheet figure — instant period, exclusive end (real FY2024
        # balance is reported as of 2025-01-01, not 2024-12-31).
        "assets_2024": {
            "value": "15545900000.0",
            "dimensions": {
                "concept": "ifrs-full:Assets",
                "entity": "scheme:96950065LBWY0APQIM86",
                "period": "2025-01-01T00:00:00",
                "unit": "iso4217:EUR",
            },
        },
    }
}

FACTS_2023 = {
    "facts": {
        "profit_2023": {
            "value": "1050200000.0",
            "dimensions": {
                "concept": "ifrs-full:ProfitLoss",
                "entity": "scheme:96950065LBWY0APQIM86",
                "period": "2023-01-01T00:00:00/2024-01-01T00:00:00",
                "unit": "iso4217:EUR",
            },
        },
    }
}


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/api/entities":
        return httpx.Response(200, json={"data": ENTITIES, "meta": {"count": len(ENTITIES)}})
    if path.endswith("/filings"):
        return httpx.Response(200, json=FILINGS)
    if "2024-12-31/report.json" in path:
        return httpx.Response(200, json=FACTS_2024)
    if "2023-12-31/report.json" in path:
        return httpx.Response(200, json=FACTS_2023)
    return httpx.Response(404, json={"errors": [{"detail": "not found"}]})


def _provider() -> EsefProvider:
    return EsefProvider(min_interval_seconds=0, client=client_returning(_handler))


class TestResolve:
    def test_resolves_an_exact_name(self):
        lei, registrant = _provider().resolve("Dassault Systemes")
        assert lei == "96950065LBWY0APQIM86"
        assert registrant == "DASSAULT SYSTEMES"

    def test_resolves_a_much_longer_legal_name(self):
        lei, registrant = _provider().resolve("Air Liquide")
        assert lei == "969500MMPQVHK671GT54"
        assert "AIR LIQUIDE" in registrant

    def test_a_single_shared_word_is_not_enough_to_match(self):
        """The real, confirmed-live false positive this provider exists to
        avoid: `edgar.names_match("Air Liquide", "Air Products & Chemicals,
        Inc.")` alone returns True on the shared word "air". Searching the
        whole entity index needs the stricter rule."""
        lei, registrant = _provider().resolve("Air Liquide")
        assert "AIR PRODUCTS" not in registrant

    def test_ambiguous_match_is_refused(self):
        with pytest.raises(SymbolNotFound, match="more than one"):
            _provider().resolve("Generic Europe Holding")

    def test_no_match_is_refused(self):
        with pytest.raises(SymbolNotFound):
            _provider().resolve("Some Unrelated Company Name")

    def test_entity_index_is_cached_after_first_resolve(self):
        calls = []

        def counting_handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/entities":
                calls.append(1)
            return _handler(request)

        provider = EsefProvider(min_interval_seconds=0, client=client_returning(counting_handler))
        provider.resolve("Dassault Systemes")
        provider.resolve("Air Liquide")

        assert len(calls) == 1


class TestFetch:
    def test_keeps_only_the_consolidated_total_not_the_segment_breakdown(self):
        result = _provider().fetch("Dassault Systemes")
        net_income = result.concepts["net_income"]
        assert [f.value for f in net_income] == [1050200000.0, 1198100000.0]

    def test_duration_period_is_parsed_to_the_real_fiscal_year(self):
        result = _provider().fetch("Dassault Systemes")
        net_income = result.concepts["net_income"]
        latest = net_income[-1]
        assert latest.fiscal_year == 2024
        assert latest.period_end == date(2024, 12, 31)

    def test_instant_period_is_parsed_to_the_real_fiscal_year(self):
        result = _provider().fetch("Dassault Systemes")
        assets = result.concepts["assets"]
        assert len(assets) == 1
        assert assets[0].fiscal_year == 2024
        assert assets[0].period_end == date(2024, 12, 31)

    def test_currency_is_parsed_from_the_unit(self):
        result = _provider().fetch("Dassault Systemes")
        assert result.concepts["net_income"][0].currency == "EUR"

    def test_filings_with_no_json_url_are_skipped_not_crashed_on(self):
        # The fixture's 2020 filing has json_url: None — fetch() must not
        # raise over it.
        result = _provider().fetch("Dassault Systemes")
        assert result.lei == "96950065LBWY0APQIM86"

    def test_unreported_concepts_are_listed_as_missing(self):
        result = _provider().fetch("Dassault Systemes")
        assert "capex" in result.missing
        assert "net_income" not in result.missing

    def test_unresolvable_name_raises_symbol_not_found(self):
        with pytest.raises(SymbolNotFound):
            _provider().fetch("Some Unrelated Company Name")


def test_is_enabled_is_always_true_no_key_required():
    assert EsefProvider().is_enabled() is True
