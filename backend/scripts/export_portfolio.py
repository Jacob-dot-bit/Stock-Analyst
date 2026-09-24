#!/usr/bin/env python3
"""Export the full portfolio state as a single JSON snapshot.

Calls the backend's own already-correct endpoints (not raw SQL against
stock_analyst.db) so this export's numbers never drift from what the app itself
computes and shows — no valuation logic is reimplemented here.

Requires the backend running locally: `uvicorn app.main:app` (or however you
normally start it) on http://127.0.0.1:8000. The backend's own middleware only
accepts loopback connections (see app/main.py), so this must run on the host —
not from inside a container.

Output path: override with the `PORTFOLIO_EXPORT_PATH` environment variable
(default `~/portfolio_export.json`).

Usage: python3 scripts/export_portfolio.py
"""
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

BASE_URL = "http://127.0.0.1:8000"
OUT_PATH = Path(os.environ.get("PORTFOLIO_EXPORT_PATH", Path.home() / "portfolio_export.json"))
BREAKDOWN_DIMENSIONS = ("category", "currency", "country", "sector")


def _get(path: str, params: dict | None = None):
    url = f"{BASE_URL}{path}"
    if params:
        url += "?" + urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        print(f"export_portfolio: FAILED {path}: {e}", file=sys.stderr)
        return None


def main() -> None:
    portfolio = _get("/api/portfolio")
    if portfolio is None:
        print(f"export_portfolio: backend unreachable at {BASE_URL} — is it running? Aborting.",
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
        # The user's own stated rules — every configured limit (satisfied or
        # not), not just current breaches, so a consumer can tell "within
        # bounds" from "no rule set" rather than assuming the latter. See
        # DEVLOG "Decision 3u.65".
        "personal_policy": _get("/api/portfolio/policy"),
        "personal_policy_limits": _get("/api/portfolio/policy/limits"),
        "personal_policy_gaps": _get("/api/portfolio/policy/gaps"),
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"export_portfolio: wrote {OUT_PATH} ({OUT_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
