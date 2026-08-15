"""Tests for the market-data provider layer.

All network calls are mocked. Real calls live behind `@pytest.mark.network` and are
excluded by default: a test suite that depends on a rate-limited third party is a test
suite that fails for reasons unrelated to the code.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from app.providers.base import (
    Bar,
    Cooldown,
    InstrumentRef,
    PlanLimited,
    PriceProvider,
    ProviderChain,
    ProviderUnavailable,
    RateLimited,
    SymbolNotFound,
    Throttle,
)
from app.providers.alpha_vantage import AlphaVantageProvider
from app.providers.boursorama import BoursoramaProvider
from app.providers.eodhd import EodhidProvider
from app.providers.fmp import FmpProvider
from app.providers.frankfurt import FrankfurtProvider, looks_like_isin
from app.providers.polygon import PolygonProvider
from app.providers.twelvedata import TwelveDataProvider
from app.providers.yahoo import YahooProvider


def yahoo_payload(closes: list[float | None], start_epoch: int = 1_700_000_000) -> dict:
    """A chart response shaped like the real one, including null padding."""
    day = 86_400
    return {
        "chart": {
            "error": None,
            "result": [
                {
                    "meta": {"currency": "USD", "symbol": "TEST"},
                    "timestamp": [start_epoch + i * day for i in range(len(closes))],
                    "indicators": {
                        "quote": [
                            {
                                "open": [c for c in closes],
                                "high": [c for c in closes],
                                "low": [c for c in closes],
                                "close": closes,
                                "volume": [1000 if c is not None else None for c in closes],
                            }
                        ]
                    },
                }
            ],
        }
    }


def client_returning(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def yahoo_splits_payload(splits: dict[int, dict]) -> dict:
    """A chart response shaped like Yahoo's real `events=split` payload —
    `splits` keyed by unix timestamp, each an entry with numerator/denominator."""
    return {
        "chart": {
            "error": None,
            "result": [
                {
                    "meta": {"currency": "USD", "symbol": "TEST"},
                    "timestamp": [],
                    "indicators": {"quote": [{"open": [], "high": [], "low": [], "close": [], "volume": []}]},
                    "events": {"splits": splits},
                }
            ],
        }
    }


class TestYahooProvider:
    def test_parses_daily_bars(self):
        provider = YahooProvider(
            min_interval_seconds=0,
            client=client_returning(lambda r: httpx.Response(200, json=yahoo_payload([10.0, 11.0, 12.0]))),
        )

        bars = provider.fetch_daily(InstrumentRef(provider_symbol="AAPL"), date(2023, 11, 1), date(2023, 11, 30))

        assert len(bars) == 3
        assert [b.close for b in bars] == [10.0, 11.0, 12.0]
        assert all(isinstance(b.bar_date, date) for b in bars)

    def test_null_padding_is_dropped(self):
        """Yahoo pads its series with nulls; a bar with no close carries no information."""
        provider = YahooProvider(
            min_interval_seconds=0,
            client=client_returning(
                lambda r: httpx.Response(200, json=yahoo_payload([10.0, None, 12.0]))
            ),
        )

        bars = provider.fetch_daily(InstrumentRef(provider_symbol="AAPL"), date(2023, 11, 1), date(2023, 11, 30))

        assert [b.close for b in bars] == [10.0, 12.0]

    def test_rate_limit_is_reported_as_such(self):
        """429 must be distinguishable from a real failure: it means "try later"."""
        provider = YahooProvider(
            min_interval_seconds=0,
            max_retries=0,
            client=client_returning(lambda r: httpx.Response(429)),
        )

        with pytest.raises(RateLimited):
            provider.fetch_daily(InstrumentRef(provider_symbol="AAPL"), date(2023, 11, 1), date(2023, 11, 30))

    def test_unknown_symbol(self):
        provider = YahooProvider(
            min_interval_seconds=0,
            client=client_returning(lambda r: httpx.Response(404)),
        )

        with pytest.raises(SymbolNotFound):
            provider.fetch_daily(InstrumentRef(provider_symbol="NOPE"), date(2023, 11, 1), date(2023, 11, 30))

    def test_error_inside_a_200_response(self):
        payload = {"chart": {"error": {"code": "Not Found"}, "result": None}}
        provider = YahooProvider(
            min_interval_seconds=0,
            client=client_returning(lambda r: httpx.Response(200, json=payload)),
        )

        with pytest.raises(SymbolNotFound):
            provider.fetch_daily(InstrumentRef(provider_symbol="NOPE"), date(2023, 11, 1), date(2023, 11, 30))

    def test_network_failure_is_wrapped(self):
        def explode(request):
            raise httpx.ConnectError("no route to host")

        provider = YahooProvider(min_interval_seconds=0, client=client_returning(explode))

        with pytest.raises(ProviderUnavailable):
            provider.fetch_daily(InstrumentRef(provider_symbol="AAPL"), date(2023, 11, 1), date(2023, 11, 30))

    def test_retries_then_gives_up_on_repeated_429(self, monkeypatch):
        monkeypatch.setattr("app.providers.yahoo.time.sleep", lambda _: None)
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            return httpx.Response(429)

        provider = YahooProvider(min_interval_seconds=0, max_retries=2, client=client_returning(handler))

        with pytest.raises(RateLimited):
            provider.fetch_daily(InstrumentRef(provider_symbol="AAPL"), date(2023, 11, 1), date(2023, 11, 30))
        assert calls["n"] == 3  # initial attempt + 2 retries


class TestYahooFetchSplits:
    def test_parses_a_real_shaped_split_event(self):
        payload = yahoo_splits_payload(
            {"1718000000": {"date": 1718000000, "numerator": 10, "denominator": 1, "splitRatio": "10:1"}}
        )
        provider = YahooProvider(
            min_interval_seconds=0, client=client_returning(lambda r: httpx.Response(200, json=payload))
        )

        events = provider.fetch_splits(InstrumentRef(provider_symbol="NVDA"), date(2020, 1, 1), date(2025, 1, 1))

        assert len(events) == 1
        assert events[0].numerator == 10.0
        assert events[0].denominator == 1.0
        assert events[0].effective_date == datetime.fromtimestamp(1718000000, tz=UTC).date()

    def test_no_events_block_yields_empty_list(self):
        payload = yahoo_payload([10.0, 11.0])  # no "events" key at all
        provider = YahooProvider(
            min_interval_seconds=0, client=client_returning(lambda r: httpx.Response(200, json=payload))
        )

        events = provider.fetch_splits(InstrumentRef(provider_symbol="AAPL"), date(2020, 1, 1), date(2025, 1, 1))

        assert events == []

    def test_multiple_splits_sorted_chronologically(self):
        payload = yahoo_splits_payload(
            {
                "1700000000": {"date": 1700000000, "numerator": 3, "denominator": 1},
                "1600000000": {"date": 1600000000, "numerator": 2, "denominator": 1},
            }
        )
        provider = YahooProvider(
            min_interval_seconds=0, client=client_returning(lambda r: httpx.Response(200, json=payload))
        )

        events = provider.fetch_splits(InstrumentRef(provider_symbol="TEST"), date(2020, 1, 1), date(2025, 1, 1))

        assert [e.effective_date for e in events] == sorted(e.effective_date for e in events)

    def test_symbol_not_found_propagates(self):
        provider = YahooProvider(
            min_interval_seconds=0, client=client_returning(lambda r: httpx.Response(404))
        )

        with pytest.raises(SymbolNotFound):
            provider.fetch_splits(InstrumentRef(provider_symbol="NOPE"), date(2020, 1, 1), date(2025, 1, 1))


class TestFmpFetchSplits:
    """FMP replaced Yahoo as the corporate-actions detection source (DEVLOG
    "Decision 3u.34") after Yahoo's real-portfolio scan proved unreliable.
    Payload shapes here match `/stable/splits` verified live against real
    symbols: NVDA (`200`, a real 10:1 split) and GOOGL (`200`, a real 20:1
    split) both worked; APLD — the one reverse-split case in hand —
    answered `402` on the free plan, so the reverse-split numerator/
    denominator direction below is the documented/assumed convention
    (matching `_classify_ratio`'s existing rule and EODHD's confirmed
    `1/6` for the same APLD event via a different endpoint), not something
    this suite could confirm against a real FMP response."""

    def test_parses_a_real_shaped_split(self):
        # Shaped exactly like FMP's real NVDA response, verified live.
        payload = [{"symbol": "NVDA", "date": "2024-06-10", "numerator": 10, "denominator": 1, "splitType": "stock-split"}]
        provider = FmpProvider(
            api_key="k", min_interval_seconds=0,
            client=client_returning(lambda r: httpx.Response(200, json=payload)),
        )

        events = provider.fetch_splits(InstrumentRef(provider_symbol="NVDA"), date(2020, 1, 1), date(2025, 1, 1))

        assert len(events) == 1
        assert events[0].numerator == 10.0
        assert events[0].denominator == 1.0
        assert events[0].effective_date == date(2024, 6, 10)

    def test_reverse_split_shaped_payload(self):
        # Convention assumed, not live-verified — see class docstring.
        payload = [{"symbol": "APLD", "date": "2022-04-13", "numerator": 1, "denominator": 6, "splitType": "reverse-split"}]
        provider = FmpProvider(
            api_key="k", min_interval_seconds=0,
            client=client_returning(lambda r: httpx.Response(200, json=payload)),
        )

        events = provider.fetch_splits(InstrumentRef(provider_symbol="APLD"), date(2020, 1, 1), date(2025, 1, 1))

        assert events[0].numerator == 1.0
        assert events[0].denominator == 6.0

    def test_empty_list_means_no_splits_ever_not_an_error(self):
        """Unlike `fetch_daily`'s empty-history-means-unknown-symbol rule —
        a stock that never split legitimately answers with an empty list."""
        provider = FmpProvider(
            api_key="k", min_interval_seconds=0,
            client=client_returning(lambda r: httpx.Response(200, json=[])),
        )

        events = provider.fetch_splits(InstrumentRef(provider_symbol="NEVER"), date(2020, 1, 1), date(2025, 1, 1))

        assert events == []

    def test_multiple_splits_sorted_chronologically(self):
        payload = [
            {"symbol": "NVDA", "date": "2024-06-10", "numerator": 10, "denominator": 1},
            {"symbol": "NVDA", "date": "2021-07-20", "numerator": 4, "denominator": 1},
        ]
        provider = FmpProvider(
            api_key="k", min_interval_seconds=0,
            client=client_returning(lambda r: httpx.Response(200, json=payload)),
        )

        events = provider.fetch_splits(InstrumentRef(provider_symbol="NVDA"), date(2020, 1, 1), date(2025, 1, 1))

        assert [e.effective_date for e in events] == sorted(e.effective_date for e in events)

    def test_date_range_filters_out_of_window_entries(self):
        payload = [
            {"symbol": "NVDA", "date": "2024-06-10", "numerator": 10, "denominator": 1},
            {"symbol": "NVDA", "date": "2000-06-27", "numerator": 2, "denominator": 1},
        ]
        provider = FmpProvider(
            api_key="k", min_interval_seconds=0,
            client=client_returning(lambda r: httpx.Response(200, json=payload)),
        )

        events = provider.fetch_splits(InstrumentRef(provider_symbol="NVDA"), date(2023, 1, 1), date(2025, 1, 1))

        assert len(events) == 1
        assert events[0].effective_date == date(2024, 6, 10)

    def test_429_is_rate_limited(self):
        provider = FmpProvider(
            api_key="k", min_interval_seconds=0,
            client=client_returning(lambda r: httpx.Response(429)),
        )

        with pytest.raises(RateLimited):
            provider.fetch_splits(InstrumentRef(provider_symbol="NVDA"), date(2020, 1, 1), date(2025, 1, 1))

    def test_402_is_plan_limited(self):
        """Verified live against APLD — a plain US symbol, gated anyway."""
        provider = FmpProvider(
            api_key="k", min_interval_seconds=0,
            client=client_returning(lambda r: httpx.Response(402, text="not available under your current subscription")),
        )

        with pytest.raises(PlanLimited):
            provider.fetch_splits(InstrumentRef(provider_symbol="APLD"), date(2020, 1, 1), date(2025, 1, 1))

    def test_unparseable_body_is_provider_unavailable(self):
        provider = FmpProvider(
            api_key="k", min_interval_seconds=0,
            client=client_returning(lambda r: httpx.Response(200, text="not json")),
        )

        with pytest.raises(ProviderUnavailable):
            provider.fetch_splits(InstrumentRef(provider_symbol="NVDA"), date(2020, 1, 1), date(2025, 1, 1))

    def test_no_api_key_is_provider_unavailable(self):
        provider = FmpProvider(api_key=None, min_interval_seconds=0)

        with pytest.raises(ProviderUnavailable):
            provider.fetch_splits(InstrumentRef(provider_symbol="NVDA"), date(2020, 1, 1), date(2025, 1, 1))


class TestEodhdFetchSplits:
    """The targeted, single-instrument fallback source (DEVLOG "Decision
    3u.35"), built for the exact case FMP's free tier won't answer: APLD,
    a US small-cap. Payload shape matches `/api/splits/APLD.US` verified
    live: `[{"date": "2022-04-13", "split": "1.000000/6.000000"}]` — the
    real 1:6 reverse split."""

    def test_parses_the_real_apld_shaped_payload(self):
        payload = [{"date": "2022-04-13", "split": "1.000000/6.000000"}]
        provider = EodhidProvider(
            api_key="k", client=client_returning(lambda r: httpx.Response(200, json=payload))
        )

        events = provider.fetch_splits(InstrumentRef(provider_symbol="APLD"), date(2020, 1, 1), date(2025, 1, 1))

        assert len(events) == 1
        assert events[0].numerator == 1.0
        assert events[0].denominator == 6.0
        assert events[0].effective_date == date(2022, 4, 13)

    def test_appends_us_suffix_for_us_listings(self):
        seen_urls = []

        def handler(request):
            seen_urls.append(str(request.url))
            return httpx.Response(200, json=[])

        provider = EodhidProvider(api_key="k", client=client_returning(handler))
        provider.fetch_splits(
            InstrumentRef(provider_symbol="APLD", broker_symbol="APLD.US"), date(2020, 1, 1), date(2025, 1, 1)
        )

        assert seen_urls == ["https://eodhd.com/api/splits/APLD.US?api_token=k&fmt=json"]

    def test_empty_list_means_no_splits_ever_not_an_error(self):
        provider = EodhidProvider(api_key="k", client=client_returning(lambda r: httpx.Response(200, json=[])))

        events = provider.fetch_splits(InstrumentRef(provider_symbol="NEVER"), date(2020, 1, 1), date(2025, 1, 1))

        assert events == []

    def test_429_is_rate_limited(self):
        provider = EodhidProvider(api_key="k", client=client_returning(lambda r: httpx.Response(429)))

        with pytest.raises(RateLimited):
            provider.fetch_splits(InstrumentRef(provider_symbol="APLD"), date(2020, 1, 1), date(2025, 1, 1))

    def test_unparseable_body_is_provider_unavailable(self):
        provider = EodhidProvider(api_key="k", client=client_returning(lambda r: httpx.Response(200, text="not json")))

        with pytest.raises(ProviderUnavailable):
            provider.fetch_splits(InstrumentRef(provider_symbol="APLD"), date(2020, 1, 1), date(2025, 1, 1))

    def test_date_range_filters_out_of_window_entries(self):
        payload = [
            {"date": "2022-04-13", "split": "1.000000/6.000000"},
            {"date": "2010-01-01", "split": "2.000000/1.000000"},
        ]
        provider = EodhidProvider(api_key="k", client=client_returning(lambda r: httpx.Response(200, json=payload)))

        events = provider.fetch_splits(InstrumentRef(provider_symbol="APLD"), date(2020, 1, 1), date(2025, 1, 1))

        assert len(events) == 1
        assert events[0].effective_date == date(2022, 4, 13)


class TestAlphaVantageFetchSplits:
    """Alpha Vantage joined FMP/EODHD as an automatic cross-checking source
    for split detection (DEVLOG "Decision 3u.41"). Payload shape matches
    `function=SPLITS` verified live: `data[].split_factor` is a single
    float rather than a numerator/denominator pair — `"4.0"` for a real
    4:1 AAPL split, `"0.1667"` for APLD's real 1:6 reverse split (matching
    EODHD's confirmed `1/6` for the same event)."""

    def test_parses_a_real_shaped_split(self):
        payload = {"symbol": "AAPL", "data": [{"effective_date": "2020-08-31", "split_factor": "4.0"}]}
        provider = AlphaVantageProvider(
            api_key="k", client=client_returning(lambda r: httpx.Response(200, json=payload))
        )

        events = provider.fetch_splits(InstrumentRef(provider_symbol="AAPL"), date(2015, 1, 1), date(2025, 1, 1))

        assert len(events) == 1
        assert events[0].numerator == 4.0
        assert events[0].denominator == 1.0
        assert events[0].effective_date == date(2020, 8, 31)

    def test_reverse_split_factor_below_one_converts_to_numerator_denominator(self):
        # Verified live against APLD's real 1:6 reverse split: 1/0.1667 ≈ 6,
        # matching FMP/EODHD/Polygon's own 1:6 for the same event.
        payload = {"symbol": "APLD", "data": [{"effective_date": "2022-04-13", "split_factor": "0.1667"}]}
        provider = AlphaVantageProvider(
            api_key="k", client=client_returning(lambda r: httpx.Response(200, json=payload))
        )

        events = provider.fetch_splits(InstrumentRef(provider_symbol="APLD"), date(2020, 1, 1), date(2025, 1, 1))

        assert events[0].numerator == 1.0
        assert events[0].denominator == 6.0

    def test_empty_list_means_no_splits_ever_not_an_error(self):
        payload = {"symbol": "NEVER", "data": []}
        provider = AlphaVantageProvider(
            api_key="k", client=client_returning(lambda r: httpx.Response(200, json=payload))
        )

        events = provider.fetch_splits(InstrumentRef(provider_symbol="NEVER"), date(2020, 1, 1), date(2025, 1, 1))

        assert events == []

    def test_date_range_filters_out_of_window_entries(self):
        payload = {
            "symbol": "AAPL",
            "data": [
                {"effective_date": "2020-08-31", "split_factor": "4.0"},
                {"effective_date": "1987-06-16", "split_factor": "2.0"},
            ],
        }
        provider = AlphaVantageProvider(
            api_key="k", client=client_returning(lambda r: httpx.Response(200, json=payload))
        )

        events = provider.fetch_splits(InstrumentRef(provider_symbol="AAPL"), date(2015, 1, 1), date(2025, 1, 1))

        assert len(events) == 1
        assert events[0].effective_date == date(2020, 8, 31)

    def test_note_field_is_rate_limited(self):
        provider = AlphaVantageProvider(
            api_key="k",
            client=client_returning(lambda r: httpx.Response(200, json={"Note": "API call frequency"})),
        )

        with pytest.raises(RateLimited):
            provider.fetch_splits(InstrumentRef(provider_symbol="AAPL"), date(2020, 1, 1), date(2025, 1, 1))

    def test_information_field_is_rate_limited(self):
        """The free-tier daily-quota shape (distinct from "Note") — see
        `fetch_daily`'s identical handling."""
        provider = AlphaVantageProvider(
            api_key="k",
            client=client_returning(lambda r: httpx.Response(200, json={"Information": "daily limit reached"})),
        )

        with pytest.raises(RateLimited):
            provider.fetch_splits(InstrumentRef(provider_symbol="AAPL"), date(2020, 1, 1), date(2025, 1, 1))

    def test_error_message_is_symbol_not_found(self):
        provider = AlphaVantageProvider(
            api_key="k",
            client=client_returning(lambda r: httpx.Response(200, json={"Error Message": "invalid symbol"})),
        )

        with pytest.raises(SymbolNotFound):
            provider.fetch_splits(InstrumentRef(provider_symbol="XXXX"), date(2020, 1, 1), date(2025, 1, 1))

    def test_unparseable_body_is_provider_unavailable(self):
        provider = AlphaVantageProvider(
            api_key="k", client=client_returning(lambda r: httpx.Response(200, text="not json"))
        )

        with pytest.raises(ProviderUnavailable):
            provider.fetch_splits(InstrumentRef(provider_symbol="AAPL"), date(2020, 1, 1), date(2025, 1, 1))


class TestPolygonFetchSplits:
    """Polygon (Massive) joined Alpha Vantage as an automatic cross-checking
    source for split detection (DEVLOG "Decision 3u.41"). Payload shape
    matches `/v3/reference/splits` verified live: `results[].split_from`/
    `split_to` map directly onto `denominator`/`numerator`, no factor
    conversion needed, unlike Alpha Vantage."""

    def test_parses_a_real_shaped_split(self):
        payload = {"results": [{"ticker": "APLD", "execution_date": "2022-04-13", "split_from": 6, "split_to": 1}]}
        provider = PolygonProvider(
            api_key="k", client=client_returning(lambda r: httpx.Response(200, json=payload))
        )

        events = provider.fetch_splits(InstrumentRef(provider_symbol="APLD"), date(2020, 1, 1), date(2025, 1, 1))

        assert len(events) == 1
        assert events[0].numerator == 1.0
        assert events[0].denominator == 6.0
        assert events[0].effective_date == date(2022, 4, 13)

    def test_forward_split_shaped_payload(self):
        payload = {"results": [{"ticker": "AAPL", "execution_date": "2020-08-31", "split_from": 1, "split_to": 4}]}
        provider = PolygonProvider(
            api_key="k", client=client_returning(lambda r: httpx.Response(200, json=payload))
        )

        events = provider.fetch_splits(InstrumentRef(provider_symbol="AAPL"), date(2015, 1, 1), date(2025, 1, 1))

        assert events[0].numerator == 4.0
        assert events[0].denominator == 1.0

    def test_empty_results_means_no_splits_ever_not_an_error(self):
        provider = PolygonProvider(
            api_key="k", client=client_returning(lambda r: httpx.Response(200, json={"results": []}))
        )

        events = provider.fetch_splits(InstrumentRef(provider_symbol="NEVER"), date(2020, 1, 1), date(2025, 1, 1))

        assert events == []

    def test_date_range_filters_out_of_window_entries(self):
        payload = {
            "results": [
                {"ticker": "AAPL", "execution_date": "2020-08-31", "split_from": 1, "split_to": 4},
                {"ticker": "AAPL", "execution_date": "1987-06-16", "split_from": 1, "split_to": 2},
            ]
        }
        provider = PolygonProvider(
            api_key="k", client=client_returning(lambda r: httpx.Response(200, json=payload))
        )

        events = provider.fetch_splits(InstrumentRef(provider_symbol="AAPL"), date(2015, 1, 1), date(2025, 1, 1))

        assert len(events) == 1
        assert events[0].effective_date == date(2020, 8, 31)

    def test_429_is_rate_limited(self):
        provider = PolygonProvider(api_key="k", client=client_returning(lambda r: httpx.Response(429)))

        with pytest.raises(RateLimited):
            provider.fetch_splits(InstrumentRef(provider_symbol="AAPL"), date(2020, 1, 1), date(2025, 1, 1))

    def test_401_is_provider_unavailable(self):
        provider = PolygonProvider(
            api_key="bad", client=client_returning(lambda r: httpx.Response(401, json={"error": "Unauthorized"}))
        )

        with pytest.raises(ProviderUnavailable):
            provider.fetch_splits(InstrumentRef(provider_symbol="AAPL"), date(2020, 1, 1), date(2025, 1, 1))

    def test_unparseable_body_is_provider_unavailable(self):
        provider = PolygonProvider(api_key="k", client=client_returning(lambda r: httpx.Response(200, text="not json")))

        with pytest.raises(ProviderUnavailable):
            provider.fetch_splits(InstrumentRef(provider_symbol="AAPL"), date(2020, 1, 1), date(2025, 1, 1))


class TestTwelveDataProvider:
    def test_disabled_without_a_key(self):
        assert TwelveDataProvider(api_key=None).is_enabled() is False
        assert TwelveDataProvider(api_key="k").is_enabled() is True

    def test_parses_and_sorts_chronologically(self):
        """The API answers newest-first; everything downstream assumes the opposite."""
        payload = {
            "values": [
                {"datetime": "2024-01-03", "open": "3", "high": "3", "low": "3", "close": "3", "volume": "30"},
                {"datetime": "2024-01-02", "open": "2", "high": "2", "low": "2", "close": "2", "volume": "20"},
                {"datetime": "2024-01-01", "open": "1", "high": "1", "low": "1", "close": "1", "volume": "10"},
            ],
            "status": "ok",
        }
        provider = TwelveDataProvider(
            api_key="k",
            min_interval_seconds=0,
            client=client_returning(lambda r: httpx.Response(200, json=payload)),
        )

        bars = provider.fetch_daily(InstrumentRef(provider_symbol="AAPL"), date(2024, 1, 1), date(2024, 1, 3))

        assert [b.bar_date.day for b in bars] == [1, 2, 3]
        assert [b.close for b in bars] == [1.0, 2.0, 3.0]

    def test_error_reported_inside_a_200_response(self):
        """Twelve Data signals failures in the body, not the status code."""
        payload = {"status": "error", "code": 429, "message": "API credits limit reached"}
        provider = TwelveDataProvider(
            api_key="k",
            min_interval_seconds=0,
            client=client_returning(lambda r: httpx.Response(200, json=payload)),
        )

        with pytest.raises(RateLimited):
            provider.fetch_daily(InstrumentRef(provider_symbol="AAPL"), date(2024, 1, 1), date(2024, 1, 3))

    def test_unknown_symbol_in_body(self):
        payload = {"status": "error", "code": 404, "message": "symbol not found"}
        provider = TwelveDataProvider(
            api_key="k",
            min_interval_seconds=0,
            client=client_returning(lambda r: httpx.Response(200, json=payload)),
        )

        with pytest.raises(SymbolNotFound):
            provider.fetch_daily(InstrumentRef(provider_symbol="NOPE"), date(2024, 1, 1), date(2024, 1, 3))


# --- Test doubles for the chain ---------------------------------------------


class FakeProvider(PriceProvider):
    def __init__(self, name: str, bars: list[Bar] | None = None, error: Exception | None = None,
                 enabled: bool = True, serves: bool = True) -> None:
        self.name = name
        self._bars = bars or []
        self._error = error
        self._enabled = enabled
        self._serves = serves
        self.calls = 0
        # Real providers each have their own Throttle serializing calls to
        # themselves; this fake has none, so a test driving several
        # instruments through ONE shared FakeProvider concurrently (DEVLOG
        # "Decision 3n.1") needs its own lock around the counter — otherwise
        # `self.calls += 1` is a genuine, flaky lost-update race, not a real
        # signal about the app's own concurrency correctness.
        self._calls_lock = threading.Lock()

    def is_enabled(self) -> bool:
        return self._enabled

    def can_serve(self, ref) -> bool:
        return self._serves

    def fetch_daily(self, ref, start, end):
        with self._calls_lock:
            self.calls += 1
        self.last_ref = ref
        if self._error:
            raise self._error
        return self._bars


def a_bar(day: int = 1) -> Bar:
    return Bar(bar_date=date(2024, 1, day), open=1.0, high=1.0, low=1.0, close=1.0, volume=1.0)


class TestProviderChain:
    def test_first_working_provider_wins(self):
        first = FakeProvider("first", bars=[a_bar()])
        second = FakeProvider("second", bars=[a_bar()])

        result = ProviderChain([first, second]).fetch_daily(InstrumentRef(provider_symbol="A"), date(2024, 1, 1), date(2024, 1, 2))

        assert result.provider == "first"
        assert second.calls == 0  # the fallback is not called needlessly

    def test_falls_back_when_the_first_is_rate_limited(self):
        first = FakeProvider("first", error=RateLimited("slow down"))
        second = FakeProvider("second", bars=[a_bar()])

        result = ProviderChain([first, second]).fetch_daily(InstrumentRef(provider_symbol="A"), date(2024, 1, 1), date(2024, 1, 2))

        assert result.provider == "second"
        assert result.succeeded
        # The failed attempt stays visible: "where did this come from" needs an answer.
        assert result.attempts[0].reason == "rate_limited"

    def test_disabled_providers_are_skipped(self):
        disabled = FakeProvider("disabled", bars=[a_bar()], enabled=False)
        working = FakeProvider("working", bars=[a_bar()])

        result = ProviderChain([disabled, working]).fetch_daily(InstrumentRef(provider_symbol="A"), date(2024, 1, 1), date(2024, 1, 2))

        assert result.provider == "working"
        assert disabled.calls == 0

    def test_empty_answer_is_not_success(self):
        """An empty series is not an error, but it is not usable data either."""
        empty = FakeProvider("empty", bars=[])
        working = FakeProvider("working", bars=[a_bar()])

        result = ProviderChain([empty, working]).fetch_daily(InstrumentRef(provider_symbol="A"), date(2024, 1, 1), date(2024, 1, 2))

        assert result.provider == "working"

    def test_all_failed_reports_every_attempt(self):
        chain = ProviderChain(
            [FakeProvider("a", error=SymbolNotFound("x")), FakeProvider("b", error=ProviderUnavailable("x"))]
        )

        result = chain.fetch_daily(InstrumentRef(provider_symbol="A"), date(2024, 1, 1), date(2024, 1, 2))

        assert not result.succeeded
        assert [a.reason for a in result.attempts] == ["symbol_not_found", "unavailable"]

    def test_rate_limited_only_when_every_attempt_was_throttled(self):
        """"Try again later" must not be reported when the symbol is simply wrong."""
        throttled = ProviderChain(
            [FakeProvider("a", error=RateLimited("x")), FakeProvider("b", error=RateLimited("x"))]
        ).fetch_daily(InstrumentRef(provider_symbol="A"), date(2024, 1, 1), date(2024, 1, 2))
        mixed = ProviderChain(
            [FakeProvider("a", error=RateLimited("x")), FakeProvider("b", error=SymbolNotFound("x"))]
        ).fetch_daily(InstrumentRef(provider_symbol="A"), date(2024, 1, 1), date(2024, 1, 2))

        assert throttled.rate_limited is True
        assert mixed.rate_limited is False

    def test_unexpected_exception_does_not_kill_the_chain(self):
        """A bug in one provider must not take down a whole refresh."""
        broken = FakeProvider("broken", error=ValueError("boom"))
        working = FakeProvider("working", bars=[a_bar()])

        result = ProviderChain([broken, working]).fetch_daily(InstrumentRef(provider_symbol="A"), date(2024, 1, 1), date(2024, 1, 2))

        assert result.provider == "working"
        assert result.attempts[0].reason == "failed"


class TestThrottle:
    def test_spaces_calls_out(self, monkeypatch):
        slept: list[float] = []
        clock = {"t": 0.0}
        monkeypatch.setattr("app.providers.base.time.monotonic", lambda: clock["t"])
        monkeypatch.setattr("app.providers.base.time.sleep", lambda s: slept.append(s))

        throttle = Throttle(2.0)
        throttle.wait()  # first call must not sleep: there is nothing to space out from
        clock["t"] = 0.5
        throttle.wait()  # only 0.5s elapsed, so wait the remaining 1.5s

        assert slept == [pytest.approx(1.5)]

    def test_zero_interval_never_sleeps(self, monkeypatch):
        monkeypatch.setattr(
            "app.providers.base.time.sleep",
            lambda s: pytest.fail("should not sleep when the interval is zero"),
        )
        Throttle(0).wait()

    def test_serializes_concurrent_callers(self):
        """A parallel refresh (DEVLOG "Decision 3n.1") can have several worker
        threads reach the SAME provider's shared Throttle instance at once — a
        bare, unlocked check-then-sleep would let them all observe the same
        stale `_last_call` and skip the wait entirely. Real threads, real
        clock: proves the lock actually serializes, not just that it exists.
        """
        throttle = Throttle(0.05)
        timestamps: list[float] = []
        record_lock = threading.Lock()

        def call():
            throttle.wait()
            with record_lock:
                timestamps.append(time.monotonic())

        threads = [threading.Thread(target=call) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        timestamps.sort()
        gaps = [b - a for a, b in zip(timestamps, timestamps[1:])]
        # A little slack for scheduling jitter — the guarantee is "not less
        # than min_interval", not exact spacing.
        assert all(gap >= 0.045 for gap in gaps), gaps


@pytest.mark.network
class TestLiveProviders:
    """Excluded by default. Run with: pytest -m network

    These document what was actually measured against the live endpoints, and exist so
    the assumptions can be re-checked when a provider changes.
    """

    def test_yahoo_returns_history(self):
        try:
            bars = YahooProvider().fetch_daily(
                InstrumentRef(provider_symbol="AAPL"), date.today().replace(month=1, day=1), date.today()
            )
        except RateLimited:
            # Being throttled says nothing about whether our parsing is right, so this
            # is inconclusive rather than a failure. Yahoo blocks by IP and the block
            # can outlast an hour; a red test here would only train people to ignore it.
            pytest.skip("Yahoo is rate-limiting this IP — run again from another network")

        assert len(bars) > 100
        assert all(bar.close is not None for bar in bars)


class TestFrankfurtProvider:
    """The only free source found that covers European venues.

    Keyed on ISIN and nothing else: tickers, slugs and company names were all tested
    against the live endpoint and rejected.
    """

    def test_parses_a_udf_payload(self):
        payload = {
            "s": "ok",
            "t": [1_751_328_000, 1_751_414_400],
            "o": [70.0, 71.0],
            "h": [72.0, 73.0],
            "l": [69.0, 70.0],
            "c": [71.5, 72.5],
            "v": [1000.0, 1100.0],
        }
        provider = FrankfurtProvider(
            min_interval_seconds=0,
            client=client_returning(lambda r: httpx.Response(200, json=payload)),
        )

        bars = provider.fetch_daily(InstrumentRef(isin="FR0000120271"), date(2025, 7, 1), date(2025, 7, 2))

        assert [b.close for b in bars] == [71.5, 72.5]
        assert [b.volume for b in bars] == [1000.0, 1100.0]
        assert bars[0].bar_date < bars[1].bar_date

    def test_without_an_isin_it_steps_aside(self):
        """Most instruments have no ISIN recorded; the chain should just move on."""
        provider = FrankfurtProvider(min_interval_seconds=0, client=client_returning(lambda r: httpx.Response(200)))

        with pytest.raises(SymbolNotFound):
            provider.fetch_daily(InstrumentRef(provider_symbol="AAPL"), date(2025, 7, 1), date(2025, 7, 2))

    def test_a_ticker_in_the_isin_field_is_rejected_before_any_request(self):
        """A malformed ISIN must never reach the network as if it were valid."""
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            return httpx.Response(200, json={"s": "ok"})

        provider = FrankfurtProvider(min_interval_seconds=0, client=client_returning(handler))

        with pytest.raises(SymbolNotFound):
            provider.fetch_daily(InstrumentRef(isin="TTE.FR"), date(2025, 7, 1), date(2025, 7, 2))
        assert calls["n"] == 0

    def test_empty_body_means_the_isin_is_not_listed_here(self):
        """The live endpoint answers 200 with {} for an ISIN Frankfurt does not list."""
        provider = FrankfurtProvider(
            min_interval_seconds=0,
            client=client_returning(lambda r: httpx.Response(200, json={})),
        )

        with pytest.raises(SymbolNotFound):
            provider.fetch_daily(InstrumentRef(isin="FR0000120271"), date(2025, 7, 1), date(2025, 7, 2))

    def test_no_data_status(self):
        provider = FrankfurtProvider(
            min_interval_seconds=0,
            client=client_returning(lambda r: httpx.Response(200, json={"s": "no_data"})),
        )

        with pytest.raises(SymbolNotFound):
            provider.fetch_daily(InstrumentRef(isin="FR0000120271"), date(2025, 7, 1), date(2025, 7, 2))

    @pytest.mark.parametrize(
        ("value", "valid"),
        [
            ("FR0000120271", True),
            ("NL0010273215", True),
            ("fr0000120271", True),  # case is normalised
            ("TTE.FR", False),
            ("FR000012027", False),  # too short
            ("FR00001202712", False),  # too long
            ("", False),
            (None, False),
        ],
    )
    def test_isin_shape(self, value, valid):
        assert looks_like_isin(value) is valid


class TestFmpProvider:
    """Written against the documented shape; free-tier coverage is unverified."""

    def test_disabled_without_a_key(self):
        assert FmpProvider(api_key=None).is_enabled() is False

    def test_parses_and_sorts_chronologically(self):
        payload = {
            "symbol": "DCAM.PA",
            "historical": [
                {"date": "2026-08-12", "open": 6.3, "high": 6.4, "low": 6.2, "close": 6.35, "volume": 200},
                {"date": "2026-08-11", "open": 6.2, "high": 6.3, "low": 6.1, "close": 6.25, "volume": 100},
            ],
        }
        provider = FmpProvider(
            api_key="k",
            min_interval_seconds=0,
            client=client_returning(lambda r: httpx.Response(200, json=payload)),
        )

        bars = provider.fetch_daily(InstrumentRef(provider_symbol="DCAM.PA"), date(2026, 8, 1), date(2026, 8, 12))

        assert [b.close for b in bars] == [6.25, 6.35]
        assert bars[0].bar_date < bars[1].bar_date

    def test_accepts_a_bare_list_too(self):
        """Some symbols answer with a list rather than the wrapped object."""
        payload = [{"date": "2026-08-11", "open": 1, "high": 1, "low": 1, "close": 1.5, "volume": 1}]
        provider = FmpProvider(
            api_key="k", min_interval_seconds=0,
            client=client_returning(lambda r: httpx.Response(200, json=payload)),
        )

        assert len(provider.fetch_daily(InstrumentRef(provider_symbol="X.PA"), date(2026, 8, 1), date(2026, 8, 12))) == 1

    def test_plan_limitation_is_not_reported_as_a_bad_symbol(self):
        """The lesson from Twelve Data: a plan boundary must not look like a mapping error."""
        payload = {"Error Message": "This endpoint is not available under your current plan"}
        provider = FmpProvider(
            api_key="k", min_interval_seconds=0,
            client=client_returning(lambda r: httpx.Response(403, json=payload)),
        )

        with pytest.raises(PlanLimited):
            provider.fetch_daily(InstrumentRef(provider_symbol="DCAM.PA"), date(2026, 8, 1), date(2026, 8, 12))

    def test_empty_history_means_unknown_symbol(self):
        provider = FmpProvider(
            api_key="k", min_interval_seconds=0,
            client=client_returning(lambda r: httpx.Response(200, json={"symbol": "X", "historical": []})),
        )

        with pytest.raises(SymbolNotFound):
            provider.fetch_daily(InstrumentRef(provider_symbol="X.PA"), date(2026, 8, 1), date(2026, 8, 12))

    def test_402_is_a_coverage_boundary_not_a_bad_symbol(self):
        """How the free tier refuses non-US symbols. Verified live on TTE.PA."""
        provider = FmpProvider(
            api_key="k", min_interval_seconds=0,
            client=client_returning(lambda r: httpx.Response(402, text="not available under your current subscription")),
        )

        with pytest.raises(PlanLimited):
            provider.fetch_daily(InstrumentRef(provider_symbol="TTE.PA"), date(2026, 8, 1), date(2026, 8, 12))

    def test_a_retired_endpoint_is_not_a_plan_boundary(self):
        """Nothing the user buys fixes a dead endpoint; do not send them to a pricing page."""
        payload = {"Error Message": "Legacy Endpoint : Due to Legacy endpoints being no longer supported"}
        provider = FmpProvider(
            api_key="k", min_interval_seconds=0,
            client=client_returning(lambda r: httpx.Response(200, json=payload)),
        )

        with pytest.raises(ProviderUnavailable):
            provider.fetch_daily(InstrumentRef(provider_symbol="AAPL"), date(2026, 8, 1), date(2026, 8, 12))


class TestCooldown:
    """A 429 is a request to back off, not a suggestion.

    Hammering through a throttle is what turns a short limit into a long block — which
    is exactly how this project's own development traffic got an IP blocked for hours.
    """

    def test_a_throttled_provider_is_not_asked_again_immediately(self):
        throttled = FakeProvider("yahoo", error=RateLimited("slow down"))
        chain = ProviderChain([throttled], cooldown_seconds=900)
        ref = InstrumentRef(provider_symbol="A")

        for _ in range(5):
            chain.fetch_daily(ref, date(2024, 1, 1), date(2024, 1, 2))

        # One refusal is enough; the next thirty instruments must not each retry it.
        assert throttled.calls == 1

    def test_the_cooldown_still_reports_the_reason(self):
        """Silence would look like a bug; the user needs to know why nothing happened."""
        chain = ProviderChain([FakeProvider("yahoo", error=RateLimited("x"))], cooldown_seconds=900)
        ref = InstrumentRef(provider_symbol="A")

        chain.fetch_daily(ref, date(2024, 1, 1), date(2024, 1, 2))
        second = chain.fetch_daily(ref, date(2024, 1, 1), date(2024, 1, 2))

        assert second.rate_limited
        assert second.attempts[0].reason == "rate_limited"

    def test_a_cooled_down_provider_does_not_block_the_others(self):
        """Backing off from one source must not stop the chain finding another."""
        chain = ProviderChain(
            [FakeProvider("yahoo", error=RateLimited("x")), FakeProvider("frankfurt", bars=[a_bar()])],
            cooldown_seconds=900,
        )
        ref = InstrumentRef(provider_symbol="A")

        chain.fetch_daily(ref, date(2024, 1, 1), date(2024, 1, 2))
        second = chain.fetch_daily(ref, date(2024, 1, 1), date(2024, 1, 2))

        assert second.provider == "frankfurt"

    def test_it_expires(self):
        chain = ProviderChain([FakeProvider("yahoo", error=RateLimited("x"))], cooldown_seconds=0.01)
        chain.cooldown.start("yahoo")
        time.sleep(0.02)

        assert chain.cooldown.is_active("yahoo") is False

    def test_zero_cooldown_never_blocks(self):
        provider = FakeProvider("yahoo", error=RateLimited("x"))
        chain = ProviderChain([provider], cooldown_seconds=0)
        ref = InstrumentRef(provider_symbol="A")

        chain.fetch_daily(ref, date(2024, 1, 1), date(2024, 1, 2))
        chain.fetch_daily(ref, date(2024, 1, 1), date(2024, 1, 2))

        assert provider.calls == 2

    def test_concurrent_start_and_is_active_do_not_corrupt_state(self):
        """A parallel refresh (DEVLOG "Decision 3n.1") can have several worker
        threads racing `start()`/`is_active()` on the same shared Cooldown at
        once — `is_active()` both reads AND deletes from the underlying dict,
        the exact shape that raises `RuntimeError: dictionary changed size
        during iteration` or worse when unsynchronized. The real assertion
        here is "no exception", not a specific value.
        """
        cooldown = Cooldown(900)
        errors: list[Exception] = []

        def hammer():
            try:
                for _ in range(200):
                    cooldown.start("fmp")
                    cooldown.is_active("fmp")
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=hammer) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert cooldown.is_active("fmp") is True


class TestOnAttemptCallback:
    """`on_attempt` is the quota-usage counting hook (see DEVLOG "Decision 3m.1") —
    it must fire exactly once per real network call, never for a skip."""

    def test_fires_once_for_a_successful_call(self):
        provider = FakeProvider("fmp", bars=[a_bar()])
        chain = ProviderChain([provider])
        seen = []

        chain.fetch_daily(
            InstrumentRef(provider_symbol="A"),
            date(2024, 1, 1),
            date(2024, 1, 2),
            on_attempt=seen.append,
        )

        assert seen == ["fmp"]

    def test_does_not_fire_on_a_cooldown_skip(self):
        provider = FakeProvider("fmp", error=RateLimited("x"))
        chain = ProviderChain([provider], cooldown_seconds=900)
        ref = InstrumentRef(provider_symbol="A")
        seen = []

        chain.fetch_daily(ref, date(2024, 1, 1), date(2024, 1, 2), on_attempt=seen.append)
        chain.fetch_daily(ref, date(2024, 1, 1), date(2024, 1, 2), on_attempt=seen.append)

        # The provider was really only asked once — the second round was a
        # cooldown skip and must not be counted as a request.
        assert seen == ["fmp"]

    def test_does_not_fire_when_can_serve_is_false(self):
        provider = FakeProvider("fmp", bars=[a_bar()], serves=False)
        chain = ProviderChain([provider])
        seen = []

        chain.fetch_daily(
            InstrumentRef(provider_symbol="A"),
            date(2024, 1, 1),
            date(2024, 1, 2),
            on_attempt=seen.append,
        )

        assert seen == []

    def test_fetch_quote_fires_once_via_the_fetch_daily_fallback(self):
        """FakeProvider has no dedicated fetch_quote, so `fetch_quote` falls
        back to a short `fetch_daily` window — still exactly one real call."""
        provider = FakeProvider("fmp", bars=[a_bar()])
        chain = ProviderChain([provider])
        seen = []

        chain.fetch_quote(InstrumentRef(provider_symbol="A"), on_attempt=seen.append)

        assert seen == ["fmp"]


class TestBoursoramaProvider:
    """The source that closed the Euronext gap after every other free option failed."""

    @staticmethod
    def payload(name: str, points: int = 3, start_day: int = 20_300) -> dict:
        return {
            "d": {
                "Name": name,
                "SymbolId": "1rTX",
                "QuoteTab": [
                    {"d": start_day + i, "o": 10.0 + i, "h": 11.0 + i, "l": 9.0 + i,
                     "c": 10.5 + i, "v": 1000 + i}
                    for i in range(points)
                ],
            }
        }

    def test_parses_day_indexed_quotes(self):
        """Dates are day counts from 1970-01-01, not timestamps."""
        provider = BoursoramaProvider(
            min_interval_seconds=0,
            client=client_returning(lambda r: httpx.Response(200, json=self.payload("LVMH"))),
        )

        bars = provider.fetch_daily(
            InstrumentRef(broker_symbol="MC.FR", name="LVMH", category="STOCK"),
            date(2025, 1, 1), date(2027, 1, 1),
        )

        assert len(bars) == 3
        assert bars[0].bar_date == date(1970, 1, 1) + timedelta(days=20_300)
        assert bars[0].bar_date < bars[-1].bar_date

    def test_a_wrong_instrument_is_refused(self):
        """The response names the instrument, so a ticker collision is catchable.

        This project has already attached one company's financials to another by
        trusting a symbol; a price series is just as easy to get wrong quietly.
        """
        provider = BoursoramaProvider(
            min_interval_seconds=0,
            client=client_returning(lambda r: httpx.Response(200, json=self.payload("ORMAT TECHNOLOGIES"))),
        )

        with pytest.raises(SymbolNotFound):
            provider.fetch_daily(
                InstrumentRef(broker_symbol="ORA.FR", name="Orange", category="STOCK"),
                date(2025, 1, 1), date(2027, 1, 1),
            )

    def test_the_category_picks_the_namespace(self):
        """Trackers live under 1rT, Paris shares under 1rP."""
        seen: list[str] = []

        def handler(request):
            seen.append(dict(request.url.params)["symbol"])
            return httpx.Response(200, json=self.payload("Amundi CAC 40 UCITS ETF"))

        provider = BoursoramaProvider(min_interval_seconds=0, client=client_returning(handler))
        provider.fetch_daily(
            InstrumentRef(broker_symbol="CAC.FR", name="CAC 40", category="ETF"),
            date(2025, 1, 1), date(2027, 1, 1),
        )

        assert seen[0] == "1rTCAC"

    def test_the_other_prefix_is_tried_when_the_first_misses(self):
        answers = [httpx.Response(410, json=[]), httpx.Response(200, json=self.payload("LVMH"))]
        provider = BoursoramaProvider(
            min_interval_seconds=0,
            client=client_returning(lambda r: answers.pop(0)),
        )

        bars = provider.fetch_daily(
            InstrumentRef(broker_symbol="MC.FR", name="LVMH", category="ETF"),
            date(2025, 1, 1), date(2027, 1, 1),
        )

        assert bars  # recovered on the second namespace

    def test_410_means_unknown_symbol(self):
        provider = BoursoramaProvider(
            min_interval_seconds=0,
            client=client_returning(lambda r: httpx.Response(410, json=[])),
        )

        with pytest.raises(SymbolNotFound):
            provider.fetch_daily(
                InstrumentRef(broker_symbol="NOPE.FR", name="Nope", category="STOCK"),
                date(2025, 1, 1), date(2027, 1, 1),
            )

    def test_the_ajax_header_is_always_sent(self):
        """Without it the endpoint answers 410 with an empty body, whatever the symbol."""
        captured: dict = {}

        def handler(request):
            captured.update(request.headers)
            return httpx.Response(200, json=self.payload("LVMH"))

        # No injected client: the provider must set the header on the one it builds.
        provider = BoursoramaProvider(min_interval_seconds=0)
        from app.providers.boursorama import HEADERS

        assert HEADERS["X-Requested-With"] == "XMLHttpRequest"

    def test_dates_outside_the_window_are_dropped(self):
        provider = BoursoramaProvider(
            min_interval_seconds=0,
            client=client_returning(lambda r: httpx.Response(200, json=self.payload("LVMH", points=5))),
        )

        bars = provider.fetch_daily(
            InstrumentRef(broker_symbol="MC.FR", name="LVMH", category="STOCK"),
            date(1970, 1, 1), date(1970, 1, 2),
        )

        assert bars == []


class TestMarketRouting:
    """Providers declare what they can serve, so the chain skips hopeless calls.

    A French holding sent to a US-only free tier costs a request and several seconds to
    be told something already known — and that request comes out of a daily quota.
    """

    def test_a_provider_that_cannot_serve_is_not_called(self):
        wrong = FakeProvider("us-only", bars=[a_bar()], serves=False)
        right = FakeProvider("europe", bars=[a_bar()])

        result = ProviderChain([wrong, right]).fetch_daily(
            InstrumentRef(provider_symbol="TTE.PA", broker_symbol="TTE.FR"),
            date(2024, 1, 1), date(2024, 1, 2),
        )

        assert wrong.calls == 0
        assert result.provider == "europe"

    def test_skipping_is_not_recorded_as_a_failed_attempt(self):
        """Nothing was attempted; listing it would bury the real reasons in noise."""
        result = ProviderChain(
            [FakeProvider("us-only", serves=False), FakeProvider("europe", bars=[a_bar()])]
        ).fetch_daily(InstrumentRef(provider_symbol="X"), date(2024, 1, 1), date(2024, 1, 2))

        assert [a.provider for a in result.attempts] == ["europe"]

    @pytest.mark.parametrize(
        ("broker_symbol", "expected"),
        [("AAPL.US", True), ("TTE.FR", False), ("ASML.NL", False), ("NOSUFFIX", False)],
    )
    def test_us_listings_are_identified_from_the_broker_symbol(self, broker_symbol, expected):
        from app.providers.base import is_us_listing

        assert is_us_listing(InstrumentRef(broker_symbol=broker_symbol)) is expected


class TestProviderScopes:
    """Each provider's declared scope must match what was measured live."""

    def test_us_only_free_tiers_decline_european_holdings(self):
        european = InstrumentRef(provider_symbol="TTE.PA", broker_symbol="TTE.FR")
        american = InstrumentRef(provider_symbol="AAPL", broker_symbol="AAPL.US")

        for provider in (TwelveDataProvider(api_key="k"), FmpProvider(api_key="k")):
            assert provider.can_serve(european) is False
            assert provider.can_serve(american) is True

    def test_boursorama_declines_us_holdings(self):
        provider = BoursoramaProvider()

        assert provider.can_serve(InstrumentRef(broker_symbol="AAPL.US")) is False
        assert provider.can_serve(InstrumentRef(broker_symbol="MC.FR", category="STOCK")) is True

    def test_frankfurt_needs_an_isin(self):
        provider = FrankfurtProvider()

        assert provider.can_serve(InstrumentRef(broker_symbol="MC.FR")) is False
        assert provider.can_serve(InstrumentRef(isin="FR0000121014")) is True

    def test_yahoo_serves_anything_with_a_symbol(self):
        """Its coverage really is worldwide; only reachability limits it."""
        provider = YahooProvider()

        assert provider.can_serve(InstrumentRef(provider_symbol="DCAM.PA")) is True
        assert provider.can_serve(InstrumentRef()) is False
