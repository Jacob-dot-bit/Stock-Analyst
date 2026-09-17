"""Company fundamentals from SEC EDGAR — filed figures, not vendor estimates.

This is the highest-quality source in the project: the numbers come from the companies'
own regulatory filings, not from a data vendor's reconstruction. It is free, needs no
key, and has no meaningful quota. Its one limit is jurisdictional — **US filers only**,
which here covers 23 of 38 holdings.

The SEC requires a named ``User-Agent`` with a contact address and asks for at most 10
requests/second. Without the header the API returns 403, which is why this provider
disables itself rather than failing when ``SEC_USER_AGENT`` is unset.

## The hard part: one concept, many tags

US GAAP lets a company tag revenue as ``Revenues``,
``RevenueFromContractWithCustomerExcludingAssessedTax``, ``SalesRevenueNet`` and more,
and the choice varies by filer and by year. Picking one tag and hoping is how a
fundamentals pipeline silently reports "no revenue" for a profitable company.

So each concept has an ordered list of candidate tags, and figures are merged **per
fiscal year**, the higher-priority tag winning for that year. Taking the first tag that
has any data at all is not enough: NVIDIA reports revenue under the contract-revenue tag
through FY2022 and switches afterwards, so a whole-series choice yields a company whose
latest revenue is four years older than its latest profit.

The tag actually used is recorded alongside every value. When a figure looks wrong, the
first question is which tag produced it, and that has to have an answer.

Coverage note: ``10-K`` (US filers) and ``20-F`` (foreign private issuers) are both
accepted, along with their amended ``/A`` variants. Dropping 20-F would exclude ASML,
TotalEnergies and every other European company listed in the US, whose figures are just
as official.

Two consequences of accepting foreign filers, both learned the hard way:

* **They do not all report in USD.** ASML files in EUR. Reading only the USD unit
  returned nothing for it. Every figure therefore carries its own currency, because a
  ratio built from EUR fundamentals and a USD share price is wrong in a way no test
  catches.
* **They do not all use US GAAP.** TotalEnergies files under IFRS, where revenue is
  ``Revenue`` and profit is ``ProfitLoss``. Both taxonomies are searched.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import httpx

from app.providers.base import ProviderUnavailable, RateLimited, SymbolNotFound, Throttle

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

#: Ordered candidates per concept. First tag present in the filing wins.
#: Order matters: the more specific, post-2018 revenue tag comes before the legacy
#: catch-all, because filers that use both mean different things by them.
CONCEPT_TAGS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
    ),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "operating_income": ("OperatingIncomeLoss",),
    "gross_profit": ("GrossProfit",),
    "assets": ("Assets",),
    "liabilities": ("Liabilities",),
    "equity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    "cash": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ),
    # `ConvertibleLongTermNotesPayable`/`ConvertibleDebtNoncurrent` added after
    # live verification (Decision 3t.1 follow-up): Datadog and Okta finance
    # via convertible notes rather than conventional long-term debt, so
    # neither of the first two tags ever matches for them — genuinely
    # untagged otherwise, not a scoring gap that can be closed by more tags
    # (confirmed live: IONQ, DouYu and Honest Company simply carry no
    # long-term debt at all).
    "debt_long_term": (
        "LongTermDebtNoncurrent",
        "LongTermDebt",
        "ConvertibleLongTermNotesPayable",
        "ConvertibleDebtNoncurrent",
    ),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "capex": (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ),
    "shares_diluted": ("WeightedAverageNumberOfDilutedSharesOutstanding",),
    #: Annual dividends declared per share — a duration fact filed once per
    #: fiscal year (`fp == "FY"`), same shape as `shares_diluted`, so the
    #: existing `_extract` filter needs no new aggregation logic. Powers
    #: Discovery's `dividend_yield_estimate`, deliberately separate from the
    #: scored `dividend_yield` metric (which replays this account's own lot
    #: history for held stocks) — see DEVLOG "Decision 3u.73".
    "dividend_per_share": (
        "CommonStockDividendsPerShareDeclared",
        "CommonStockDividendsPerShareCashPaid",
    ),
}

#: IFRS equivalents, used by foreign private issuers such as TotalEnergies.
IFRS_CONCEPT_TAGS: dict[str, tuple[str, ...]] = {
    "revenue": ("Revenue", "RevenueFromContractsWithCustomers"),
    "net_income": ("ProfitLoss", "ProfitLossAttributableToOwnersOfParent"),
    "operating_income": ("ProfitLossFromOperatingActivities",),
    "gross_profit": ("GrossProfit",),
    "assets": ("Assets",),
    "liabilities": ("Liabilities",),
    "equity": ("Equity", "EquityAttributableToOwnersOfParent"),
    "cash": ("CashAndCashEquivalents",),
    # `LongtermBorrowings` added after live ESEF verification (Decision 3t.1):
    # Air Liquide, Dassault Systèmes and Air France KLM all tag debt under
    # this name rather than either of the first two — a fallback, not a
    # replacement, so a filer already matching on the first two is unaffected.
    "debt_long_term": ("NoncurrentPortionOfNoncurrentBorrowings", "NoncurrentBorrowings", "LongtermBorrowings"),
    "operating_cash_flow": ("CashFlowsFromUsedInOperatingActivities",),
    "capex": ("PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",),
    # `NumberOfSharesOutstanding` is a point-in-time count, not the diluted
    # weighted average `WeightedAverageShares` is — a lower-priority fallback
    # for filers (confirmed live: Air France KLM) that don't tag the latter at
    # all. `AnnualFigure.tag` still records which one actually produced a
    # given value, so this substitution is never silent.
    "shares_diluted": ("WeightedAverageShares", "NumberOfSharesOutstanding"),
    "dividend_per_share": ("DividendsPaidPerShare",),
}


@dataclass
class AnnualFigure:
    fiscal_year: int
    period_end: date
    value: float
    #: Which XBRL tag produced this number. Kept so a surprising figure can be traced.
    tag: str
    #: Reporting currency. Never assumed: ASML files in EUR, and a ratio mixing that
    #: with a USD price would be silently wrong.
    currency: str


@dataclass
class Fundamentals:
    cik: str
    company_name: str
    #: concept -> figures, oldest first
    concepts: dict[str, list[AnnualFigure]] = field(default_factory=dict)
    #: Concepts the filer simply does not report. Surfaced rather than silently zero.
    missing: list[str] = field(default_factory=list)

    def latest(self, concept: str) -> AnnualFigure | None:
        figures = self.concepts.get(concept)
        return figures[-1] if figures else None


class EdgarProvider:
    name = "edgar"

    def __init__(
        self,
        user_agent: str | None,
        # The SEC asks for 10 req/s at most. 0.5s is far under that and costs nothing,
        # since fundamentals are fetched once per company per quarter at most.
        min_interval_seconds: float = 0.5,
        timeout_seconds: float = 45.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._user_agent = user_agent
        self._throttle = Throttle(min_interval_seconds)
        self._timeout = timeout_seconds
        self._client = client
        self._ticker_index: dict[str, dict[str, Any]] | None = None

    def is_enabled(self) -> bool:
        # The SEC returns 403 to anonymous callers, so a missing contact header means
        # this provider cannot work at all — better disabled than failing per request.
        return bool(self._user_agent)

    def _headers(self) -> dict[str, str]:
        return {"User-Agent": self._user_agent or "", "Accept": "application/json"}

    def _get(self, url: str) -> Any:
        client = self._client or httpx.Client(timeout=self._timeout)
        owns_client = self._client is None
        try:
            self._throttle.wait()
            try:
                response = client.get(url, headers=self._headers())
            except httpx.HTTPError as exc:
                raise ProviderUnavailable(str(exc)) from exc

            if response.status_code == 429:
                raise RateLimited("SEC EDGAR is throttling requests")
            if response.status_code == 403:
                raise ProviderUnavailable(
                    "SEC EDGAR refused the request; SEC_USER_AGENT must name a contact address"
                )
            if response.status_code == 404:
                raise SymbolNotFound(url)
            if response.status_code >= 400:
                raise ProviderUnavailable(f"HTTP {response.status_code}")

            try:
                return response.json()
            except ValueError as exc:
                raise ProviderUnavailable("malformed JSON response") from exc
        finally:
            if owns_client:
                client.close()

    def _load_index(self) -> dict[str, dict[str, Any]]:
        if self._ticker_index is None:
            payload = self._get(TICKERS_URL)
            self._ticker_index = {
                str(entry["ticker"]).upper(): entry
                for entry in payload.values()
                if isinstance(entry, dict) and entry.get("ticker")
            }
        return self._ticker_index

    def resolve(self, ticker: str, expected_name: str | None = None) -> tuple[str, str]:
        """Map a ticker to (CIK, registrant name), refusing unconfirmed matches.

        ``expected_name`` is the company name the broker reported. When given, the
        registrant found at that ticker must plausibly be the same company or the
        match is rejected.

        This guard is not theoretical. The SEC index is keyed on *US* tickers, so a
        bare-root lookup maps ``AI.FR`` (Air Liquide) onto C3.ai, ``ORA.FR`` (Orange)
        onto Ormat Technologies and ``SAN.FR`` (Sanofi) onto Banco Santander. Each
        would have produced a full set of plausible-looking fundamentals belonging to
        a different company — the worst failure this project can have.

        Callers should pass it for **non-US** instruments only. For a US listing the
        broker ticker and the SEC ticker are the same namespace, so the lookup is exact
        by construction, and demanding a name match there rejects valid results:
        the broker writes "AMD" where the registrant is "Advanced Micro Devices Inc".
        """
        index = self._load_index()
        entry = index.get(ticker.strip().upper())

        if entry is not None:
            registrant = str(entry.get("title") or "")
            if not expected_name or names_match(expected_name, registrant):
                return str(entry["cik_str"]).zfill(10), registrant

        # The ticker is absent or belongs to someone else. A European company may still
        # file with the SEC under an ADR ticker we cannot guess, so look it up by name —
        # which cannot collide, since the name is what we are matching on.
        if expected_name:
            found = find_by_name(index, expected_name)
            if found:
                return found

        if entry is not None:
            raise SymbolNotFound(
                f"{ticker} resolves to '{entry.get('title')}', which does not match "
                f"'{expected_name}' — refusing to use another company's filings"
            )
        raise SymbolNotFound(f"{ticker} is not in the SEC ticker index")

    def fetch(self, ticker: str, expected_name: str | None = None) -> Fundamentals:
        """Fetch and normalise one company's annual figures."""
        if not self.is_enabled():
            raise ProviderUnavailable("SEC_USER_AGENT is not configured")

        cik, _ = self.resolve(ticker, expected_name)
        payload = self._get(FACTS_URL.format(cik=cik))
        return _normalise(payload, cik)


#: Words that carry no identifying information when comparing company names.
_NAME_NOISE = {
    "the", "inc", "incorporated", "corp", "corporation", "company", "co", "plc",
    "sa", "se", "nv", "ag", "ltd", "limited", "holding", "holdings", "group",
    "sas", "spa", "as", "ab", "oyj", "class", "adr", "common", "stock", "shares",
}


def _name_tokens(name: str) -> set[str]:
    text = unicodedata.normalize("NFKD", name.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    words = re.split(r"[^a-z0-9]+", text)
    return {w for w in words if w and w not in _NAME_NOISE and len(w) > 1}


def names_match(expected: str, registrant: str) -> bool:
    """Whether two company names plausibly denote the same company.

    Deliberately permissive on formatting and strict on substance: "TotalEnergies"
    and "TotalEnergies SE" match, "Air Liquide" and "C3.ai, Inc." do not. Legal-form
    words are stripped because they identify nothing.
    """
    left, right = _name_tokens(expected), _name_tokens(registrant)
    if not left or not right:
        return False
    if left & right:
        return True
    # One name written solid, the other spaced: "TotalEnergies" vs "Total Energies".
    return "".join(sorted(left)) == "".join(sorted(right)) or (
        "".join(left) in "".join(right) or "".join(right) in "".join(left)
    )


def find_by_name(index: dict[str, dict[str, Any]], expected: str) -> tuple[str, str] | None:
    """Find a registrant by company name, or nothing when the answer is not certain.

    Searching 10,000 names needs a far stricter rule than verifying one candidate.
    ``names_match`` accepts a single shared token, which is right when the ticker has
    already narrowed the field to one company — and useless here, where "Air Liquide"
    would collect Air Products, Air Brake Technologies and Madison Air Solutions.

    So: an exact name match wins; failing that, a single registrant containing every
    significant word of the expected name is accepted; anything ambiguous is refused.
    Returning nothing costs one missing data point, whereas guessing attaches another
    company's accounts to a holding.
    """
    wanted = _name_tokens(expected)
    if not wanted:
        return None

    exact, contains = [], []
    for entry in index.values():
        title = str(entry.get("title") or "")
        tokens = _name_tokens(title)
        if not tokens:
            continue
        if tokens == wanted:
            exact.append(entry)
        elif wanted <= tokens:
            contains.append(entry)

    for candidates in (exact, contains):
        ciks = {str(c["cik_str"]).zfill(10) for c in candidates}
        # Several tickers for one company (ordinary shares plus ADR) is not ambiguity.
        if len(ciks) == 1:
            best = candidates[0]
            return str(best["cik_str"]).zfill(10), str(best.get("title") or "")

    return None


def _normalise(payload: dict, cik: str) -> Fundamentals:
    facts = payload.get("facts") or {}
    gaap = facts.get("us-gaap") or {}
    ifrs = facts.get("ifrs-full") or {}
    result = Fundamentals(cik=cik, company_name=str(payload.get("entityName") or ""))

    for concept in CONCEPT_TAGS:
        # US GAAP first: when a filer publishes both, that is the primary taxonomy.
        figures = _extract(gaap, CONCEPT_TAGS[concept])
        if not figures:
            figures = _extract(ifrs, IFRS_CONCEPT_TAGS.get(concept, ()))

        if figures:
            result.concepts[concept] = figures
        else:
            result.missing.append(concept)

    return result


#: Annual report forms, amendments included. 20-F is how foreign private issuers file,
#: and excluding it would drop every European company listed in the US.
ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A"}

#: Units that are share counts rather than money.
NON_MONETARY_UNITS = {"shares", "pure"}


def _extract(gaap: dict, tags: tuple[str, ...]) -> list[AnnualFigure]:
    """Merge annual figures across candidate tags, per fiscal year.

    Filers switch tags mid-history, so a year is taken from the highest-priority tag
    that reports it rather than committing the whole series to one tag.
    """
    by_year: dict[int, AnnualFigure] = {}
    priority = {tag: rank for rank, tag in enumerate(tags)}

    for tag in tags:
        units = (gaap.get(tag) or {}).get("units") or {}
        # Take whichever unit the filer used rather than assuming USD: ASML reports in
        # EUR, and only looking for USD returned nothing at all for it.
        unit = next((u for u in units if u not in NON_MONETARY_UNITS), None)
        if unit is None:
            unit = next(iter(units), None)
        if unit is None:
            continue
        entries = units[unit]

        for entry in entries:
            if entry.get("form") not in ANNUAL_FORMS or entry.get("fp") != "FY":
                continue
            fiscal_year, end = entry.get("fy"), entry.get("end")
            value = entry.get("val")
            if fiscal_year is None or end is None or value is None:
                continue
            try:
                period_end = datetime.strptime(str(end)[:10], "%Y-%m-%d").date()
            except ValueError:
                continue

            year = int(fiscal_year)
            existing = by_year.get(year)
            figure = AnnualFigure(year, period_end, float(value), tag, unit)
            existing = by_year.get(year)
            if existing is None:
                by_year[year] = figure
                continue

            # Same year from two tags: the preferred tag wins. Same tag twice: the
            # later period end wins, because a year is restated in later filings.
            if priority[tag] < priority[existing.tag]:
                by_year[year] = figure
            elif priority[tag] == priority[existing.tag] and period_end > existing.period_end:
                by_year[year] = figure

    return [by_year[year] for year in sorted(by_year)]
