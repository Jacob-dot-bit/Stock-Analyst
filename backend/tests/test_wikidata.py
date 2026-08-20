"""Tests for the Wikidata sector fallback (non-US holdings FMP's free tier can't reach)."""

from __future__ import annotations

import httpx
import pytest

from app.providers import wikidata


def _search_response(ids: list[str]) -> httpx.Response:
    return httpx.Response(200, json={"search": [{"id": qid} for qid in ids]})


def _sparql_response(rows: list[dict]) -> httpx.Response:
    return httpx.Response(200, json={"results": {"bindings": rows}})


def _binding(qid: str, industries: str | None, isin: str | None = None) -> dict:
    binding = {"item": {"value": f"http://www.wikidata.org/entity/{qid}"}}
    if industries is not None:
        binding["industries"] = {"value": industries}
    if isin is not None:
        binding["isinSample"] = {"value": isin}
    return binding


class TestResolveSector:
    def test_maps_a_known_industry_to_the_existing_vocabulary(self, monkeypatch):
        calls = iter(
            [
                _search_response(["Q504998"]),
                _sparql_response([_binding("Q504998", "retail")]),
            ]
        )
        monkeypatch.setattr(httpx, "get", lambda *a, **k: next(calls))

        assert wikidata.resolve_sector("LVMH") == "Consumer Cyclical"

    def test_picks_the_best_ranked_candidate_not_the_first_sparql_row(self, monkeypatch):
        # SPARQL's VALUES does not preserve input order — the response lists
        # the lower-ranked subsidiary first, on purpose, to prove the caller
        # respects search rank rather than response order.
        calls = iter(
            [
                _search_response(["Q1172038", "Q140605825"]),
                _sparql_response(
                    [
                        _binding("Q140605825", "automotive industry"),  # wrong subsidiary, rank 1
                        _binding("Q1172038", "software industry"),  # correct parent, rank 0
                    ]
                ),
            ]
        )
        monkeypatch.setattr(httpx, "get", lambda *a, **k: next(calls))

        assert wikidata.resolve_sector("Dassault Systemes") == "Technology"

    def test_publicly_traded_match_with_no_mappable_industry_stops_there(self, monkeypatch):
        """A correct entity with nothing useful on it must not fall through to
        a lower-ranked, less relevant candidate."""
        calls = iter(
            [
                _search_response(["Q1431486", "Q64990444"]),
                _sparql_response(
                    [
                        _binding("Q1431486", ""),  # right entity, no industry data
                        _binding("Q64990444", "telecommunications industry"),  # lower rank
                    ]
                ),
            ]
        )
        monkeypatch.setattr(httpx, "get", lambda *a, **k: next(calls))

        assert wikidata.resolve_sector("Orange S.A.") is None

    def test_unmapped_industry_is_dropped_not_shown_raw(self, monkeypatch):
        calls = iter(
            [
                _search_response(["Q407237"]),
                _sparql_response([_binding("Q407237", "holding company activities")]),
            ]
        )
        monkeypatch.setattr(httpx, "get", lambda *a, **k: next(calls))

        assert wikidata.resolve_sector("Air France-KLM") is None

    def test_no_search_results_returns_none(self, monkeypatch):
        monkeypatch.setattr(httpx, "get", lambda *a, **k: _search_response([]))
        assert wikidata.resolve_sector("Not A Real Company Xyzzy") is None

    def test_no_publicly_traded_candidate_returns_none(self, monkeypatch):
        # Every candidate lacks P414 (stock exchange), so the SPARQL query
        # (which filters on it) returns nothing at all.
        calls = iter([_search_response(["Q195833"]), _sparql_response([])])
        monkeypatch.setattr(httpx, "get", lambda *a, **k: next(calls))

        assert wikidata.resolve_sector("TotalEnergies cycling team") is None

    def test_network_error_returns_none_rather_than_raising(self, monkeypatch):
        def raise_error(*args, **kwargs):
            raise httpx.ConnectError("no route to host")

        monkeypatch.setattr(httpx, "get", raise_error)
        assert wikidata.resolve_sector("LVMH") is None

    def test_malformed_response_returns_none_rather_than_raising(self, monkeypatch):
        monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(200, json={"unexpected": True}))
        assert wikidata.resolve_sector("LVMH") is None


class TestResolveIsin:
    def test_resolves_isin_for_a_known_company(self, monkeypatch):
        calls = iter(
            [
                _search_response(["Q504998"]),
                _sparql_response([_binding("Q504998", "retail", isin="FR0000121014")]),
            ]
        )
        monkeypatch.setattr(httpx, "get", lambda *a, **k: next(calls))

        assert wikidata.resolve_isin("LVMH") == "FR0000121014"

    def test_publicly_traded_match_with_no_isin_claim_returns_none(self, monkeypatch):
        calls = iter(
            [
                _search_response(["Q1431486"]),
                _sparql_response([_binding("Q1431486", "telecommunications industry")]),
            ]
        )
        monkeypatch.setattr(httpx, "get", lambda *a, **k: next(calls))

        assert wikidata.resolve_isin("Orange S.A.") is None

    def test_no_publicly_traded_candidate_returns_none(self, monkeypatch):
        calls = iter([_search_response(["Q195833"]), _sparql_response([])])
        monkeypatch.setattr(httpx, "get", lambda *a, **k: next(calls))

        assert wikidata.resolve_isin("TotalEnergies cycling team") is None

    def test_no_search_results_returns_none(self, monkeypatch):
        monkeypatch.setattr(httpx, "get", lambda *a, **k: _search_response([]))
        assert wikidata.resolve_isin("Not A Real Company Xyzzy") is None

    def test_network_error_returns_none_rather_than_raising(self, monkeypatch):
        def raise_error(*args, **kwargs):
            raise httpx.ConnectError("no route to host")

        monkeypatch.setattr(httpx, "get", raise_error)
        assert wikidata.resolve_isin("LVMH") is None
