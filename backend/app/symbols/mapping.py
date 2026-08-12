"""Mapping between XTB broker symbols and data-provider symbols.

XTB suffixes equities by country (``AAPL.US``, ``TTE.FR``) while Yahoo suffixes by
listing venue (``AAPL``, ``TTE.PA``). No official mapping table exists, so we convert
suffixes and keep a table of manual corrections for the rest.

Known limitation: suffix conversion cannot guess differences in the *root* of the
symbol. Real example — XTB's ``ERICB.SE`` corresponds to Yahoo's ``ERIC-B.ST``: the
suffix is right, the root is not. Such cases end up unresolved or silently wrong, and
are fixed through ``SymbolOverride``. A mapping that has never been verified must not
be presented as certain.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.messages import SymbolReason
from app.models import MappingStatus

#: XTB country suffix -> Yahoo listing-venue suffix.
#: An empty value means "no suffix" (US markets).
SUFFIX_MAP: dict[str, str] = {
    "US": "",
    "UK": ".L",
    "DE": ".DE",
    "FR": ".PA",
    "NL": ".AS",
    "BE": ".BR",
    "PT": ".LS",
    "ES": ".MC",
    "IT": ".MI",
    "CH": ".SW",
    "AT": ".VI",
    "IE": ".IR",
    "DK": ".CO",
    "SE": ".ST",
    "NO": ".OL",
    "FI": ".HE",
    "PL": ".WA",
    "CZ": ".PR",
    "HU": ".BD",
    "CA": ".TO",
}

#: XTB suffix -> expected currency. Indicative only.
CURRENCY_HINTS: dict[str, str] = {
    "US": "USD",
    "UK": "GBP",
    "CH": "CHF",
    "DK": "DKK",
    "SE": "SEK",
    "NO": "NOK",
    "PL": "PLN",
    "CZ": "CZK",
    "HU": "HUF",
    "CA": "CAD",
}

#: Fallback used **only** when the broker gives no category. These patterns denote
#: indices, commodities, FX or crypto, which have no fundamentals and must not be
#: scored.
#:
#: This heuristic is deliberately secondary: it produces false positives
#: ("GOLD.US" is Barrick Gold, a perfectly analysable equity). The export's category
#: — STOCK, ETF, CFD — is always preferred when available.
NON_EQUITY_HINTS = ("US500", "US100", "US30", "DE30", "DE40", "FRA40", "EURUSD", "BITCOIN", "NATGAS")

#: Broker categories that can be analysed (prices and fundamentals available).
ANALYSABLE_CATEGORIES = {"STOCK", "ETF"}

#: Categories without fundamentals: derivatives.
DERIVATIVE_CATEGORIES = {"CFD"}


@dataclass(frozen=True)
class SymbolResolution:
    provider_symbol: str | None
    status: str
    country_suffix: str | None
    currency_hint: str | None
    #: Language-neutral reason code, rendered by the client.
    reason: str
    reason_params: dict[str, str]


def looks_like_equity(broker_symbol: str, category: str | None = None) -> bool:
    """Whether the instrument can be tracked through a data provider.

    The broker's ``category`` (STOCK, ETF, CFD) is authoritative when known. The
    symbol heuristic is only a fallback for manual entries, where no category exists.
    """
    symbol = broker_symbol.strip().upper()

    if category:
        normalized = category.strip().upper()
        if normalized in DERIVATIVE_CATEGORIES:
            return False
        if normalized in ANALYSABLE_CATEGORIES:
            # Trust the broker, but the symbol still has to be usable.
            return "." in symbol and symbol.rpartition(".")[2] in SUFFIX_MAP

    if any(hint in symbol for hint in NON_EQUITY_HINTS):
        return False
    if "." not in symbol:
        return False
    return symbol.rpartition(".")[2] in SUFFIX_MAP


def resolve(
    broker_symbol: str,
    overrides: dict[str, str] | None = None,
    category: str | None = None,
) -> SymbolResolution:
    """Work out the provider symbol for a broker symbol.

    ``overrides`` holds manual corrections (``SymbolOverride``) and always wins.
    ``category`` is the one supplied by the broker export.
    """
    symbol = broker_symbol.strip().upper()
    overrides = overrides or {}

    if symbol in overrides:
        return SymbolResolution(
            provider_symbol=overrides[symbol],
            status=MappingStatus.MANUAL,
            country_suffix=None,
            currency_hint=None,
            reason=SymbolReason.MANUAL_OVERRIDE,
            reason_params={},
        )

    if not looks_like_equity(symbol, category):
        normalized = (category or "").strip().upper()
        if normalized in DERIVATIVE_CATEGORIES:
            reason, params = SymbolReason.DERIVATIVE, {"category": normalized}
        elif "." not in symbol or symbol.rpartition(".")[2] not in SUFFIX_MAP:
            reason, params = SymbolReason.UNKNOWN_FORMAT, {}
        else:
            reason, params = SymbolReason.NOT_AN_EQUITY, {}
        return SymbolResolution(
            provider_symbol=None,
            status=MappingStatus.UNRESOLVED,
            country_suffix=None,
            currency_hint=None,
            reason=reason,
            reason_params=params,
        )

    root, _, suffix = symbol.rpartition(".")
    yahoo_suffix = SUFFIX_MAP[suffix]

    return SymbolResolution(
        provider_symbol=f"{root}{yahoo_suffix}",
        status=MappingStatus.RESOLVED,
        country_suffix=suffix,
        currency_hint=CURRENCY_HINTS.get(suffix, "EUR"),
        reason=SymbolReason.SUFFIX_CONVERTED,
        reason_params={"suffix": suffix, "providerSuffix": yahoo_suffix},
    )
