# Stock Analyst

A local application for tracking and analysing an equity portfolio: deciding whether to
**hold or sell** your positions, whether to **enter or wait** on the ones you follow, and
spotting **hidden gems** — by cross-referencing several public data sources.

Available in English, French and Polish.

> This tool produces indicators from public data. It is not investment advice, and the
> decisions remain yours.

📓 The [development log](DEVLOG.md) records the steps, the decisions and their reasons,
along with the bugs encountered and their root causes. This README describes the *current
state* of the project; the log explains *how it got there*.

---

## Read this first: the XTB API no longer exists

XTB **permanently shut down its API on 14 March 2025**. Their help centre is explicit:
"*API access is no longer available. The service was discontinued on March 14, 2025.*"
([source](https://www.xtb.com/int/help-center/our-platforms-6-4/does-xtb-offer-investment-automation-tools-4))

In practice:

- the `xapi.xtb.com` and `ws.xtb.com` hosts are switched off;
- the documentation domain `developers.xstore.pro` no longer even resolves in DNS;
- community libraries have been archived (e.g. [`pawelkn/xapi-python`](https://github.com/pawelkn/xapi-python), archived 2025-08-26);
- XTB offers **no replacement**: no API, no automated trading, no copy trading.

**Automatic account synchronisation is therefore impossible.** The application is fed by
**file exports** from xStation. That is the only reliable, terms-compliant route — and it
has the advantage of requiring no credentials at all: nothing sensitive is ever stored.

### Exporting your data from xStation

1. Open [xStation 5](https://xstation5.xtb.com/);
2. **Account history** tab → **Export** button;
3. period **All**, format **Excel**;
4. drop the resulting file onto the Portfolio page.

The file contains three sheets — *Open Positions*, *Closed Positions*, *Cash Operations* —
all handled in a single import.

**One export only covers one account.** If you hold several (a brokerage account and a
tax-wrapper account, say), export them separately and import both files: they coexist
without overwriting each other, each identified by its *Product* column.

The import is **idempotent**: re-importing the same file, or an overlapping period,
creates no duplicates. Open positions are a snapshot and replace the previous import
**of that account only**; hand-entered positions are always preserved.

---

## Getting started

Requirements: Python 3.13+, Node 20+.

### Backend

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

```bash
cd backend && .venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

Interactive API docs: <http://127.0.0.1:8000/docs>

Schema changes go through Alembic (`backend/alembic/`), not by hand-editing the
database. The app applies pending migrations itself on every startup — nothing to
run manually to *use* the app. When you change a model in `app/models.py`, generate
the migration for it before committing:

```bash
cd backend && .venv/bin/alembic revision --autogenerate -m "short description"
```

Review the generated file in `alembic/versions/` before committing — autogenerate
is a good first draft, not a guarantee (it won't detect a plain column rename, for
instance, and will instead emit a drop + add that loses data).

### Frontend

```bash
cd frontend && npm install && npm run dev
```

UI: <http://localhost:5173>. The dev server proxies `/api` to the backend, so there is no
CORS setup to worry about.

### Configuration

Copy `.env.example` to `.env` at the repository root. **Every key is optional**: the
application starts without any of them, and the affected features disable themselves
cleanly rather than failing startup.

| Variable | Purpose | Cost |
|---|---|---|
| `BASE_CURRENCY` | Currency used for portfolio totals | — |
| `TWELVEDATA_API_KEY` | **Recommended.** Fallback price provider for when Yahoo throttles — see below | free |
| `FMP_API_KEY` | Optional third US price source (250 req/day). Does **not** cover Euronext on the free tier | free |
| `SEC_USER_AGENT` | Official US fundamentals via SEC EDGAR. Format `First Last email@example.com` — the SEC rejects anonymous requests | free |
| `ALPHA_VANTAGE_API_KEY` | Fallback prices, plus per-instrument news + sentiment (the "Insights" row expander) | free |
| `PERPLEXITY_API_KEY` | Per-instrument AI qualitative commentary, on request — see "Insights" | **paid** |

### Tests

```bash
cd backend && .venv/bin/python -m pytest
```

Network tests are marked `@pytest.mark.network` and excluded by default. They *skip*
rather than fail when a provider is throttling: being rate-limited says nothing about
whether our code is correct.

Two things that silently disable a key, both worth knowing:

- **Location.** `.env` belongs at the **project root**, not in `backend/`. Both are read
  (the root wins if both exist), but only the root is the documented spot.
- **Placeholders.** A value left as `votre_cle`, `your_key`, `changeme` and similar is
  treated as *unset*. Forwarding a placeholder to a provider produces an opaque 401
  halfway through a refresh, which is much harder to diagnose than the feature simply
  staying off.

`GET /api/health` shows which `.env` files were found and which integrations are actually
enabled — the fastest way to check a key is being read.

> **If price refreshes return nothing but "rate limited":** Yahoo blocks by IP, and a
> block can persist for a long time once tripped. Add a free `TWELVEDATA_API_KEY` to
> `.env` — signup takes an email and no card — and the fallback takes over. The app tells
> you this in the refresh report rather than leaving you to guess.

---

## Architecture

```
backend/app/
├── config.py            Settings from .env, no hardcoded keys
├── messages.py          Language-neutral message codes
├── models.py            SQLAlchemy ORM (local SQLite)
├── ingest/
│   ├── xtb_import.py    xStation export parser
│   └── service.py       Persistence, deduplication, idempotency
├── symbols/mapping.py   Broker symbol ↔ provider symbol
├── routers/             HTTP endpoints
├── providers/           Data sources (phase 2)
└── analysis/            Indicators and scoring (phase 3)

frontend/src/
├── api/                 Typed HTTP client
├── i18n/                Translation catalogues (en, fr, pl)
├── components/          Reusable components
└── pages/               Portfolio, Watchlist, Hidden gems
```

### Three design commitments worth knowing

**1. The API is language-neutral.** The backend never returns prose. Diagnostics come back
as a `code` plus parameters, and the client turns them into a sentence:

```json
{ "code": "import.unresolvedSymbols", "params": { "count": 2, "symbols": ["FOO.XX"] } }
```

This matters because import diagnostics are the most useful thing the backend produces —
they say which rows were skipped and why. Committing them to one language would make them
useless to everyone else, and no amount of frontend work could recover the meaning. A test
enforces the rule: no warning may contain a sentence.

Polish plural rules are handled through `Intl.PluralRules`: Polish has three categories
(`one`, `few` for 2–4, `many` for 0 and 5+), so a `count === 1 ? a : b` ternary would be
wrong twice over.

**2. The parser is tolerant, but never silent.** The xStation export format is not publicly
documented and varies with the interface language. Columns are therefore matched through
normalised aliases (English and French) and tables classified by *column signature* rather
than by heading. Anything not understood is surfaced in the import warnings, and the source
row is stored verbatim (the `raw` field) so everything can be recomputed without asking for
the file again.

If an export fails to parse, `COLUMN_ALIASES` in
[`xtb_import.py`](backend/app/ingest/xtb_import.py) is what needs extending.

Four traps in the real format, all verified against production exports and covered by
tests — worth knowing before touching the parser:

| Trap | Consequence if ignored |
|---|---|
| The workbook declares a wrong `A1:A1` dimension | In `read_only` mode openpyxl trusts it and the file looks **empty** |
| `Ticker` holds the symbol, `Instrument` the company name | "Canadian Pacific" would be treated as a ticker |
| Open positions come in **two levels**: one aggregate row per holding, then one row per lot | Every holding counted **twice** |
| The `Position ID` of closed positions is **not unique** (partial closes: 223 rows for 220 ids) | Unique-constraint violation on import |

**3. Missing data is never treated as zero.** A position without figures is **excluded from
the totals** and flagged, rather than counted as zero — which would produce a wrong total
wearing the appearance of a correct one. The same principle will apply to scoring: a pillar
without data is dropped from the calculation and the weights renormalised, with the score
marked "partial".

### Reconciling the amounts

The export provides no "purchase value" for open positions, so it is derived exactly as
`market value − unrealised P&L`, both being expressed in the account currency. The price
shown comes from the lot rows and stays in the instrument's currency — it is **not**
recomputed as `value / quantity`, which would give a figure in euros that cannot be
compared to the average cost.

No FX conversion is applied. The totals reconcile to the cent against the summary rows
inside the XTB file itself.

### Symbol mapping

XTB suffixes by country (`AAPL.US`, `TTE.FR`), Yahoo by listing venue (`AAPL`, `TTE.PA`).
No official table exists, so the application converts suffixes, which covers the large
majority of cases.

**Important limitation**: the conversion only rewrites the suffix, never the root of the
symbol. `ERICB.SE` becomes `ERICB.ST` where Yahoo expects `ERIC-B.ST`. An automatic mapping
is therefore displayed as **"unverified"** until data has actually been fetched with it,
and can be corrected in one click from the positions table. Corrections are persisted and
reapplied to later imports.

The decision rests on the **category supplied by the broker** (`STOCK`, `ETF`, `CFD`),
not on a naming heuristic. That matters: `GOLD.US` is *Barrick Gold*, a perfectly
analysable equity that a filter on the word "GOLD" would wrongly reject. CFDs (`US500`,
`BITCOIN`, `NATGAS`...) are left unmapped — they have no fundamentals — and are not
reported as anomalies, since that is the expected outcome.

---

## Project status

| Phase | Content | Status |
|---|---|---|
| 1 | Foundation, XTB import, Portfolio page | ✅ done |
| 1b | Real-file hardening (7 bugs) | ✅ done |
| 1c | Version control, data scrubbing | ✅ done |
| 1d | English codebase, i18n (en/fr/pl) | ✅ done |
| 2 | Provider layer, market prices, charts | ✅ done |
| 3 | Scoring engine (4 pillars, `scoring.yaml`) | ✅ done |
| 4 | Watchlist and entry timing | ✅ done |
| 5 | Hidden gems page (screener) | ✅ done |
| 6 | News/sentiment (Alpha Vantage) + qualitative commentary (Perplexity) | ✅ done |

### Planned data sources (phase 2)

| Source | Role | Coverage | Note |
|---|---|---|---|
| Yahoo chart endpoint | Daily prices | worldwide | The backbone. Unofficial and **rate-limits hard** — four rapid requests earned a 429 that outlasted 30 minutes |
| FMP | Daily prices | **US only on the free tier** | Verified live: non-US symbols answer HTTP 402. Kept as a third US source |
| Boursorama | Daily prices | **Euronext Paris** | No key. Home-market prices for French shares and ETFs. Requires an `X-Requested-With` header |
| Boerse Frankfurt | Daily prices | **Europe** | No key, no session. Keyed on **ISIN only**. Prices are the Frankfurt listing, not the home market |
| Twelve Data | Fallback prices | **US only on the free tier** | Verified live. European venues need a paid plan — their API says so explicitly |
| SEC EDGAR | Official fundamentals (XBRL) | **US only** | Free, official, no key |
| Alpha Vantage | Fallback prices + news/sentiment | worldwide | Free, 5 req/min. `NEWS_SENTIMENT` shares the same throttle as its price fetches |
| Perplexity | Qualitative commentary | worldwide | **Paid** — on demand, one instrument at a time, cached |

**Sources are routed by market, not tried blindly.** Each provider declares what it can
serve, so a French holding never spends a request on a US-only free tier. On this
portfolio that leaves 33 holdings with three independent sources and 4 with two — none
with only one. `GET /api/prices/providers` shows the current state of each.

An asymmetry we accept: fundamentals coverage is excellent for US names and noticeably
patchier elsewhere on free tiers. The UI always shows the data coverage and which source
actually served the data.

### Caveats

- **No real-time data**: free prices are delayed. This tool is for fundamental analysis,
  not intraday trading.
- **Price targets and analyst ratings** are now largely paywalled; the sentiment pillar
  will rest mostly on the news flow.
- **European holdings need an ISIN.** Boerse Frankfurt covers them for free, but is
  keyed on ISIN and nothing else — its search endpoint ignores its search term, and no
  free service tested maps a ticker to an ISIN reliably. Type the ISIN on the position
  row (it is on your broker's instrument page). It is never guessed: a wrong ISIN would
  silently return **another company's** prices.
- **Frankfurt does not list every European fund.** French PEA ETFs in particular are
  absent, so an ISIN will not help them; they need Yahoo, which covers them under the
  `.PA` symbols already derived.
- **Frankfurt prices are the Frankfurt listing.** For a Paris- or Amsterdam-listed share
  the two track closely (0–3% in practice) but they are different venues.
- **Rate limits are respected, not worked around.** After a provider answers 429 it is
  left alone for 15 minutes rather than retried on every remaining instrument, calls are
  spaced 5 seconds apart, and each instrument is asked about once per day. Hammering
  through a throttle is what turns a short limit into a long block.
- **Refreshing prices is deliberately slow.** Free providers throttle, so a refresh is
  serialised, spaced out, and bounded by a time budget; it reports what is left and you
  click again. That is a constraint of the sources, not a bug.
- Stooq was dropped as a source: it now serves a JavaScript proof-of-work anti-bot
  challenge instead of CSV, and defeating that is out of scope for this project.
- No scraping of Finviz or TradingView: against their terms.
