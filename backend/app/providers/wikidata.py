"""Sector/industry classification for instruments FMP's free tier can't reach.

FMP's `/profile` endpoint (`providers/fmp.py`) is US-only on the free tier —
confirmed live (HTTP 402 on any European symbol). Wikidata fills the gap:
free, keyless, and it carries the data for most large, well-known companies.

Wikidata's own vocabulary (`industry`, P452) is far more granular and
inconsistent than FMP's GICS-style sectors ("Technology", "Healthcare"...),
so a result is only used after passing through `INDUSTRY_TO_SECTOR` — an
unmapped industry is dropped rather than shown as a foreign-vocabulary label
sitting next to FMP-sourced ones in the same breakdown chart.

Entity resolution: search by company name, then keep the best-ranked
candidate that lists a stock exchange (P414) — the strongest available
signal that this is the publicly traded parent, not a subsidiary sharing the
name (a Czech or Austrian branch office, both seen live) or an unrelated
same-named entity (a cycling team turned up for "TotalEnergies", a Wikinews
article for "Air France-KLM"). Verified live against every European holding
in a real portfolio before relying on it — see DEVLOG "Decision 3c.1".
"""

from __future__ import annotations

import httpx

SEARCH_URL = "https://www.wikidata.org/w/api.php"
SPARQL_URL = "https://query.wikidata.org/sparql"
USER_AGENT = "StockAnalyst/1.0 (personal portfolio tracker; sector enrichment)"

#: Wikidata `industry` (P452) labels observed on real holdings, mapped onto
#: the sector vocabulary FMP's `/profile` already uses. Not exhaustive by
#: design: an industry with no entry here is dropped, never guessed.
INDUSTRY_TO_SECTOR: dict[str, str] = {
    "semiconductor industry": "Technology",
    "software industry": "Technology",
    "software development": "Technology",
    "information industry": "Technology",
    "information technology industry": "Technology",
    "electronics industry": "Technology",
    "consumer electronics industry": "Technology",
    "digital distribution": "Technology",
    "publishing of application software": "Technology",
    "mobile phone industry": "Technology",
    "pharmaceutical industry": "Healthcare",
    "biotechnology industry": "Healthcare",
    "petroleum industry": "Energy",
    "energy industry": "Energy",
    "extraction of crude petroleum and natural gas": "Energy",
    "oil and gas industry": "Energy",
    "manufacture of industrial gases": "Basic Materials",
    "chemical industry": "Basic Materials",
    "iron and steel industry": "Basic Materials",
    "mining industry": "Basic Materials",
    "metal industry": "Basic Materials",
    "retail": "Consumer Cyclical",
    "fashion industry": "Consumer Cyclical",
    "luxury goods industry": "Consumer Cyclical",
    "automotive industry": "Consumer Cyclical",
    "air transport": "Industrials",
    "aerospace industry": "Industrials",
    "machinery industry and plant construction": "Industrials",
    "banking": "Financial Services",
    "insurance industry": "Financial Services",
    "telecommunications industry": "Communication Services",
    "mass media": "Communication Services",
    "food industry": "Consumer Defensive",
    "beverage industry": "Consumer Defensive",
    "utility industry": "Utilities",
    "real estate": "Real Estate",
}


def resolve_sector(company_name: str, timeout: float = 15.0) -> str | None:
    """Best-effort GICS-style sector for a company, via Wikidata.

    Never raises: an unresolvable name, no publicly-traded match, and
    industries that don't map to the existing vocabulary all come back as
    ``None`` — no data, not a guess.
    """
    try:
        candidates = _search(company_name, timeout)
        if not candidates:
            return None
        entity = _best_entity(candidates, timeout)
        if entity is None:
            return None
        for label in entity["industries"]:
            sector = INDUSTRY_TO_SECTOR.get(label)
            if sector:
                return sector
        return None
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        return None


def resolve_isin(company_name: str, timeout: float = 15.0) -> str | None:
    """Best-effort ISIN for a company, via the same entity resolution
    `resolve_sector` uses above — same P414-first-match rule, same "no data,
    not a guess" contract on failure.

    Used to spot a same-company watchlist/screener duplicate added under a
    different ticker: ISIN survives a ticker-format change where the symbol
    string itself does not (DEVLOG "Decision 3u.16" — `ESLOY.US`, `ESLOF.US`,
    `EI.SW.US` and `EL.PA.US` were four unrelated strings for one company).
    """
    try:
        candidates = _search(company_name, timeout)
        if not candidates:
            return None
        entity = _best_entity(candidates, timeout)
        if entity is None:
            return None
        return entity["isin"]
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        return None


def _search(name: str, timeout: float) -> list[str]:
    response = httpx.get(
        SEARCH_URL,
        params={
            "action": "wbsearchentities",
            "search": name,
            "language": "en",
            "format": "json",
            "type": "item",
            "limit": 6,
        },
        timeout=timeout,
        headers={"User-Agent": USER_AGENT},
    )
    if response.status_code != 200:
        return []
    return [item["id"] for item in response.json().get("search", [])]


def _best_entity(candidate_qids: list[str], timeout: float) -> dict | None:
    """The best-ranked candidate's raw claims — industries and ISIN together,
    one SPARQL round trip shared by `resolve_sector` and `resolve_isin`.

    Walks candidates in original search-rank order — SPARQL's VALUES does not
    preserve it — and stops at the first one that lists a stock exchange
    (P414, already filtered by the query below). That is the right entity
    even if it turns out to have no mappable industry or no ISIN claim;
    falling through to a lower-ranked candidate at that point would trade a
    correct-but-empty result for a wrong-but-populated one.
    """
    values = " ".join(f"wd:{qid}" for qid in candidate_qids)
    query = f"""
    SELECT ?item
           (GROUP_CONCAT(DISTINCT ?industryLabel; separator="|") AS ?industries)
           (SAMPLE(?isin) AS ?isinSample) WHERE {{
      VALUES ?item {{ {values} }}
      ?item wdt:P414 ?exchange .
      OPTIONAL {{
        ?item wdt:P452 ?industry .
        ?industry rdfs:label ?industryLabel .
        FILTER(LANG(?industryLabel) = "en")
      }}
      OPTIONAL {{ ?item wdt:P946 ?isin . }}
    }} GROUP BY ?item
    """
    response = httpx.get(
        SPARQL_URL,
        params={"query": query, "format": "json"},
        timeout=timeout,
        headers={"User-Agent": USER_AGENT},
    )
    if response.status_code != 200:
        return None
    rows = response.json()["results"]["bindings"]
    by_qid = {row["item"]["value"].rsplit("/", 1)[-1]: row for row in rows}

    for qid in candidate_qids:
        row = by_qid.get(qid)
        if row is None:
            continue
        industries = row.get("industries", {}).get("value", "")
        return {
            "industries": [label.strip() for label in industries.split("|") if label.strip()],
            "isin": row.get("isinSample", {}).get("value"),
        }
    return None
