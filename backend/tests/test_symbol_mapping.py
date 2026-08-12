"""Tests for mapping XTB symbols onto data-provider symbols."""

from __future__ import annotations

import pytest

from app.messages import SymbolReason
from app.models import MappingStatus
from app.symbols import mapping


class TestResolve:
    @pytest.mark.parametrize(
        ("broker_symbol", "expected"),
        [
            ("AAPL.US", "AAPL"),  # US: no suffix at Yahoo
            ("TTE.FR", "TTE.PA"),  # Paris
            ("BMW.DE", "BMW.DE"),  # Xetra: identical suffix
            ("VOD.UK", "VOD.L"),  # London
            ("ASML.NL", "ASML.AS"),  # Amsterdam
            ("ENI.IT", "ENI.MI"),  # Milan
            ("NESN.CH", "NESN.SW"),  # Switzerland
            ("KGH.PL", "KGH.WA"),  # Warsaw
        ],
    )
    def test_suffix_conversion(self, broker_symbol, expected):
        resolution = mapping.resolve(broker_symbol)

        assert resolution.provider_symbol == expected
        assert resolution.status == MappingStatus.RESOLVED
        assert resolution.reason == SymbolReason.SUFFIX_CONVERTED

    def test_lowercase_input_is_normalised(self):
        assert mapping.resolve("aapl.us").provider_symbol == "AAPL"

    def test_override_takes_precedence(self):
        # A real case suffix conversion cannot guess: the root of the symbol differs
        # between XTB and Yahoo.
        resolution = mapping.resolve("ERICB.SE", {"ERICB.SE": "ERIC-B.ST"})

        assert resolution.provider_symbol == "ERIC-B.ST"
        assert resolution.status == MappingStatus.MANUAL
        assert resolution.reason == SymbolReason.MANUAL_OVERRIDE

    def test_currency_hint(self):
        assert mapping.resolve("AAPL.US").currency_hint == "USD"
        assert mapping.resolve("VOD.UK").currency_hint == "GBP"


class TestNonEquities:
    @pytest.mark.parametrize("symbol", ["US500", "DE40", "EURUSD", "GOLD", "OIL.WTI"])
    def test_non_equities_are_unresolved(self, symbol):
        """Indices, FX and commodities have no fundamentals: keep them out."""
        resolution = mapping.resolve(symbol)

        assert resolution.provider_symbol is None
        assert resolution.status == MappingStatus.UNRESOLVED

    def test_unknown_country_suffix_is_unresolved(self):
        resolution = mapping.resolve("XYZ.ZZ")

        assert resolution.provider_symbol is None
        assert resolution.reason == SymbolReason.UNKNOWN_FORMAT

    def test_a_reason_is_always_provided(self):
        """The UI must be able to explain why a symbol cannot be analysed."""
        assert mapping.resolve("US500").reason
        assert mapping.resolve("AAPL.US").reason


class TestCategoryTakesPrecedence:
    """The broker category outranks any naming heuristic."""

    def test_stock_named_like_a_commodity_resolves(self):
        # Barrick Gold: "GOLD" in the symbol must not disqualify it.
        resolution = mapping.resolve("GOLD.US", category="STOCK")

        assert resolution.provider_symbol == "GOLD"
        assert resolution.status == MappingStatus.RESOLVED

    def test_without_category_the_heuristic_still_guards_indices(self):
        assert mapping.resolve("US500").status == MappingStatus.UNRESOLVED

    def test_cfd_never_resolves_even_on_a_valid_ticker(self):
        # IJR is an ETF, but offered as a CFD: no fundamentals apply.
        resolution = mapping.resolve("IJR.US", category="CFD")

        assert resolution.provider_symbol is None
        assert resolution.reason == SymbolReason.DERIVATIVE
        assert resolution.reason_params == {"category": "CFD"}

    def test_etf_resolves(self):
        assert mapping.resolve("IWDA.NL", category="ETF").provider_symbol == "IWDA.AS"

    def test_manual_override_beats_category(self):
        resolution = mapping.resolve("US500", {"US500": "^GSPC"}, category="CFD")

        assert resolution.provider_symbol == "^GSPC"
        assert resolution.status == MappingStatus.MANUAL

    def test_non_ticker_code_is_unresolved_with_an_explanation(self):
        resolution = mapping.resolve("US592CVR0133", category="STOCK")

        assert resolution.provider_symbol is None
        assert resolution.reason == SymbolReason.UNKNOWN_FORMAT


class TestLooksLikeEquity:
    def test_equity(self):
        assert mapping.looks_like_equity("AAPL.US")

    def test_index(self):
        assert not mapping.looks_like_equity("US500")

    def test_no_suffix(self):
        assert not mapping.looks_like_equity("AAPL")
