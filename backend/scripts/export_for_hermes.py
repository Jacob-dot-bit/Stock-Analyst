#!/usr/bin/env python3
"""Export the full portfolio state for the "portfolio-analyst" Hermes skill.

Calls the backend's own already-correct endpoints (not raw SQL against
stock_analyst.db) so this export's numbers never drift from what the app itself
computes and shows — no valuation logic is reimplemented here.

Requires the backend running locally: `uvicorn app.main:app` (or however you
normally start it) on http://127.0.0.1:8000. The backend's own middleware only
accepts loopback connections (see app/main.py), so this must run on the host —
never from inside a container, which is exactly why Hermes can't call the API
directly and instead reads the JSON file this script produces.

Usage: python3 scripts/export_for_hermes.py
"""
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

BASE_URL = "http://127.0.0.1:8000"
# Deliberately NOT under ~/.hermes: that tree gets reset to owner-only permissions
# by the Hermes container's own init on every (re)start, which broke group-shared
# access repeatedly. This directory is bind-mounted separately (read-only, see
# docker run's -v ~/Hermes/portfolio-data:/opt/portfolio-data:ro) so it's never
# touched by that reset and never needs special permissions at all.
OUT_PATH = Path.home() / "Hermes" / "portfolio-data" / "portfolio_export.json"
BREAKDOWN_DIMENSIONS = ("category", "currency", "country", "sector")


def _get(path: str, params: dict | None = None):
    url = f"{BASE_URL}{path}"
    if params:
        url += "?" + urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        print(f"export_for_hermes: FAILED {path}: {e}", file=sys.stderr)
        return None


def main() -> None:
    portfolio = _get("/api/portfolio")
    if portfolio is None:
        print(f"export_for_hermes: backend unreachable at {BASE_URL} — is it running? Aborting.",
              file=sys.stderr)
        sys.exit(1)

    breakdown = {dim: _get("/api/portfolio/breakdown", {"by": dim}) for dim in BREAKDOWN_DIMENSIONS}
    tax_years = _get("/api/tax/years") or {}
    tax_summaries = {str(y): _get("/api/tax/summary", {"year": y}) for y in tax_years.get("years", [])}

    # /lots is per-instrument (no bulk mode) — fetch once per distinct instrument held.
    instrument_ids = {p["instrument"]["id"] for p in portfolio.get("positions", [])}
    lots_by_instrument = {
        str(iid): _get("/api/portfolio/lots", {"instrument_id": iid}) for iid in sorted(instrument_ids)
    }

    data = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "portfolio": portfolio,
        "breakdown_by": breakdown,
        "allocation": _get("/api/portfolio/allocation"),
        "attention": _get("/api/portfolio/attention"),
        "data_health": _get("/api/portfolio/data-health"),
        "lots_by_instrument": lots_by_instrument,
        "dividends_summary": _get("/api/dividends/summary"),
        "tax_summaries_by_year": tax_summaries,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"export_for_hermes: wrote {OUT_PATH} ({OUT_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
