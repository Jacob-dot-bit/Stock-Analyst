"""Tests for the market-data provider layer.

All network calls are mocked. Real calls live behind `@pytest.mark.network` and are
excluded by default: a test suite that depends on a rate-limited third party is a test
suite that fails for reasons unrelated to the code.
"""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from app.providers.base import (
    Bar,
    PriceProvider,
    ProviderChain,
    ProviderUnavailable,
    RateLimited,
    SymbolNotFound,
    Throttle,
)
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


class TestYahooProvider:
    def test_parses_daily_bars(self):
        provider = YahooProvider(
            min_interval_seconds=0,
            client=client_returning(lambda r: httpx.Response(200, json=yahoo_payload([10.0, 11.0, 12.0]))),
        )

        bars = provider.fetch_daily("AAPL", date(2023, 11, 1), date(2023, 11, 30))

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

        bars = provider.fetch_daily("AAPL", date(2023, 11, 1), date(2023, 11, 30))

        assert [b.close for b in bars] == [10.0, 12.0]

    def test_rate_limit_is_reported_as_such(self):
        """429 must be distinguishable from a real failure: it means "try later"."""
        provider = YahooProvider(
            min_interval_seconds=0,
            max_retries=0,
            client=client_returning(lambda r: httpx.Response(429)),
        )

        with pytest.raises(RateLimited):
            provider.fetch_daily("AAPL", date(2023, 11, 1), date(2023, 11, 30))

    def test_unknown_symbol(self):
        provider = YahooProvider(
            min_interval_seconds=0,
            client=client_returning(lambda r: httpx.Response(404)),
        )

        with pytest.raises(SymbolNotFound):
            provider.fetch_daily("NOPE", date(2023, 11, 1), date(2023, 11, 30))

    def test_error_inside_a_200_response(self):
        payload = {"chart": {"error": {"code": "Not Found"}, "result": None}}
        provider = YahooProvider(
            min_interval_seconds=0,
            client=client_returning(lambda r: httpx.Response(200, json=payload)),
        )

        with pytest.raises(SymbolNotFound):
            provider.fetch_daily("NOPE", date(2023, 11, 1), date(2023, 11, 30))

    def test_network_failure_is_wrapped(self):
        def explode(request):
            raise httpx.ConnectError("no route to host")

        provider = YahooProvider(min_interval_seconds=0, client=client_returning(explode))

        with pytest.raises(ProviderUnavailable):
            provider.fetch_daily("AAPL", date(2023, 11, 1), date(2023, 11, 30))

    def test_retries_then_gives_up_on_repeated_429(self, monkeypatch):
        monkeypatch.setattr("app.providers.yahoo.time.sleep", lambda _: None)
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            return httpx.Response(429)

        provider = YahooProvider(min_interval_seconds=0, max_retries=2, client=client_returning(handler))

        with pytest.raises(RateLimited):
            provider.fetch_daily("AAPL", date(2023, 11, 1), date(2023, 11, 30))
        assert calls["n"] == 3  # initial attempt + 2 retries


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

        bars = provider.fetch_daily("AAPL", date(2024, 1, 1), date(2024, 1, 3))

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
            provider.fetch_daily("AAPL", date(2024, 1, 1), date(2024, 1, 3))

    def test_unknown_symbol_in_body(self):
        payload = {"status": "error", "code": 404, "message": "symbol not found"}
        provider = TwelveDataProvider(
            api_key="k",
            min_interval_seconds=0,
            client=client_returning(lambda r: httpx.Response(200, json=payload)),
        )

        with pytest.raises(SymbolNotFound):
            provider.fetch_daily("NOPE", date(2024, 1, 1), date(2024, 1, 3))


# --- Test doubles for the chain ---------------------------------------------


class FakeProvider(PriceProvider):
    def __init__(self, name: str, bars: list[Bar] | None = None, error: Exception | None = None,
                 enabled: bool = True) -> None:
        self.name = name
        self._bars = bars or []
        self._error = error
        self._enabled = enabled
        self.calls = 0

    def is_enabled(self) -> bool:
        return self._enabled

    def fetch_daily(self, symbol, start, end):
        self.calls += 1
        if self._error:
            raise self._error
        return self._bars


def a_bar(day: int = 1) -> Bar:
    return Bar(bar_date=date(2024, 1, day), open=1.0, high=1.0, low=1.0, close=1.0, volume=1.0)


class TestProviderChain:
    def test_first_working_provider_wins(self):
        first = FakeProvider("first", bars=[a_bar()])
        second = FakeProvider("second", bars=[a_bar()])

        result = ProviderChain([first, second]).fetch_daily("A", date(2024, 1, 1), date(2024, 1, 2))

        assert result.provider == "first"
        assert second.calls == 0  # the fallback is not called needlessly

    def test_falls_back_when_the_first_is_rate_limited(self):
        first = FakeProvider("first", error=RateLimited("slow down"))
        second = FakeProvider("second", bars=[a_bar()])

        result = ProviderChain([first, second]).fetch_daily("A", date(2024, 1, 1), date(2024, 1, 2))

        assert result.provider == "second"
        assert result.succeeded
        # The failed attempt stays visible: "where did this come from" needs an answer.
        assert result.attempts[0].reason == "rate_limited"

    def test_disabled_providers_are_skipped(self):
        disabled = FakeProvider("disabled", bars=[a_bar()], enabled=False)
        working = FakeProvider("working", bars=[a_bar()])

        result = ProviderChain([disabled, working]).fetch_daily("A", date(2024, 1, 1), date(2024, 1, 2))

        assert result.provider == "working"
        assert disabled.calls == 0

    def test_empty_answer_is_not_success(self):
        """An empty series is not an error, but it is not usable data either."""
        empty = FakeProvider("empty", bars=[])
        working = FakeProvider("working", bars=[a_bar()])

        result = ProviderChain([empty, working]).fetch_daily("A", date(2024, 1, 1), date(2024, 1, 2))

        assert result.provider == "working"

    def test_all_failed_reports_every_attempt(self):
        chain = ProviderChain(
            [FakeProvider("a", error=SymbolNotFound("x")), FakeProvider("b", error=ProviderUnavailable("x"))]
        )

        result = chain.fetch_daily("A", date(2024, 1, 1), date(2024, 1, 2))

        assert not result.succeeded
        assert [a.reason for a in result.attempts] == ["symbol_not_found", "unavailable"]

    def test_rate_limited_only_when_every_attempt_was_throttled(self):
        """"Try again later" must not be reported when the symbol is simply wrong."""
        throttled = ProviderChain(
            [FakeProvider("a", error=RateLimited("x")), FakeProvider("b", error=RateLimited("x"))]
        ).fetch_daily("A", date(2024, 1, 1), date(2024, 1, 2))
        mixed = ProviderChain(
            [FakeProvider("a", error=RateLimited("x")), FakeProvider("b", error=SymbolNotFound("x"))]
        ).fetch_daily("A", date(2024, 1, 1), date(2024, 1, 2))

        assert throttled.rate_limited is True
        assert mixed.rate_limited is False

    def test_unexpected_exception_does_not_kill_the_chain(self):
        """A bug in one provider must not take down a whole refresh."""
        broken = FakeProvider("broken", error=ValueError("boom"))
        working = FakeProvider("working", bars=[a_bar()])

        result = ProviderChain([broken, working]).fetch_daily("A", date(2024, 1, 1), date(2024, 1, 2))

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


@pytest.mark.network
class TestLiveProviders:
    """Excluded by default. Run with: pytest -m network

    These document what was actually measured against the live endpoints, and exist so
    the assumptions can be re-checked when a provider changes.
    """

    def test_yahoo_returns_history(self):
        try:
            bars = YahooProvider().fetch_daily(
                "AAPL", date.today().replace(month=1, day=1), date.today()
            )
        except RateLimited:
            # Being throttled says nothing about whether our parsing is right, so this
            # is inconclusive rather than a failure. Yahoo blocks by IP and the block
            # can outlast an hour; a red test here would only train people to ignore it.
            pytest.skip("Yahoo is rate-limiting this IP — run again from another network")

        assert len(bars) > 100
        assert all(bar.close is not None for bar in bars)
