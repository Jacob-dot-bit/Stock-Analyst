"""Correspondance entre les symboles XTB et ceux des fournisseurs de données.

XTB suffixe ses actions par pays (``AAPL.US``, ``TTE.FR``, ``BMW.DE``) alors que
Yahoo suffixe par place de cotation (``AAPL``, ``TTE.PA``, ``BMW.DE``). Il n'existe
aucune table de correspondance officielle : on applique donc une conversion de
suffixes, complétée par des corrections manuelles stockées en base.

Limite assumée : la conversion de suffixe ne peut pas deviner les différences de
*racine* du symbole. Exemple réel : ``ERICB.SE`` chez XTB correspond à ``ERIC-B.ST``
chez Yahoo — le suffixe est bon, la racine non. Ces cas sortent en ``UNRESOLVED``
ou en correspondance fausse, et se corrigent via ``SymbolOverride``. Une
correspondance jamais vérifiée ne doit pas être présentée comme certaine.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models import MappingStatus

#: Suffixe pays XTB -> suffixe place de cotation Yahoo.
#: Une valeur vide signifie « aucun suffixe » (marchés américains).
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

#: Suffixe XTB -> devise attendue, utilisé comme indication seulement.
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

#: Repli utilisé **uniquement** quand le courtier ne fournit pas de catégorie.
#: Ces motifs désignent des indices, matières premières, FX ou cryptos, qui n'ont
#: pas de fondamentaux et ne doivent pas recevoir de score.
#:
#: Cette heuristique est volontairement secondaire : elle produit des faux positifs
#: (« GOLD.US » est Barrick Gold, une action parfaitement analysable). La catégorie
#: de l'export — STOCK, ETF, CFD — est toujours préférée quand elle est disponible.
NON_EQUITY_HINTS = ("US500", "US100", "US30", "DE30", "DE40", "FRA40", "EURUSD", "BITCOIN", "NATGAS")

#: Catégories courtier analysables (fondamentaux et cours disponibles).
ANALYSABLE_CATEGORIES = {"STOCK", "ETF"}

#: Catégories sans fondamentaux : produits dérivés.
DERIVATIVE_CATEGORIES = {"CFD"}


@dataclass(frozen=True)
class SymbolResolution:
    provider_symbol: str | None
    status: str
    country_suffix: str | None
    currency_hint: str | None
    reason: str


def looks_like_equity(broker_symbol: str, category: str | None = None) -> bool:
    """Indique si l'instrument peut être suivi chez un fournisseur de données.

    La ``category`` de l'export courtier (STOCK, ETF, CFD) fait autorité quand elle
    est connue. L'heuristique sur le symbole n'est qu'un repli pour les saisies
    manuelles, où aucune catégorie n'est disponible.
    """
    symbol = broker_symbol.strip().upper()

    if category:
        normalized = category.strip().upper()
        if normalized in DERIVATIVE_CATEGORIES:
            return False
        if normalized in ANALYSABLE_CATEGORIES:
            # On fait confiance au courtier, mais le symbole doit rester exploitable.
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
    """Détermine le symbole fournisseur correspondant à un symbole courtier.

    ``overrides`` est la table des corrections manuelles (``SymbolOverride``), qui
    prime toujours. ``category`` est celle fournie par l'export courtier.
    """
    symbol = broker_symbol.strip().upper()
    overrides = overrides or {}

    if symbol in overrides:
        return SymbolResolution(
            provider_symbol=overrides[symbol],
            status=MappingStatus.MANUAL,
            country_suffix=None,
            currency_hint=None,
            reason="Correspondance définie manuellement.",
        )

    if not looks_like_equity(symbol, category):
        normalized = (category or "").strip().upper()
        if normalized in DERIVATIVE_CATEGORIES:
            reason = (
                f"Produit dérivé ({normalized}) : pas de données fondamentales. "
                "L'analyse ne s'y applique pas."
            )
        elif "." not in symbol or symbol.rpartition(".")[2] not in SUFFIX_MAP:
            reason = (
                "Symbole hors du format « RACINE.PAYS » attendu, ou place de cotation "
                "inconnue. Indiquez le symbole fournisseur à la main si le titre est suivi."
            )
        else:
            reason = (
                "Instrument non reconnu comme une action (indice, matière première, "
                "FX ou crypto). L'analyse fondamentale ne s'y applique pas."
            )
        return SymbolResolution(
            provider_symbol=None,
            status=MappingStatus.UNRESOLVED,
            country_suffix=None,
            currency_hint=None,
            reason=reason,
        )

    root, _, suffix = symbol.rpartition(".")
    yahoo_suffix = SUFFIX_MAP[suffix]

    return SymbolResolution(
        provider_symbol=f"{root}{yahoo_suffix}",
        status=MappingStatus.RESOLVED,
        country_suffix=suffix,
        currency_hint=CURRENCY_HINTS.get(suffix, "EUR"),
        reason=f"Conversion automatique du suffixe .{suffix} vers « {yahoo_suffix or 'aucun'} ».",
    )
