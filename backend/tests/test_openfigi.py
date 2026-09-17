"""Tests for the OpenFIGI canonical-identity client — see DEVLOG
"Decision 3u.76"."""

from __future__ import annotations

import httpx
import pytest

from app.providers.openfigi import FigiJob, FigiMatch, map_instruments


def _mapping_response(rows: list[dict]) -> httpx.Response:
    return httpx.Response(200, json=rows)


def _match(figi: str, share_class_figi: str | None = None, name: str | None = None) -> dict:
    return {"data": [{"figi": figi, "shareClassFIGI": share_class_figi, "name": name}]}


class TestMapInstruments:
    def test_a_single_isin_job_resolves(self, monkeypatch):
        monkeypatch.setattr(
            httpx, "post", lambda *a, **k: _mapping_response([_match("BBG000B9XRY4", "BBG001S5N8V8", "Apple Inc")])
        )

        results = map_instruments([FigiJob(isin="US0378331005", ticker=None, currency=None)], None, 10)

        assert results == [FigiMatch(figi="BBG000B9XRY4", share_class_figi="BBG001S5N8V8", name="Apple Inc")]

    def test_a_ticker_plus_currency_job_resolves(self, monkeypatch):
        captured = {}

        def fake_post(url, json, headers, timeout):
            captured["body"] = json
            return _mapping_response([_match("BBG000BVPV84", "BBG001S5PQL7")])

        monkeypatch.setattr(httpx, "post", fake_post)

        results = map_instruments([FigiJob(isin=None, ticker="NKE", currency="USD")], None, 10)

        assert results[0].figi == "BBG000BVPV84"
        assert captured["body"] == [{"idType": "TICKER", "idValue": "NKE", "currency": "USD"}]

    def test_isin_takes_priority_over_ticker_in_the_request_payload(self, monkeypatch):
        captured = {}

        def fake_post(url, json, headers, timeout):
            captured["body"] = json
            return _mapping_response([_match("X")])

        monkeypatch.setattr(httpx, "post", fake_post)

        map_instruments([FigiJob(isin="US0378331005", ticker="AAPL", currency="USD")], None, 10)

        assert captured["body"] == [{"idType": "ID_ISIN", "idValue": "US0378331005"}]

    def test_zero_matches_is_none_not_a_guess(self, monkeypatch):
        monkeypatch.setattr(httpx, "post", lambda *a, **k: _mapping_response([{"data": [], "warning": "No identifier found."}]))

        results = map_instruments([FigiJob(isin=None, ticker="ZZZNOPE", currency=None)], None, 10)

        assert results == [None]

    def test_ambiguous_match_is_none_never_picks_the_first(self, monkeypatch):
        """More than one candidate for the same query — an honest gap beats
        a confidently wrong cross-reference feeding a duplicate warning."""
        monkeypatch.setattr(
            httpx,
            "post",
            lambda *a, **k: _mapping_response(
                [{"data": [{"figi": "AAA", "shareClassFIGI": "X"}, {"figi": "BBB", "shareClassFIGI": "Y"}]}]
            ),
        )

        results = map_instruments([FigiJob(isin=None, ticker="F", currency=None)], None, 10)

        assert results == [None]

    def test_http_non_200_is_none_not_a_raise(self, monkeypatch):
        monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(429, json={}))

        results = map_instruments([FigiJob(isin="US0378331005", ticker=None, currency=None)], None, 10)

        assert results == [None]

    def test_network_error_is_none_not_a_raise(self, monkeypatch):
        def raise_error(*a, **k):
            raise httpx.ConnectError("no route to host")

        monkeypatch.setattr(httpx, "post", raise_error)

        results = map_instruments([FigiJob(isin="US0378331005", ticker=None, currency=None)], None, 10)

        assert results == [None]

    def test_more_jobs_than_the_chunk_size_split_into_multiple_calls_in_order(self, monkeypatch):
        calls = []

        def fake_post(url, json, headers, timeout):
            calls.append(json)
            # One match per job in this chunk, echoing back a distinct FIGI
            # so the test can confirm result order survives the split.
            return _mapping_response([_match(f"FIGI-{job['idValue']}") for job in json])

        monkeypatch.setattr(httpx, "post", fake_post)

        jobs = [FigiJob(isin=None, ticker=f"T{i}", currency=None) for i in range(5)]
        results = map_instruments(jobs, None, max_jobs_per_request=2)

        assert len(calls) == 3  # 2 + 2 + 1
        assert [r.figi for r in results] == [f"FIGI-T{i}" for i in range(5)]

    def test_api_key_sets_the_header(self, monkeypatch):
        captured = {}

        def fake_post(url, json, headers, timeout):
            captured["headers"] = headers
            return _mapping_response([_match("X")])

        monkeypatch.setattr(httpx, "post", fake_post)

        map_instruments([FigiJob(isin="US0378331005", ticker=None, currency=None)], "my-key", 10)

        assert captured["headers"]["X-OPENFIGI-APIKEY"] == "my-key"

    def test_no_api_key_omits_the_header(self, monkeypatch):
        captured = {}

        def fake_post(url, json, headers, timeout):
            captured["headers"] = headers
            return _mapping_response([_match("X")])

        monkeypatch.setattr(httpx, "post", fake_post)

        map_instruments([FigiJob(isin="US0378331005", ticker=None, currency=None)], None, 10)

        assert "X-OPENFIGI-APIKEY" not in captured["headers"]
