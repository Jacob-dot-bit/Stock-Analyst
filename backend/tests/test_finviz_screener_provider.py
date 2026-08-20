"""Tests for the Finviz preset-screener provider.

See `app/providers/finviz_screener.py`'s own module docstring for why only
two specific, robots.txt-whitelisted presets exist — the tests here also
pin that only those whitelisted scan codes are ever requested, since that
compliance boundary is the entire reason this module is shaped the way it
is (DEVLOG "Decision 3u.20").
"""

from __future__ import annotations

import httpx
import pytest

from app.providers import finviz_screener

SNAPSHOT_HTML = """
<table class="screener_snapshot-table-header">
  <tr><td>Ticker</td><td><a href="stock?t=ZZZ&ty=c">ZZZ</a>[NASD, S&amp;P 500]</td></tr>
  <tr><td>Company</td><td><a href="http://example.com">Zzz Corp</a></td></tr>
  <tr><td>Country</td><td><a href="#">USA</a></td></tr>
  <tr><td>Industry</td><td><a href="#">Software</a></td></tr>
</table>
"""


class TestFetchPreset:
    def test_parses_a_snapshot_block(self, monkeypatch):
        monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(200, text=SNAPSHOT_HTML))

        results = finviz_screener.fetch_preset("insider_buys")

        assert results == [{"ticker": "ZZZ", "name": "Zzz Corp", "country": "USA", "industry": "Software"}]

    def test_unknown_preset_returns_empty_without_a_request(self, monkeypatch):
        def fail_if_called(*args, **kwargs):
            raise AssertionError("must not request an unknown/unwhitelisted preset")

        monkeypatch.setattr(httpx, "get", fail_if_called)

        assert finviz_screener.fetch_preset("custom_pe_filter") == []

    def test_non_200_response_returns_empty(self, monkeypatch):
        monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(500, text=""))

        assert finviz_screener.fetch_preset("oversold") == []

    def test_network_error_returns_empty_rather_than_raising(self, monkeypatch):
        def raise_error(*a, **k):
            raise httpx.ConnectError("no route to host")

        monkeypatch.setattr(httpx, "get", raise_error)

        assert finviz_screener.fetch_preset("oversold") == []

    def test_no_snapshot_blocks_returns_empty(self, monkeypatch):
        monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(200, text="<html></html>"))

        assert finviz_screener.fetch_preset("insider_buys") == []

    def test_only_ever_requests_whitelisted_scan_codes(self, monkeypatch):
        captured: dict = {}

        def fake_get(url, params=None, **kwargs):
            captured.update(params or {})
            return httpx.Response(200, text="")

        monkeypatch.setattr(httpx, "get", fake_get)

        finviz_screener.fetch_preset("insider_buys")
        assert captured["s"] == "it_latestbuys"

        finviz_screener.fetch_preset("oversold")
        assert captured["s"] == "ta_oversold"
