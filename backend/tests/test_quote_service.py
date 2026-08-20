"""Tests for the live-quote round. See DEVLOG "Decision 3n.1" for why it now
processes several instruments concurrently, the same shape as the daily
price-history refresh in `prices/service.py`."""

from __future__ import annotations

from datetime import date

from app.models import Instrument, MappingStatus
from app.prices.quote_service import fetch_live_quotes
from app.providers.base import Bar, ProviderChain
from tests.test_providers import FakeProvider


def a_bar() -> Bar:
    return Bar(bar_date=date(2026, 1, 1), open=1, high=1, low=1, close=42.0, volume=1)


def make_instrument(symbol: str, provider_symbol: str, instrument_id: int) -> Instrument:
    instrument = Instrument(
        broker_symbol=symbol, provider_symbol=provider_symbol, mapping_status=MappingStatus.RESOLVED
    )
    instrument.id = instrument_id
    return instrument


class TestFetchLiveQuotes:
    def test_many_instruments_are_quoted_correctly_when_run_concurrently(self):
        count = 12
        instruments = [make_instrument(f"C{i}.US", f"C{i}", i + 1) for i in range(count)]
        provider = FakeProvider("yahoo", bars=[a_bar()])
        chain = ProviderChain([provider])

        results = fetch_live_quotes(instruments, chain, budget_seconds=30)

        assert len(results) == count
        assert all(price == 42.0 for price, _ in results.values())
        assert {instrument.id for instrument in instruments} == set(results.keys())
        # No dropped or duplicated calls despite running through the same
        # shared FakeProvider from several worker threads at once.
        assert provider.calls == count

    def test_on_attempt_fires_once_per_instrument(self):
        instruments = [make_instrument(f"D{i}.US", f"D{i}", i + 1) for i in range(6)]
        provider = FakeProvider("yahoo", bars=[a_bar()])
        chain = ProviderChain([provider])
        seen: list[str] = []

        fetch_live_quotes(instruments, chain, budget_seconds=30, on_attempt=seen.append)

        assert seen.count("yahoo") == len(instruments)
