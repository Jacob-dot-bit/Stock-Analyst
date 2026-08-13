"""Tests for SEC EDGAR fundamentals.

Two of these cover mistakes that were live in this code and produced real wrong data,
which is why they assert on specific companies rather than on abstractions.
"""

from __future__ import annotations

import httpx
import pytest

from app.providers.base import ProviderUnavailable, SymbolNotFound
from app.providers.edgar import EdgarProvider, names_match


def client_returning(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


TICKERS = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 1045810, "ticker": "AI", "title": "C3.ai, Inc."},
    "2": {"cik_str": 2488, "ticker": "AMD", "title": "ADVANCED MICRO DEVICES INC"},
    "3": {"cik_str": 937966, "ticker": "ASML", "title": "ASML HOLDING NV"},
}


def annual(year: int, end: str, value: float, form: str = "10-K") -> dict:
    return {"fy": year, "fp": "FY", "form": form, "end": end, "val": value}


class TestNameVerification:
    """A bare-root lookup maps European tickers onto unrelated US companies.

    Each of these was produced by the code before the guard existed, and each would
    have shown one company's fundamentals under another's name.
    """

    @pytest.mark.parametrize(
        ("broker_name", "registrant"),
        [
            ("Air Liquide", "C3.ai, Inc."),
            ("Orange", "ORMAT TECHNOLOGIES, INC."),
            ("Sanofi", "Banco Santander, S.A."),
            ("Dassault Systemes", "BIG TREE CLOUD HOLDINGS LIMITED"),
            ("LVMH", "Moelis & Company"),
            ("CAC 40", "CAMDEN NATIONAL CORP"),
        ],
    )
    def test_unrelated_companies_are_rejected(self, broker_name, registrant):
        assert names_match(broker_name, registrant) is False

    @pytest.mark.parametrize(
        ("broker_name", "registrant"),
        [
            ("TotalEnergies", "TotalEnergies SE"),
            ("ASML", "ASML HOLDING NV"),
            ("Apple", "Apple Inc."),
            ("ArcelorMittal", "ArcelorMittal"),
            ("Novo Nordisk", "NOVO NORDISK A/S"),
        ],
    )
    def test_the_same_company_is_accepted(self, broker_name, registrant):
        assert names_match(broker_name, registrant) is True

    def test_legal_form_alone_is_not_a_match(self):
        """Two unrelated "Inc"s share only a suffix, which identifies nothing."""
        assert names_match("Foo Inc", "Bar Inc") is False

    def test_resolution_refuses_a_mismatched_registrant(self):
        provider = EdgarProvider(
            user_agent="test contact@example.com",
            min_interval_seconds=0,
            client=client_returning(lambda r: httpx.Response(200, json=TICKERS)),
        )

        with pytest.raises(SymbolNotFound, match="does not match"):
            provider.resolve("AI", expected_name="Air Liquide")

    def test_without_an_expected_name_the_ticker_is_trusted(self):
        """For a US listing the two namespaces are the same, so the lookup is exact.

        Requiring a name match there rejects valid results: the broker writes "AMD"
        where the registrant is "Advanced Micro Devices Inc".
        """
        provider = EdgarProvider(
            user_agent="test contact@example.com",
            min_interval_seconds=0,
            client=client_returning(lambda r: httpx.Response(200, json=TICKERS)),
        )

        cik, registrant = provider.resolve("AMD")

        assert cik == "0000002488"
        assert registrant == "ADVANCED MICRO DEVICES INC"


class TestTagMerging:
    """Filers switch XBRL tags mid-history."""

    def test_years_are_merged_across_tags(self):
        """NVIDIA reports revenue under one tag through FY2022 and another after.

        Choosing a single tag for the whole series yielded a company whose latest
        revenue was four years older than its latest profit.
        """
        payload = {
            "entityName": "Test",
            "facts": {
                "us-gaap": {
                    "RevenueFromContractWithCustomerExcludingAssessedTax": {
                        "units": {"USD": [annual(2021, "2021-12-31", 100), annual(2022, "2022-12-31", 200)]}
                    },
                    "Revenues": {
                        "units": {"USD": [annual(2023, "2023-12-31", 300), annual(2024, "2024-12-31", 400)]}
                    },
                }
            },
        }
        from app.providers.edgar import _normalise

        fundamentals = _normalise(payload, "0000000001")
        years = [f.fiscal_year for f in fundamentals.concepts["revenue"]]

        assert years == [2021, 2022, 2023, 2024]
        assert fundamentals.latest("revenue").value == 400

    def test_the_preferred_tag_wins_for_a_shared_year(self):
        payload = {
            "entityName": "Test",
            "facts": {
                "us-gaap": {
                    "RevenueFromContractWithCustomerExcludingAssessedTax": {
                        "units": {"USD": [annual(2024, "2024-12-31", 111)]}
                    },
                    "Revenues": {"units": {"USD": [annual(2024, "2024-12-31", 999)]}},
                }
            },
        }
        from app.providers.edgar import _normalise

        assert _normalise(payload, "1").latest("revenue").value == 111


class TestForeignFilers:
    def test_ifrs_taxonomy_is_read(self):
        """TotalEnergies files under IFRS, where revenue is "Revenue"."""
        payload = {
            "entityName": "TotalEnergies SE",
            "facts": {"ifrs-full": {"Revenue": {"units": {"USD": [annual(2025, "2025-12-31", 201_196_000_000, "20-F")]}}}},
        }
        from app.providers.edgar import _normalise

        assert _normalise(payload, "1").latest("revenue").value == 201_196_000_000

    def test_a_non_usd_reporting_currency_is_kept(self):
        """ASML files in EUR. Reading only USD returned nothing at all for it, and a
        ratio mixing EUR fundamentals with a USD price is wrong in a way no test sees."""
        payload = {
            "entityName": "ASML HOLDING NV",
            "facts": {"us-gaap": {"Revenues": {"units": {"EUR": [annual(2025, "2025-12-31", 32_667_300_000, "20-F")]}}}},
        }
        from app.providers.edgar import _normalise

        figure = _normalise(payload, "1").latest("revenue")
        assert figure.value == 32_667_300_000
        assert figure.currency == "EUR"

    def test_amended_annual_reports_count(self):
        payload = {
            "entityName": "Test",
            "facts": {"us-gaap": {"Revenues": {"units": {"USD": [annual(2025, "2025-12-31", 50, "20-F/A")]}}}},
        }
        from app.providers.edgar import _normalise

        assert _normalise(payload, "1").latest("revenue").value == 50

    def test_quarterly_filings_are_ignored(self):
        payload = {
            "entityName": "Test",
            "facts": {"us-gaap": {"Revenues": {"units": {"USD": [annual(2025, "2025-03-31", 10, "10-Q")]}}}},
        }
        from app.providers.edgar import _normalise

        assert "revenue" in _normalise(payload, "1").missing


class TestConfiguration:
    def test_disabled_without_a_contact_user_agent(self):
        """The SEC answers 403 to anonymous callers, so this cannot work without it."""
        assert EdgarProvider(user_agent=None).is_enabled() is False
        assert EdgarProvider(user_agent="Name contact@example.com").is_enabled() is True

    def test_403_explains_what_is_missing(self):
        provider = EdgarProvider(
            user_agent="bad", min_interval_seconds=0,
            client=client_returning(lambda r: httpx.Response(403)),
        )

        with pytest.raises(ProviderUnavailable, match="SEC_USER_AGENT"):
            provider.resolve("AAPL")
