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


def dividend_fact(year: int, start: str, end: str, value: float, form: str = "10-K") -> dict:
    return {"fy": year, "fp": "FY", "form": form, "start": start, "end": end, "val": value}


class TestDividendAggregation:
    """Dividends-per-share don't reliably follow the "one fact per year"
    pattern every other concept does — confirmed live against Bank of
    America's real 10-K filings (DEVLOG "Decision 3u.74"): four separate
    quarterly facts, each individually tagged `fp == "FY"`."""

    def test_quarterly_fragments_are_summed_not_latest_wins(self):
        """The exact shape found live for Bank of America: four same-year
        facts, none spanning more than one quarter. Taking "the latest"
        the way every other concept's tags are merged would silently keep
        only Q4's own $0.28 instead of the real $1.08 annual total."""
        payload = {
            "entityName": "Test",
            "facts": {
                "us-gaap": {
                    "CommonStockDividendsPerShareDeclared": {
                        "units": {
                            "USD/shares": [
                                dividend_fact(2025, "2025-01-01", "2025-03-31", 0.26),
                                dividend_fact(2025, "2025-04-01", "2025-06-30", 0.26),
                                dividend_fact(2025, "2025-07-01", "2025-09-30", 0.28),
                                dividend_fact(2025, "2025-10-01", "2025-12-31", 0.28),
                            ]
                        }
                    }
                }
            },
        }
        from app.providers.edgar import _normalise

        fundamentals = _normalise(payload, "1")

        assert fundamentals.latest("dividend_per_share").value == pytest.approx(1.08)

    def test_a_genuine_single_annual_fact_is_used_as_is(self):
        """The common case (confirmed live for IBM, Albemarle, Oracle...):
        one fact per year already spanning the whole year — must not be
        altered by the new sum-fragments logic."""
        payload = {
            "entityName": "Test",
            "facts": {
                "us-gaap": {
                    "CommonStockDividendsPerShareDeclared": {
                        "units": {"USD/shares": [dividend_fact(2025, "2025-01-01", "2025-12-31", 1.62)]}
                    }
                }
            },
        }
        from app.providers.edgar import _normalise

        assert _normalise(payload, "1").latest("dividend_per_share").value == pytest.approx(1.62)

    def test_a_later_filing_restating_the_same_quarter_is_deduped_not_double_counted(self):
        """A 10-K/A amendment re-reports the same Q1 with a corrected
        value — same (start, end), must replace, not add to, the original."""
        payload = {
            "entityName": "Test",
            "facts": {
                "us-gaap": {
                    "CommonStockDividendsPerShareDeclared": {
                        "units": {
                            "USD/shares": [
                                dividend_fact(2025, "2025-01-01", "2025-03-31", 0.20),
                                dividend_fact(2025, "2025-04-01", "2025-06-30", 0.20),
                                # Restatement of Q1, same period, corrected value.
                                dividend_fact(2025, "2025-01-01", "2025-03-31", 0.22, form="10-K/A"),
                            ]
                        }
                    }
                }
            },
        }
        from app.providers.edgar import _normalise

        assert _normalise(payload, "1").latest("dividend_per_share").value == pytest.approx(0.42)

    def test_a_non_payer_with_no_dividend_tag_at_all_is_missing_not_zero(self):
        payload = {"entityName": "Test", "facts": {"us-gaap": {}}}
        from app.providers.edgar import _normalise

        fundamentals = _normalise(payload, "1")

        assert "dividend_per_share" not in fundamentals.concepts
        assert "dividend_per_share" in fundamentals.missing


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


class TestNameLookup:
    """Searching 10,000 names needs a stricter rule than verifying one candidate.

    `names_match` accepts a single shared token, which is right once a ticker has
    narrowed the field to one company and useless across the whole index: "Air Liquide"
    would collect Air Products, Air Brake Technologies and Madison Air Solutions.
    """

    INDEX = {
        "0": {"cik_str": 2969, "ticker": "APD", "title": "Air Products & Chemicals, Inc."},
        "1": {"cik_str": 943452, "ticker": "WAB", "title": "WESTINGHOUSE AIR BRAKE TECHNOLOGIES CO"},
        "2": {"cik_str": 1161167, "ticker": "AIQUY", "title": "L AIR LIQUIDE SA /FI"},
        "3": {"cik_str": 1121404, "ticker": "SNY", "title": "Sanofi"},
        "4": {"cik_str": 1121404, "ticker": "SNYNF", "title": "Sanofi"},
        "5": {"cik_str": 1038143, "ticker": "FNCTF", "title": "ORANGE"},
        "6": {"cik_str": 1754226, "ticker": "OBT", "title": "Orange County Bancorp, Inc. /DE/"},
    }

    def test_every_significant_word_must_be_present(self):
        from app.providers.edgar import find_by_name

        found = find_by_name(self.INDEX, "Air Liquide")

        # Not Air Products, whose only overlap is the word "Air".
        assert found is not None
        assert found[0] == "0001161167"

    def test_an_exact_name_beats_a_longer_one_containing_it(self):
        """"Orange" must not become Orange County Bancorp."""
        from app.providers.edgar import find_by_name

        found = find_by_name(self.INDEX, "Orange")

        assert found == ("0001038143", "ORANGE")

    def test_several_tickers_for_one_company_are_not_ambiguity(self):
        """Ordinary shares and an ADR share a CIK; that is one company, not two."""
        from app.providers.edgar import find_by_name

        assert find_by_name(self.INDEX, "Sanofi")[0] == "0001121404"

    def test_an_unknown_company_returns_nothing(self):
        from app.providers.edgar import find_by_name

        assert find_by_name(self.INDEX, "LVMH") is None

    def test_ambiguity_is_refused_rather_than_guessed(self):
        """Two different companies matching equally well is not an answer.

        Returning nothing costs one data point; guessing attaches another company's
        accounts to a holding.
        """
        from app.providers.edgar import find_by_name

        index = {
            "0": {"cik_str": 1, "ticker": "AAA", "title": "Acme Corp"},
            "1": {"cik_str": 2, "ticker": "BBB", "title": "Acme Corp"},
        }

        assert find_by_name(index, "Acme") is None

    def test_name_lookup_rescues_a_ticker_that_belongs_to_someone_else(self):
        """ORA.FR is Orange; ORA in the US is Ormat. The name still finds the filer."""
        provider = EdgarProvider(
            user_agent="test contact@example.com",
            min_interval_seconds=0,
            client=client_returning(lambda r: httpx.Response(200, json={
                **self.INDEX,
                "9": {"cik_str": 1296445, "ticker": "ORA", "title": "ORMAT TECHNOLOGIES, INC."},
            })),
        )

        cik, registrant = provider.resolve("ORA", expected_name="Orange")

        assert cik == "0001038143"
        assert registrant == "ORANGE"
