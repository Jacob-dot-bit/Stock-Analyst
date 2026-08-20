"""Finviz preset screener scans — robots.txt-compliant discovery source.

Finviz's `robots.txt` (checked live, 2026-08-28) reads:

    Disallow: /screener?*
    Allow: /screener?v=340&s=it_latestbuys
    Allow: /screener?v=210&s=ta_oversold
    ... (a fixed list of other presets)

A custom-filtered query (e.g. by P/E ratio or growth rate — what "sous-
évalué"/"fort potentiel futur" would naturally map to) falls under the
`Disallow`. This module therefore never builds a custom filter — it only
ever requests one of the specific preset URLs their own `Allow` list opts
in, and always via the exact `v=`/`s=` pair from that list.

Two presets are wired here:
  - "insider_buys" (`s=it_latestbuys`) — recent insider purchases, a
    commonly-cited conviction/value signal.
  - "oversold" (`s=ta_oversold`) — RSI-oversold, a technical "cheap right
    now" signal.

Neither is "Value" or "Growth" in the sense the app's own scoring pillars
already compute — callers must label these as their own, narrower signal
(insider conviction / technical oversold), never blend them into a Value or
Growth ranking. See `routers/discovery.py` for how the result is presented.
"""

from __future__ import annotations

import httpx
from bs4 import BeautifulSoup

SCREENER_URL = "https://finviz.com/screener.ashx"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

#: robots.txt-whitelisted presets only — see module docstring. Values are
#: Finviz's own `s=` scan codes; adding a new preset here means confirming
#: it has an `Allow` entry in their robots.txt first.
PRESETS: dict[str, str] = {
    "insider_buys": "it_latestbuys",
    "oversold": "ta_oversold",
}


def fetch_preset(preset: str, timeout: float = 15.0) -> list[dict]:
    """Ticker/name/country/industry for one whitelisted Finviz preset scan.

    Never raises: an unknown preset, a network problem, or a page Finviz
    changed the layout of all come back as an empty list — no data, not a
    guess (same contract `providers/wikidata.py` uses).
    """
    scan = PRESETS.get(preset)
    if scan is None:
        return []

    try:
        response = httpx.get(
            SCREENER_URL,
            params={"v": "340", "s": scan},
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
            follow_redirects=True,
        )
        if response.status_code != 200:
            return []
        return _parse_snapshot_blocks(response.text)
    except httpx.HTTPError:
        return []


def _parse_snapshot_blocks(html: str) -> list[dict]:
    """One dict per company snapshot card on a `v=340` screener page.

    Each card is a `table.screener_snapshot-table-header` with label/value
    rows (Ticker, Company, Country, Industry) — verified live against a
    real response, 2026-08-28.
    """
    soup = BeautifulSoup(html, "html.parser")
    results = []
    for header in soup.select("table.screener_snapshot-table-header"):
        fields: dict[str, str] = {}
        for row in header.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) != 2:
                continue
            label = cells[0].get_text(strip=True)
            if label == "Ticker":
                link = cells[1].find("a")
                # The ticker cell also carries a "[NASD, S&P 500]" exchange
                # annotation outside the link — only the link text is the
                # bare ticker.
                fields["ticker"] = link.get_text(strip=True) if link else cells[1].get_text(strip=True).split("[")[0]
            elif label == "Company":
                link = cells[1].find("a")
                fields["name"] = link.get_text(strip=True) if link else cells[1].get_text(strip=True)
            elif label in ("Country", "Industry"):
                fields[label.lower()] = cells[1].get_text(strip=True)
        if fields.get("ticker"):
            results.append(fields)
    return results
