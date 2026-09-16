# Architecture reference

A map, not a story — for the *why* behind any of this, see [DEVLOG.md](DEVLOG.md).
For what the app does today, see [README.md](README.md). Keep this file current
whenever a router endpoint, model, or pattern changes.

## Directory map

```
backend/app/
  routers/       FastAPI endpoints — one file per resource area
  ingest/        XTB file parsing + get_or_create_instrument
  prices/        Daily-bar history, live quotes, FX, provider-quota tracking
  fundamentals/  SEC EDGAR + ESEF fetch/cache
  scoring/       Composite score computation (config, metrics, service)
  symbols/       Broker-symbol ↔ provider-symbol mapping/resolution
  providers/     One file per external data source, behind a common interface
  analysis/      Per-instrument on-request enrichment: news_service.py (Alpha
                 Vantage news/sentiment), commentary_service.py (Perplexity) —
                 never read by scoring/service.py. Originally slated in an
                 early sketch for "indicators and scoring," which ended up
                 living in scoring/ instead; repurposed here rather than left
                 empty.

frontend/src/
  pages/         One per route (Portfolio, Transactions, Watchlist, Screener, Settings)
  components/    Shared + page-specific React components
  hooks/         useHiddenColumns (column-visibility persistence)
  api/           types.ts (response shapes) + client.ts (fetch wrappers)
  i18n/          en.ts / fr.ts / pl.ts + index.tsx (the t()/format* hooks)
```

## Data model (`backend/app/models.py`)

| Model | Table | Purpose |
|---|---|---|
| `Instrument` | `instruments` | The pivot: broker symbol ↔ provider symbol, category, mapping status. Can exist with zero positions (watchlist-only, or an orphaned manual entry). |
| `ImportBatch` | `import_batches` | One broker file import (XTB, Mintos, or Amundi) — enables idempotency and undo. |
| `Transaction` | `transactions` | One broker ledger line (buy/sell/dividend/tax/fee/...), preserved faithfully. |
| `Position` | `positions` | An open holding — the presence of a row *is* "held". Replaced wholesale on re-import; deleted (not zeroed) on a full sell. `value_as_of` (Decision 3u.50) is the date this position's *value* was declared by its source, set only for Mintos/Amundi's broker-declared valuations. |
| `AmundiFundSnapshot` | `amundi_fund_snapshots` | Every Amundi fund's disclosed figures from every import, keyed by `broker_symbol`+`as_of` — kept even when a newer import wholesale-replaces `Position`, so a later gain-less Synthese import can still compute a real per-fund gain since its own last disclosed snapshot (Decision 3u.48). Not FK-linked to `Instrument`: a pure historical log. |
| `Lot` | `lots` | One actual buy fill — replay unit for the historical value chart. Append-only, never bulk-deleted on re-import. |
| `WatchlistItem` | `watchlist_items` | A watched-but-unheld instrument. `instrument_id` is UNIQUE. See "Anti-join self-healing" below. |
| `ScreenerCandidate` | `screener_candidates` | A hand-picked candidate to screen for hidden gems — held out of the ranking once bought or watchlisted. `instrument_id` is UNIQUE. |
| `DiscoveryCandidate` | `discovery_candidates` | A candidate surfaced automatically — the static S&P 500 universe, or a whitelisted Finviz preset scan. A much larger, uncurated pool than `ScreenerCandidate`; never shown directly, only the ranked top few. `instrument_id` is UNIQUE. |
| `SymbolOverride` | `symbol_overrides` | Manual broker-symbol → provider-symbol correction. |
| `AllocationTarget` | `allocation_targets` | User-configured target min/max % range for one asset class. `category` is UNIQUE. Descriptive only — never read by anything that suggests a trade. |
| `PriceBar` | `price_bars` | One cached daily candle. |
| `LastQuote` | `last_quotes` | Most recent live (intraday) quote per instrument — one row, no history. |
| `AppMetadata` | `app_metadata` | Singleton row: last price-refresh timestamp, etc. |
| `ProviderUsage` | `provider_usage` | Per-provider request count for the current quota period (only quota-tracked providers get a row). |
| `FxRate` | `fx_rates` | Daily-cached currency conversion rate. |
| `Fundamental` | `fundamentals` | One filed annual figure (concept/fiscal_year/value) for one instrument, from EDGAR or ESEF. |
| `NewsSentiment` | `news_sentiments` | Cached Alpha Vantage news + per-article sentiment, one row per instrument. Free, softer TTL than commentary. |
| `InstrumentCommentary` | `instrument_commentaries` | Cached Perplexity qualitative commentary, one row per instrument. 7-day TTL is a cost decision, not a freshness one. |
| `FactorReturn` | `factor_returns` | One day's Carhart four-factor return series (Mkt-RF/SMB/HML/Mom/RF), fetched from Kenneth French's Data Library. `region` ("US"/"EUROPE") + date is UNIQUE. Decimal returns (source is percent). |
| `CorporateAction` | `corporate_actions` | A confirmed stock split or reverse split. Never mutates `PriceBar`/`Lot` — read-time adjustment only, see "Stock splits" below. |
| `PersonalPolicy` | `personal_policy` | Singleton: the user's own, self-declared objective/horizon/liquidity/risk-tolerance — every field optional, never inferred or scored. See "Personal policy" below. |
| `PersonalPolicyLimit` | `personal_policy_limits` | One personal concentration rule (dimension + target + min/max %). `(dimension, target)` UNIQUE. |
| `JournalEntry` | `journal_entries` | A user-written decision — `thesis`, optional `instrument_id` (nullable, no cascade delete), `entry_date` (set once, never edited), optional `review_date`/`outcome_note`. See "Decision journal" below. |

## API endpoints

### `/api/portfolio` (`routers/portfolio.py`)
- `GET  ""` — current portfolio state, cache-only, no provider calls.
- `GET  /breakdown?by=` — totals grouped by category/currency/country/sector.
- `GET  /allocation` — current allocation by asset class vs. a user-configured target range (descriptive only — never a buy/sell suggestion). Union of held categories and targeted-but-unheld ones.
- `PUT  /allocation/{category}` — set (or replace) the target min/max range for one asset class.
- `DELETE /allocation/{category}` — remove a configured target.
- `GET/PUT /policy` — the user's own, self-declared investment policy (objective/horizon/liquidity/risk tolerance) — every field optional, never inferred or scored. See "Personal policy" below.
- `GET/POST /policy/limits`, `DELETE /policy/limits/{id}` — personal concentration rules (per line/sector/country/currency/category/declared-valuation).
- `GET  /policy/gaps` — current portfolio vs. every configured limit, breaches only — descriptive, never a buy/sell suggestion.
- `GET  /risk/concentration?limit=` — every held position's weight, largest first, capped at `limit` — the unconditional counterpart to Personal Policy's `line` limit. See "Portfolio risk page" below.
- `GET  /risk/liquidity` — declared-valuation share (Mintos Core P2P / Amundi ESR) by source and freshness — the unconditional counterpart to Personal Policy's `declared_valuation` limit.
- `GET  /risk/drawdown` — largest peak-to-trough decline in real historical value, from the same series `/value-history` returns.
- `GET  /attention` — a short, ranked list of facts worth checking today (stale/error prices, unresolved symbols, allocation gaps), cache-only, purely descriptive — see "Attention card" below.
- `GET  /data-health` — held (open) positions only, one row per instrument with its valuation source/freshness and corporate-action trust state resolved into one overall severity (v2) — the detailed, fix-it-console counterpart to `/attention`'s compact counts. See "Data health console (v2)" below.
- `GET  /onboarding` — whether each first-run step (import, refresh, resolve unmapped symbols, fetch fundamentals, set an allocation target, start a watchlist) has been done at least once — see "Getting-started checklist" below.
- `GET  /position-signals` — one "reinforce"/"reduce"/"hold"/"not_applicable" label per held instrument, from a fixed rule combining its composite score with its asset class's allocation state — see "Position/watchlist signals" below.
- `GET  /value-history` — real historical value, replaying actual buys/sells (`prices/history_service.py`).
- `POST /enrich-sectors` — one-off sector/industry lookup for held instruments.
- `POST /backfill-isins` — one-off ISIN lookup for every held/watchlisted/screened instrument with a `name` but no `isin` yet (`symbols/duplicates.py::backfill_isins`).
- `GET  /symbol-search?q=` — company-name autocomplete (FMP, US-only free tier).
- `POST /refresh-live` — budgeted live-quote round, returns the whole portfolio recomputed.
- `GET  /refresh-live/status` — progress of a live-quote round in flight.
- `POST /positions` — hand-entered position (creates `Instrument`+`Position`+one synthetic `Lot`).
- `DELETE /positions/{id}` — remove a position (and its still-open lots).
- `DELETE /instruments/{id}` — remove an instrument with zero positions/lots/transactions/watchlist rows.
- `PUT  /symbol-overrides` — manual broker↔provider symbol correction.
- `PUT  /isin` — record an ISIN (unlocks the Frankfurt/European price source).
- `GET  /lots?instrument_id=` — every `Lot` (open and closed) for one instrument, newest-opened first. Feeds the per-position detail panel's "Historique" section — see "Per-position detail panel" below.

### `/api/prices` (`routers/prices.py`)
- `POST /refresh?force=&symbols=` — bring held (+ benchmark + watchlist) instruments' daily history up to date; budgeted, thread-pooled.
- `GET  /refresh/status` — live progress (`RefreshProgress` — see pattern below).
- `GET  /providers` — which price sources are configured and what each can serve.
- `GET  /sparklines?days=` — compact close series per held instrument, one call.
- `GET  /{id}/history?days=` — cache-only chart data, never triggers a fetch.

### `/api/scoring` (`routers/scoring.py`)
- `POST /fundamentals/refresh?force=` — EDGAR-then-ESEF fundamentals fetch for held stocks; sequential, locked.
- `GET  /fundamentals/refresh/status` — live progress (`FundamentalsProgress`).
- `GET  /scores` — every held STOCK/ETF's composite score, computed live from cached data.

### `/api/watchlist` (`routers/watchlist.py`)
- `POST ""` — add a symbol (rejects an already-held or already-watched instrument, 400; rejects a symbol no price provider recognizes, 422 — see "Reject-on-add guardrail" below). Optional `company_name` powers a best-effort same-company duplicate warning — see "ISIN duplicate detection" below; never blocks the add.
- `GET  ""` — list watched instruments, cache-only price resolution.
- `PATCH /{id}` — update target entry price / note; optional `company_name` retroactively runs the same ISIN duplicate check as the create endpoint.
- `DELETE /{id}` — remove the watchlist row (never the underlying `Instrument`).
- `GET  /scores`, `GET  /sparklines` — same shape as the prices/scoring equivalents, scoped to watched instruments.
- `GET  /signals` — one "reinforce"/"hold"/"not_applicable" label per watched instrument (never "reduce" — nothing here is held) — see "Position/watchlist signals" below.

### `/api/screener` (`routers/screener.py`)
- `POST ""` — add a candidate (rejects an already-held, already-watchlisted, or already-a-candidate instrument, 400; rejects a symbol no price provider recognizes, 422 — see "Reject-on-add guardrail" below). Same optional `company_name` / duplicate-warning behavior as `/api/watchlist`.
- `GET  ""` — list candidates, cache-only price resolution.
- `PATCH /{id}` — the only editable thing about a candidate: `company_name`, same retroactive ISIN check as `/api/watchlist`'s PATCH.
- `DELETE /{id}` — remove the candidate row (never the underlying `Instrument`).
- `GET  /scores` — same shape as `/api/watchlist/scores`, but **sorted by composite descending** (`None` last) — ranking is the point.
- `GET  /sparklines` — same shape as `/api/watchlist/sparklines`, scoped to candidates.

### `/api/discovery` (`routers/discovery.py`)
- `POST /import-sp500` — one-off bulk import of the static, bundled S&P 500 constituent list (`app/data/sp500_constituents.json`, fetched once from Wikipedia and committed — not a live API) as `DiscoveryCandidate` rows, `source="sp500"`.
- `POST /refresh` — evaluate the next fixed-size batch (`discovery/service.py::BATCH_SIZE = 20`) of not-yet-verified S&P 500 candidates: price refresh + fundamentals fetch, same as the existing per-instrument pipeline. No internal time budget (`fetch_fundamentals` processes its whole input synchronously) — the batch size itself is the bound. Click again to continue, same pattern as other budgeted operations.
- `GET  /candidates?rank_by=value|growth&limit=` — ranks evaluated, not-already-tracked candidates by one existing Value or Growth pillar score (reuses `scoring/service.py::compute_scores` — no new notion of "undervalued"). Anti-joined against `Position`/`WatchlistItem`/`ScreenerCandidate`, same pattern as the watchlist/screener anti-joins.
- `POST /finviz?preset=insider_buys|oversold` — fetches one of exactly two Finviz preset scans, the only ones whitelisted by Finviz's own `robots.txt` (see "Discovery: two-source candidate search" below), scores and returns them live (not persisted as a batch — small, on-demand result set).
- Every candidate returned by `/candidates` and `/finviz` carries a `recommendation` ("buy"/"hold"/"sell"/`None`), mechanically derived from `composite_score` via `scoring/service.py::score_band` (high→buy, mid→hold, low→sell, none→`None`) — a deliberate, user-requested exception to this app's usual fact-based labeling, scoped to Discovery only (see DEVLOG "Decision 3u.21"). Position/watchlist signals elsewhere are unaffected and stay descriptive.
- Every candidate also carries `instrument.price_status` (reuses `prices/service.py::price_status` unchanged, same signal the positions/screener/watchlist tables already show) and `corporate_action_pending` (true when an unresolved `ProviderCorporateActionCandidate` group exists for the instrument, via `corporate_actions/service.py::list_outstanding_candidates`, computed once per request). Both are client-side filter inputs for the frontend's "data quality only" toggle — no new persistence, no new business logic, purely reused signals. See DEVLOG "Step 3u.62".

### `/api/prediction` (`routers/prediction.py`)
- `POST /backfill-history` — phase 1 of a real, backtestable Discovery prediction (DEVLOG "Decision 3u.22"): pulls `prediction/service.py::BACKFILL_YEARS` (5) years of daily bars for every already-priced instrument, one call per instrument covering the whole window. Price-only, deliberately: `Fundamental` rows hold only each concept's latest known figure, not a dated history, so a fundamentals-based backtest today would be lookahead bias (using information that didn't exist yet at the date being tested). `PriceBar` is naturally point-in-time safe, so it's the only input this phase (and the model phase after it) touches. Runs synchronously, same "blocks for the duration, poll status separately" convention as `POST /api/scoring/fundamentals/refresh`.
- `GET  /backfill-history/status` — live progress of the backfill currently in flight, or the last completed one.
- `POST /backtest` — phase 2 (DEVLOG "Decision 3u.23"): trains a `scikit-learn` `LogisticRegression` on `prediction/features.py`'s price-only features (momentum, SMA ratios, realized volatility), split strictly chronologically (train on the earlier 70% by date, test on the later 30% — never a random split, which would leak future market conditions into training). Recomputed live on every call, not persisted, matching `compute_scores`'s own always-recompute convention. Reports honest metrics — accuracy plus the mean *realized* forward return of the "predicted up" vs "predicted down" buckets — and two explicit warning flags (`low_sample_warning`, `single_class_warning`) rather than a bare number that could misread as more confident than it is. Wired into the Discovery UI as an aggregate report only (`BacktestPanel.tsx`) — deliberately never a per-instrument prediction label, given the model's own real accuracy (~0.54, barely above chance, one test period). See DEVLOG "Decision 3u.66".

### `/api/factors` (`routers/factors.py`)
- `POST /import` — one-off (or occasional re-run) fetch of Kenneth French's daily US and Europe factor series (`providers/kenneth_french.py`) into `FactorReturn`. Free, no API key. Upserts by (region, date) — safe to re-run.
- `GET  ""` — Carhart four-factor exposure (`factors/service.py`) for every held position — explanatory, never predictive: a factor loading states what has historically driven a holding's returns, it forecasts nothing (DEVLOG "Decision 3u.24"). Held positions only, daily returns, region-matched (a US instrument regressed against US factors, a European one against Europe's — never mixed). An instrument outside the two covered regions, or without enough overlapping price/factor history, reports `not_applicable_reason` rather than a guessed regression. Cache-only.

### `/api/insights` (`routers/insights.py`)
- `POST /{instrument_id}/news` — free Alpha Vantage news + sentiment; fetches on a cache miss/stale row (1-day TTL), otherwise cache-only.
- `POST /{instrument_id}/commentary` — paid Perplexity qualitative commentary; fetches on a cache miss/stale row (`settings.perplexity_cache_ttl_days`, 7 by default), otherwise cache-only. One instrument at a time, on explicit request — never mass screening (DEVLOG "Decision 0.3").
- Both `POST`, not `GET`: they're the one place fetching happens, same convention as `POST /api/watchlist`. Never read by `compute_scores` — commentary, not a scoring input.

### `/api/transactions` (`routers/transactions.py`)
- `GET  ""` — list, filterable by type/date range/account/`instrument_id`.
- `POST ""` — hand-entered transaction.
- `PATCH /{id}` — edit.
- `DELETE /{id}` — remove.
- `POST /backfill-accounts` — one-off recovery of `account` from `raw` for rows imported before it was a real column — see "Getting-started checklist"'s sibling note, DEVLOG "Decision 3u.28".

### `/api/dividends` (`routers/dividends.py`)
- `GET  /summary` — gross/withholding/net by calendar year, account **and
  currency** — never summed across currencies (see DEVLOG "Decision
  3u.70": a single account can hold instruments in several currencies).
- `GET  /detail` — every dividend payment (reconciled with its withholding tax where attributable), filterable by year/account/instrument.
- `GET  /summary.csv`, `GET /detail.csv` — same data as CSV downloads.
- Descriptive only — never computes a tax liability. See "Dividends by year and account" below and DEVLOG "Decision 3u.28".

### `/api/tax` (`routers/tax.py`)
- `GET  /years` — every calendar year with at least one dated transaction.
- `GET  /summary?year=` — one row per account with tax-relevant activity that year: dividends/withholding (delegates to `dividends/service.py::dividend_summary`, never recomputed), interest, realized gains/losses (kept separate, never netted), fees, deposits, withdrawals, and `OTHER`-typed flows shown verbatim. **No tax rate is ever applied and no liability is ever computed** — a reconciliation aid, not a tax calculator. See "Annual tax-year reconciliation" below and DEVLOG "Decision 3u.60".
- `GET  /summary.csv` — same data as a CSV download.

### `/api/journal` (`routers/journal.py`)
- `POST ""` — write a decision (`thesis` required, optional `broker_symbol` and `review_date`). `entry_date` is always server-set to today, never accepted from the client. See "Decision journal" below and DEVLOG "Decision 3u.68".
- `GET  ""` — every entry, newest `entry_date` first.
- `PATCH /{id}` — edit the original decision: `thesis`/`review_date` only.
- `PATCH /{id}/outcome` — set `outcome_note` alone, a separate later moment from editing the original decision.
- `DELETE /{id}` — remove an entry (never the underlying `Instrument`).

### `/api/backup` (`routers/backup.py`)
- `POST ""` — create a timestamped copy of the live database in `backups/`; prunes beyond the 10 most recent.
- `GET  ""` — list existing backups, newest first.
- `POST /{filename}/restore` — restore one over the live database. `404` if the filename can't be resolved inside `backups/`, `409` if its `alembic_version` doesn't exactly match the live database's. See "Backup and restore" below and DEVLOG "Decision 3u.29".

### `/api/corporate-actions` (`routers/corporate_actions.py`)
- `GET  ?instrument_id=` — list recorded splits/reverse splits, optionally filtered. Each row carries `confidence`/`corroborating_sources` (see below).
- `POST ""` — record one by hand (`source="manual"`); runs the same raw-vs-adjusted price-history detection as automatic discovery.
- `DELETE /{id}` — remove a recorded action.
- `POST /detect` — cross-checks Alpha Vantage, Polygon, and (once readmitted) FMP's split history for every held/watchlisted/screened instrument; auto-applies an event at least two currently-active-tier sources agree on. Idempotent. See "Stock splits" below and DEVLOG "Decision 3u.30"/"Decision 3u.34"/"Decision 3u.41".
- `POST /detect-one` — targeted, single-instrument check against one on-demand source (only `"eodhd"` accepted today), for cases the bulk scan can't reach (e.g. a small-cap FMP gates behind a paid plan). Never automatic, never part of the bulk scan. See "Stock splits" below and DEVLOG "Decision 3u.35".
- `GET  /coverage` — read-only, no-provider-calls snapshot for the "Couverture automatique" UI: eligible/excluded/checked/unchecked **instrument** counts plus verified/candidate/conflict/suspect **event** counts, always kept distinct. See `corporate_actions/service.py::compute_coverage_summary` and DEVLOG "Step 3u.57".
- `GET  /outstanding` — every still-unconfirmed cross-source-merged event (never applied, never promoted), for the "Candidats à confirmer" list — same merge/classify engine as `/detect`, re-run over already-persisted data, no provider calls. Retroactively applies a group that has achieved genuine cross-source agreement across separate past scans (see `list_outstanding_candidates`'s docstring) rather than leaving it stuck as "unconfirmed" forever. See DEVLOG "Step 3u.57".
- `GET  /incomplete`, `POST /detect/resume`, `GET /resume/status`, `POST /resume/pause` / `/resume/unpause` — the targeted Alpha Vantage catch-up mechanism: `/detect/resume` only re-checks instruments Alpha Vantage has never answered (prioritizing ones already awaiting corroboration), `limit` defaulting to a margin under its daily quota. See DEVLOG "Decision 3u.41".
- `GET  /candidates`, `POST /candidates/{id}/promote` — every provider's raw per-event observation, and manually promoting one (`candidate_single_source`/`provider_conflict`) into a real `CorporateAction` after independent confirmation (e.g. via `/detect-one`). See DEVLOG "Decision 3u.41".

### `/api/imports` (`routers/imports.py`)
- `POST /xtb` / `/xtb/preview` — import (or dry-run) an XTB export file.
- `POST /mintos` / `/mintos/preview` — import (or dry-run) a Mintos quarterly PDF statement. "Core ETF 90" fills become real `Transaction`/`Position`/`Lot` rows (account `"Mintos ETF"`, current holdings recomputed from every fill imported so far via `ingest/mintos_import.py::compute_average_cost_positions`); the "Mintos Core" P2P loan pool becomes one aggregate `Position` (account `"Mintos Core P2P"`, `Instrument.category="P2P"`) with no PRU or computed gain/loss — see "P2P aggregate: no cost basis" below. See DEVLOG "Decision 3u.39".
- `POST /amundi` / `/amundi/preview` — import (or dry-run) an Amundi ESR annual statement PDF. Each statement is a snapshot, not a ledger: fund positions (`Instrument.category="FUND"`, accounts `"Amundi PEG"`/`"Amundi PERCO"`) are replaced only if the statement's date is the same age or newer than what's already stored, so all statements are safe to import in any order. The "Relevé d'information fiscale" tax document is detected and skipped with a warning, never mis-parsed. See DEVLOG "Decision 3u.39".
- `GET  ""` — import history (all sources).
- `DELETE /{id}` — undo an import (only the most recent one, across all sources).

### `/api/settings` (`routers/settings.py`)
- `GET  /providers` — provider status.
- `GET  /api-keys` — which keys are configured (values never revealed).
- `POST /verify-key` — test a key against the real provider without saving it.
- `PUT  /api-keys` — write keys to `.env`.

## Established patterns — reuse these, don't re-derive them

**Progress tracking for a long-running batch operation.** Built three times now
(prices, live quotes, fundamentals) — same shape every time: a module-level
`@dataclass` (`running`/`total`/`done`/`current_symbol`/`started_at`/
`finished_at`/`report`), a `threading.Lock`-guarded `_set_progress`/
`_advance_progress`/`get_*_progress()` trio, and a non-blocking
`threading.Lock` around the whole operation so a second concurrent call is
refused instead of doubling the work. See `prices/service.py::RefreshProgress`
(the original), `prices/quote_service.py::QuoteProgress`, or
`fundamentals/service.py::FundamentalsProgress` (the newest). The frontend
side: an 800ms `setInterval` poll against a `GET .../status` endpoint, started
right before the triggering `POST` fires, plus a mount-time "resume" effect in
case the component remounts mid-run. See `RefreshPanel.tsx` or
`FundamentalsRefreshButton.tsx`. Shared UI piece: `components/ProgressBar.tsx`
(structurally typed, works with any status shape carrying `total`/`done`/
`current_symbol`).

**Creating an instrument by hand.** `ingest/service.py::get_or_create_instrument`
— finds-or-creates by broker symbol, resolves the provider symbol via
`symbols/mapping.py::resolve()`, only *backfills* empty fields on an existing
row (never overwrites). Used by manual positions, manual transactions, and
watchlist adds alike. Category isn't broker-supplied for a hand-typed symbol —
`symbols/mapping.py::looks_like_equity()` is the existing heuristic for
inferring one (a symbol with a recognized suffix, not on the non-equity hint
list) rather than leaving it `None` and silently falling out of scoring.

**"Never guess a number."** Missing data is dropped or shown as missing, never
defaulted to zero or interpolated. Applies at every level: a metric with
missing inputs is dropped and its pillar's weights renormalize
(`scoring/service.py`); a price with nothing cached is `None`, not the last
close pretending to be current; `distance_to_target_pct` is `None`, not `0`,
when either side of the calculation is missing.

**Anti-join self-healing** (`routers/watchlist.py`, `routers/screener.py`). A
watchlist row for an instrument that's currently held is filtered out of
every read via `~exists(select(Position...))`, rather than deleted — so it
silently reappears, with its original data intact, the moment the position is
fully sold again. `routers/screener.py` extends the same idiom one layer
further: a candidate anti-joins against **both** `Position` and
`WatchlistItem` — bought *or* watchlisted, either one means it's no longer
"hidden". Worth reaching for whenever two or more features share one row but
should never all claim it at once.

**Reject-on-add guardrail** (`prices/service.py::is_permanently_unresolvable`,
used by both `add_watchlist_item` and `add_screener_candidate`). Adding a
symbol runs the same best-effort price fetch it always did, but now checks
the outcome *before* persisting the row: if the outcome is `SYMBOL_NOT_FOUND`,
`NOT_MAPPED`, or `NOT_PRICEABLE` — the three outcomes `refresh_instrument`'s
own docstring already calls unrecoverable "before tomorrow" — and no price
bar exists yet, the add is rejected with 422 instead of silently creating a
row. Deliberately excludes `NO_PROVIDER` (a local config gap, not the
symbol's fault) and `RATE_LIMITED` (today's throttling, not tomorrow's) —
both can still resolve on a later refresh, so blocking on them would reject
perfectly good symbols. Without this, a mistyped or wrong-format ticker
(e.g. an OTC ADR ticker typed by hand instead of picked from the symbol
search) sat on the watchlist forever, silently re-asked and re-failed on
every future batch refresh for zero chance of success.

**ISIN duplicate detection** (`symbols/duplicates.py`, `providers/wikidata.py::resolve_isin`).
The guardrail above catches a symbol that resolves to *nothing*; it can't
catch a symbol that resolves *fine* but is the same company as something
already tracked under a different ticker (real incident: `ESLOY.US`,
`ESLOF.US`, `EI.SW.US` and `EL.PA.US` were four unrelated ticker strings for
one company, three of them dead ends). Manually-typed watchlist/screener
adds never get an ISIN from anywhere — only a broker CSV import supplies
one — so there was nothing to compare. `resolve_isin` reuses the exact
entity-resolution SPARQL query `resolve_sector` already relies on (same
P414-stock-exchange-required rule, live-verified against real European
holdings — see Decision 3c.1), just reading P946 (ISIN) off the same
candidate instead of/alongside P452 (industry) — `_best_entity` returns
both from one round trip. `check_for_duplicate` (called from both add
endpoints, right before the response is built) stores the optional
`company_name` payload field as `instrument.name` if it didn't have one yet
— this is the *only* thing that ever names a manually-typed instrument;
without it the field silently stayed blank forever even when a name was
typed at add time (real bug: typing "Netflix" resolved the ISIN fine but
never saved the name itself — fixed in Decision 3u.18's addendum). It then
resolves that same name to an ISIN via `resolve_isin`, stores it on the
instrument if it didn't have one yet either (a side effect worth keeping
even absent a duplicate — it also unlocks ISIN-only providers like
Frankfurt later), and looks for another instrument with the same ISIN
that's actually held, watchlisted, or screened elsewhere
(`find_tracked_duplicate` — deliberately excludes orphaned rows nothing
references). A match becomes `duplicate_warning` in the response: a soft,
non-blocking signal — the add still succeeds — since two ISINs for the
same issuer (a different share class, a dual listing) can legitimately
coexist. `company_name` is optional and auto-filled by the
frontend's symbol-search suggestions; a user typing a raw ticker by hand
(the scenario that caused the incident) can still type a name to opt in.

Two gaps in the above, closed by Decision 3u.18: `check_for_duplicate` only
ever runs at *add* time, so a row that predates this feature (or was added
without `company_name`) never gets checked — `PATCH /api/watchlist/{id}` and
the new `PATCH /api/screener/{id}` both now accept an optional
`company_name` too, running the identical check retroactively (this is the
*only* editable field `ScreenerCandidate` has, since it carries nothing else
user-supplied). Second, a company name isn't always something a user has to
type by hand: a broker-imported instrument already carries one, so
`symbols/duplicates.py::backfill_isins` (exposed as
`POST /api/portfolio/backfill-isins`) sweeps every held/watchlisted/screened
instrument that has a `name` but no `isin` yet and resolves it automatically
— no typing needed. Neither closes the gap for an instrument with no `name`
*and* no `company_name` ever supplied (most manually-typed adds): that one
still needs a name typed once, via the PATCH path above. Wikidata's ISIN
property (P946) is also noticeably sparser than P414/P452 — a real company
can legitimately come back with no ISIN (confirmed live: `Celsius Holdings`
has none on Wikidata; re-running the backfill later can still pick up a
transient miss, same "click again" pattern as the price/fundamentals
refresh buttons).

**Position/watchlist signals** (`routers/portfolio.py::_position_signal`,
`scoring/service.py::score_band`). A user request for an "Acheter/Vendre/
Conserver" verdict — twice pushed back on before being built, since a
labeled recommendation is exactly the line this app has otherwise refused
to cross (Decision 0.3, the app's own disclaimer, the earlier rejected
per-position verdict proposal). Built anyway once the user asserted it's
their own private tool and their call to make — but designed to stay
honest about what it is: a **fixed, fully transparent combination of two
indicators the app already shows separately**, never a new analysis and
never phrased as a trade order. `score_band` buckets a composite score into
"high"/"mid"/"low"/"none" (thresholds 66/33, matching the frontend's own
`scoreBand` in `ScoreBadge.tsx` — duplicated deliberately rather than
shared across the Python/TypeScript boundary). `_position_signal` combines
that band with the instrument's asset class's `GET /allocation` state:
`high` + `under` → "reinforce", `low` + `over` → "reduce", either input
missing (`no_target`, or `none` — no computable score) → "not_applicable"
(never defaulted to "hold", which would read as a confident "no action
needed" when the honest answer is "not enough data"). `GET /api/watchlist/
signals` runs the same idea for unheld instruments, combining the score
with distance to the user-set target entry price instead of an allocation
gap — and only ever returns "reinforce"/"hold"/"not_applicable", never
"reduce" (there is nothing held to reduce). These four strings
("reinforce"/"reduce"/"hold"/"not_applicable") are internal signal codes
only — what the UI actually displays is a **fact, not a verb**: caught on
review that "Reinforce"/"Reduce" still read as instructions even without
saying "Buy"/"Sell", since a verb — any verb — implies an action to take.
`SignalBadge` instead renders the two conditions that are true ("High
score · under-allocated", never a bare direction word), "—" for "hold"
(deliberately not a word like "fine" or "OK", which would itself read as a
verdict), and "Insufficient data" for "not_applicable". Both convergence
cases share one "worth a look" tag color (`.tag.unresolved`, amber) rather
than a green/red pair, matching `AllocationTargets.tsx`'s own under/over
convention — the badge flags that two signals line up, not which direction
is "good". The tooltip goes further than before: it now also states
explicitly that the position signal compares *this holding's own score*
against *its entire asset class's* allocation gap — not a full evaluation
of that specific position (a real gap in the first version: a low-scoring
holding in an over-allocated category isn't thereby shown to be the right
one to trim) — and includes the exact point gap (`PositionSignalOut.gap_pct`),
not just the word. See DEVLOG "Decision 3u.19" and its addendum for the
full back-and-forth.

**Attention card.** `GET /api/portfolio/attention` (`routers/portfolio.py::
get_attention`) is the first thing shown on the Portfolio page, above the
detailed tables — a short, ranked list of facts worth a look today, built
entirely by re-reading indicators the app already computes elsewhere:
price status (`_price_status`, reused from the positions table), unresolved
symbols (`_unresolved_instruments`, factored out of `_build_portfolio_out`
so both call sites share one definition of "needs fixing"), and configured
allocation targets (`_current_allocation_values` + `_allocation_row`, same
as `GET /allocation`). No new computation, no new data source — this
endpoint only picks out what deserves attention and ranks it (`missing`
before `warning`). Deliberately excludes `not_priceable` instruments (CFDs
and anything else permanently outside pricing by design — not a problem to
fix) and `no_target` allocation rows (nothing configured means nothing to
flag), and never fabricates a positive item when the list is empty — the
frontend (`AttentionCard.tsx`) shows its own reassuring "nothing to report"
text in that case. See DEVLOG "Decision 3u.25".

**Data health console (v2).** `GET /api/portfolio/data-health`
(`routers/portfolio.py::get_data_health`) is `/attention`'s detailed
counterpart, in Settings' "Intégrité et corrections" group rather than on
Portfolio. Scoped to held positions only (never Watchlist/Screener), same
as v1 (Decision 3u.33/3u.50) — but every instrument gets a row now, not
just the broken ones: `{summary, rows}`, one `DataHealthRowOut` per held
instrument, carrying two independent signals resolved into one overall
severity. See DEVLOG "Decision 3u.58" for the full rationale (v1's
category-only shape is gone, replaced outright — no migration, no new
tables, everything was already computable from existing columns).

- **Valuation signal** (`_valuation_report`): reuses `_price_status`/
  `_declared_valuation_note`/`DECLARED_VALUE_FRESHNESS_DAYS` unchanged.
  `kind` is `market_price` | `declared_value` | `unavailable`;
  `freshness` is `fresh` | `stale` | `unknown`. An unresolved mapping
  (keyed off `_unresolved_instruments()`, not `_price_status()`'s
  broader `"unmapped"`, so it matches exactly what `UnresolvedPanel` can
  correct) is handled before this function runs at all, forcing
  `unavailable`/`action_required`/`unresolved_symbol` directly.
- **Corporate-actions signal** (`_corporate_action_report`): `status` is
  `verified` | `no_events` | `candidate_single_source` |
  `provider_conflict` | `suspect_ticker_reuse` | `incomplete_coverage` |
  `never_checked` | `not_applicable`, built from
  `corporate_actions.service.list_outstanding_candidates`/
  `list_incomplete_instrument_ids` (both read-only, no provider calls) plus
  a `CorporateAction` count grouped by instrument. `not_applicable`
  whenever the valuation signal isn't `market_price` or the instrument has
  no `provider_symbol` — a declared-value or still-unresolved instrument
  never gets a corporate-actions verdict. `confirmed_events`/
  `outstanding_events` are **event** counts, never instrument counts —
  same discipline as `CoverageSummary` (Decision 3u.41).
- **Combining the two** (`_combine_severity`): the overall `severity`
  (`info` | `attention` | `action_required` | `not_applicable`) is
  whichever signal is more severe; a tie is won by the valuation signal
  (the more fundamental one). `reason`/`recommended_action` always travel
  with whichever signal won, so a row's suggested action always matches
  its own severity.
- `DataHealthSummaryOut` rolls up `info_count`/`attention_count`/
  `action_required_count`/`not_applicable_count`; rows are sorted worst
  severity first.

Deliberately not built in this pass: operational buttons wired to each
`recommended_action` (jump to symbol correction, trigger the Alpha
Vantage resume, open the EODHD mini-form) — `recommended_action` is
descriptive text only for now, a scoped follow-up if ever picked up.
Fundamentals-completeness still has no backend definition and is still
excluded, same as v1.

**Personal policy.** `PersonalPolicy`/`PersonalPolicyLimit` (`app/models.py`),
`routers/portfolio.py::get_personal_policy`/`set_personal_policy`/
`create_personal_policy_limit`/`delete_personal_policy_limit`/
`get_personal_policy_gaps`. The user's own, self-declared investment
rules — never inferred, scored, or turned into a "prudent/balanced/
dynamic" profile by the app. Two tables:

- `PersonalPolicy` — a singleton (id=1, same pattern as `AppMetadata`):
  objective (three independent booleans — growth/income/preservation,
  freely combinable — plus a free-text note), horizon (a qualitative
  bucket and/or a target date, independent of each other), liquidity need
  (amount/date/note), risk tolerance (free text, no imposed scale), and a
  loss-capacity percentage. Every field optional and stays optional
  permanently — an incomplete policy is not a form to push to completion.
- `PersonalPolicyLimit` — one row per personal concentration rule:
  `dimension` (`line` | `sector` | `country` | `currency` | `category` |
  `declared_valuation`) + `target` (the specific value being limited,
  e.g. `target="Technology"` for `dimension="sector"`; always `None` for
  `line` — applies uniformly to every position — and
  `declared_valuation` — a fixed pseudo-dimension covering
  Mintos/Amundi-style declared valuations as a whole) + `min_pct`/
  `max_pct` (either or both).

`GET /policy/gaps` is the comparison engine — read-only, no writes.
Reuses (rather than reinvents) the same "group market value by one
`Instrument` attribute" computation `/breakdown` and `/allocation`
already needed: both were unified into a shared
`_positions_figures_and_total`/`_weight_buckets(positions, figures,
attribute)` pair, so all three endpoints now compute from one code path.
Only breaches are returned, same "nothing to report when nothing needs a
look" posture as `/attention`; a `line` breach is reported per breaching
instrument (`target` = its own symbol), every other dimension per
configured limit. Purely descriptive throughout — a gap is a fact about
the user's own stated rule, never a suggestion to buy or sell anything.
See DEVLOG "Decision 3u.59".

Frontend: `PersonalPolicyPanel.tsx`, on the Portfolio page next to
`AllocationTargets` (this is portfolio strategy, not a data-
administration setting) — a consultation view, an edit form (`PUT`
replaces the whole policy in one call), a limits table + add-row form,
and a gaps list shown only once at least one limit is configured.

**Portfolio risk page.** `pages/Risques.tsx`, route `/risk`, a dedicated
top-level page answering a deliberately different question than Personal
Policy: Policy is "did I breach the limit I chose?" (nothing shown
without a configured limit); Risques is "what is my portfolio actually
exposed to?" — unconditional facts, never gated behind a limit. Reunites
two facets that also ship elsewhere in the app's history but are mounted
only here: `PortfolioBreakdown.tsx` (category/currency/country/sector
concentration, `GET /breakdown?by=`) and `FactorExposures.tsx` (Carhart
four-factor exposure, `GET /api/factors`) — moved from the Portfolio page
to this one, not duplicated. Three new panels, all reading from `/risk/*`
(see the endpoint list above): `PositionConcentration.tsx` (top-N
position weights), `Liquidity.tsx` (declared-valuation share by source —
Mintos Core P2P / Amundi ESR — deliberately excluding corporate-action
residuals, which is a `/data-health` concern, not a liquidity one), and
`Drawdown.tsx` (largest historical peak-to-trough decline, from
`compute_max_drawdown` in `prices/history_service.py`, computed over the
same series `/value-history` already returns — no new data source). A
permanent, non-dismissible disclaimer states the Policy-vs-Risk split
directly, so this distinction doesn't get lost or re-duplicated later.
See DEVLOG "Decision 3u.67".

**Decision journal.** `pages/Journal.tsx`, route `/journal` — the user's
own written reasoning behind a trade (or a general/macro note), never
computed or scored, same posture as `WatchlistItem.note`/`PersonalPolicy`.
Tied to an `Instrument` optionally, never to a specific `Lot`/trade fill
— a deliberate choice: this lets an entry be written before any trade
exists (the thesis, arguably the most valuable moment to capture it),
survives lots being closed/sold without going stale, and lets a
general/macro entry stand with no instrument at all. `entry_date` is set
once server-side at creation and never editable afterward — a historical
fact. Editing the original decision (`thesis`/`review_date`) and adding
an `outcome_note` later are two separate `PATCH` endpoints and two
separate UI actions on purpose — conceptually different moments, never
bundled into one form. An entry with a past `review_date` and no
`outcome_note` yet gets a descriptive "due for review" tag — a fact, not
a reminder push (no scheduled notification exists). The thesis field is
this app's first `<textarea>` — every other free-text field elsewhere is
single-line — deliberate, since a thesis is genuinely multi-sentence by
nature and is the one thing this feature exists to capture. See DEVLOG
"Decision 3u.68".

**Getting-started checklist.** `GET /api/portfolio/onboarding`
(`routers/portfolio.py::get_onboarding_status`) backs a dismissible
"getting started" card (`OnboardingChecklist.tsx`), shown first on the
Portfolio page — above `AttentionCard` — until every step is done or the
user dismisses it. Each of the six fields (`imported`, `prices_refreshed`,
`unresolved_resolved`, `fundamentals_fetched`, `allocation_target_set`,
`watchlist_started`) is a plain existence check against a table the app
already maintains (`ImportBatch`, `AppMetadata.last_price_refresh_time`,
`_unresolved_instruments`, `Fundamental`, `AllocationTarget`,
`WatchlistItem`) — no new tracking, no derived state, and no timestamp of
when a step was completed. Dismissal is `localStorage`-only (this is a
single-user local app, same convention as `i18n`'s locale and
`useHiddenColumns`): once dismissed the checklist never reappears, even if
a later step becomes undone again (e.g. a new unresolved symbol after a
fresh import). The frontend recomputes "is everything done" on every load
rather than the backend baking in a single boolean, so a step regressing
(a newly unresolved symbol) is visible again on its own line without
needing the whole card un-dismissed. See DEVLOG "Decision 3u.26".

**Score summary wording — a second, narrow exception to fact-not-verdict.**
`ScoreBadge.tsx` adds a chevron (▾/▴) after the composite number and a
"click to see the detail" line in its tooltip, purely a visibility fix —
the badge was always clickable, but nothing before this hinted at it.
`ScoreDetailRow.tsx` now opens with a plain-language sentence ("Score
77/100 : indicateurs globalement favorables selon les données
disponibles") derived from `scoreBand(composite)`, plus two lists —
"Points forts" / "Points à contrôler" — built by applying that same
66/33 threshold to each individual metric's own score (not the
composite), flattened across all four pillars. The band adjective
("favorable"/"mitigé"/"défavorable") is mildly interpretive, not a bare
fact — flagged to the user before building (a purely-factual count
alternative was offered and declined) — so treat this as a second,
narrowly-scoped exception to the fact-not-verdict rule below, alongside
Discovery's buy/hold/sell verdict. See DEVLOG "Decision 3u.27" for why
this one sentence is exempted and nothing else is.

**Dividends by year and account.** `dividends/service.py` answers the
question the Transactions page's own lifetime summary couldn't: what was
received and withheld, split by account (PEA and a brokerage account have
completely different French tax treatment), calendar year (what a
declaration needs), **and currency** — `dividend_summary` never sums
across currencies (a real bug until DEVLOG "Decision 3u.70": a single
account can hold instruments in several currencies, e.g. this app's own
"My Trades" account pays dividends in EUR, USD, CHF, GBP and SEK).
Descriptive only — no tax liability is ever computed.

The hard part is reconciliation, not aggregation: a dividend and its
withholding tax are two independent `Transaction` rows (`DIVIDEND` and
`TAX`) linked by nothing but usually sharing an account, an instrument and
a timestamp. Verified against real data before writing any matching logic:
paired rows share the exact same `executed_at` down to the microsecond in
the overwhelming majority of cases, but not always (one real pair was 1ms
apart) — so `_reconcile_instrument_account_group` matches by nearest
timestamp within a 3-day window, scoped to one (account, instrument) group
at a time, greedily claiming the closest still-unclaimed tax row per
dividend in chronological order (handles multiple same-day pairs for one
instrument correctly — seen in real data: partial lots paying separately).
A `DIVIDEND`/`TAX` row with no instrument at all (a manual entry with no
symbol) is never matched, rather than risk pairing it with an unrelated
row on account and date alone.

Absence of a withholding is not an anomaly — most dividends legitimately
carry none (0% treaty rate, PEA wrapper), reported `no_withholding`, never
flagged as a problem. Only a `TAX` row that can't be attributed to any
dividend is a genuine anomaly (`unmatched_tax`).

`TxType.TAX` is not all withholding tax, found live while verifying this
feature against the real portfolio: the importer's `classify_cash_type`
buckets French financial-transaction tax ("Tax IFTT") and UK stamp duty on
*trades* into the same `TxType.TAX` as dividend withholding — all three
match its "tax" keyword family. `_is_dividend_withholding` re-reads each
row's own `raw["Type"]` to exclude the two trade taxes, defaulting to
*true* (include) when `raw` is missing entirely — a manually-entered `TAX`
row has no `Type` label to check and no other signal besides the user's
own choice to type it as a withholding correction. This same helper is now
reused by `routers/transactions.py::_compute_summary`, whose own lifetime
"Retenue à la source" total had been silently inflated by trade taxes
since before this feature existed — fixed so the two views never disagree.

**`Transaction.account` is now a real column** (DEVLOG "Decision 3u.28"),
reversing "Decision 3d.1"'s original design: `account` used to be
recovered from `raw` at serve time specifically *because* Alembic didn't
exist yet, and altering a table already holding real rows without a
migration tool was the exact kind of change this project avoided. Alembic
has existed since Decision 3u.7, so that constraint no longer holds — this
migration is a routine `add_column`. Rows imported before the column existed
are backfilled via `POST /api/transactions/backfill-accounts`, which
recovers the value from each row's own `raw` JSON — the same
normalised-alias matching the importer itself uses, applied backwards.

**Annual tax-year reconciliation.** `app/tax/service.py` — explicitly a
**reconciliation aid, not a tax calculator**: it never applies a rate and
never computes a final liability, only sums what was already imported.
Requested with that exact framing after the user accepted the risk of a
prior, narrower "calculate my tax" ask and then rescoped it themselves
before any code was written. See DEVLOG "Decision 3u.60".

`compute_tax_year_summary(db, tax_year)` groups every dated `Transaction`
by account for the requested calendar year, classifies each account's
wrapper via `_classify_envelope` (a heuristic on the account name — `pea`,
`p2p`, `employee_savings`, defaulting to `cto` — since no structured
wrapper-type field exists on `Transaction` yet), and sums by `TxType`:
dividends/withholding are **delegated to `dividends/service.py::dividend_summary`
rather than recomputed**, specifically to avoid silently reintroducing the
FTT/stamp-duty-vs-withholding bug that module's own docstring documents
having found live; interest, realized gains, realized losses (kept
separate, never netted into one "gain"), fees, deposits and withdrawals
are direct sums by type. `OTHER`-typed rows (Amundi's own annual-statement
aggregate lines) are surfaced verbatim as `other_flows`, never bucketed
into a guessed category and never counted as taxable activity.

A real, load-bearing legal fact drove the design, found by checking real
data before writing anything: a PEA/PEG/PERCO wrapper with no `WITHDRAWAL`
transaction this year has **zero** taxable activity regardless of the
wrapper's age — gains and dividends stay untaxed while held. `_summarize_envelope`
reflects this directly rather than approximating it: a PEA/employee-savings
envelope always gets a `taxPrep.noWithdrawalDetected` or
`taxPrep.withdrawalDetected` note (the latter never resolves the
consequence, which depends on rules — plan age, exit conditions — this
service does not model); the generic `taxPrep.notApplicable` note is
suppressed whenever one of those more specific notes already explains the
same conclusion, to avoid two notes repeating one fact.

A real `SELL` transaction with no matching `CLOSED_TRADE` row (the Mintos
ETF sub-account: raw buys/sells with no broker-computed realized figure)
is never estimated — flagged `taxPrep.unmatchedSales` instead, needing a
validated FIFO lot-matching engine this app does not have yet (explicitly
deferred, gated on validating its output against real Mintos tax reports
across several years before showing a single derived figure, not on the
code merely running).

**Backup and restore.** `backup/service.py` — a plain timestamped copy of
the live SQLite file into `backups/` (gitignored, same sensitivity as
`data/`), and nothing more sophisticated: no incremental snapshots, no
compression. `.env`/API keys are never touched, by construction — only the
`.db` file is ever read or written. The 10 most recent backups are kept;
older ones are pruned on each new backup.

**Hermes export (`backend/scripts/export_for_hermes.py`).** Read-only
integration for Hermes, a separate personal AI agent running on the same
host: a `*/15 * * * *` cron on the host calls every relevant existing
endpoint (never raw SQL — the export's numbers can never drift from what
the app itself shows) and writes one consolidated JSON snapshot to
`~/Hermes/portfolio-data/portfolio_export.json`, which Hermes' own
container reads via a read-only bind mount. Runs on the host, never
inside a container: the backend's own middleware only accepts loopback
connections (`app/main.py`), so a containerized caller could never reach
it directly anyway.

Bundles: `portfolio`, `breakdown_by` (category/currency/country/sector),
`allocation`, `attention`, `data_health`, `lots_by_instrument`,
`dividends_summary`, `tax_summaries_by_year`, and — since Decision
3u.65 — `personal_policy`/`personal_policy_limits`/`personal_policy_gaps`.
The policy fields exist specifically so an agent reasoning about this
portfolio stays inside the investor's *own* stated rules rather than
inventing independent recommendations — `personal_policy_limits` is the
full configured set (satisfied or not), deliberately not just
`/policy/gaps`'s breaches-only view, since "within bounds" and "no rule
configured" need to read differently to a consumer that never sees the
UI. This app has, and is intended to have, no trade-execution
capability — Hermes reads facts; nothing here ever writes back.

Restore refuses a schema-version mismatch rather than attempting to
reconcile one: `alembic_version` is compared byte-for-byte between the
backup and the live database, and anything but an exact match is rejected
(`409`) rather than silently loading an older schema underneath newer
application code. No "upgrade the backup first" attempt is made — that
would mean running migrations against a file the user hasn't committed to
using. `engine.dispose()` runs before the file copy: SQLite holds its file
lock through the connection, so a stale pooled connection would otherwise
keep pointing at content that's about to disappear; the next request opens
a fresh one against the restored file. The filename arrives from an API
request, so it's resolved strictly inside `BACKUP_DIR` first (rejects
`../` traversal, an absolute path, or a symlink escaping the directory).

Confirmed with the user before building: backups live in a fixed local
folder (not a per-backup file-picker — this app has no native file dialog
to offer one), and restoring requires typing the exact filename in the UI
before the button enables, rather than a bare confirm click, since it
overwrites the live database with no undo.

**Stock splits.** `corporate_actions/service.py` handles splits and reverse
splits — the next roadmap item after dividends and backup, chosen
deliberately before the per-position detail panel, since that panel would
otherwise surface numbers a split could make wrong (quantity, cost basis,
chart, return). Audited before writing any code: XTB never reports a split
in any raw transaction row, and no price provider can be trusted to
deliver split-adjusted history uniformly — the same provider (twelvedata)
served already-adjusted history for two real splits (NVDA 10:1, GOOGL
20:1) but raw, unadjusted history for a third (APLD's real 1-for-6 reverse
split) — same source, opposite behavior depending on the instrument.

Same principle as `Transaction`/`Lot`: `PriceBar` and `Lot` are never
mutated. A `CorporateAction` row drives correction entirely at read time,
via two pure functions in `corporate_actions/service.py`:
`quantity_factor_from(actions, reference_date)` restates a lot's real
share count (keyed by its `opened_at`) to today's post-split basis;
`price_factor_from(actions, bar_date)` does the inverse for a raw close,
but only for splits whose stored price history was confirmed `RAW` by
`detect_price_history_status` — never for `ALREADY_ADJUSTED` ones, which
is what prevents double-adjusting a series a provider already fixed (the
exact NVDA/GOOGL-vs-APLD inconsistency the audit found). Detection
compares the last cached close before `effective_date` to the first
on/after it against the split's own ratio; missing bars on either side
reports `NOT_APPLICABLE` rather than a guessed status.

Both factors are threaded into every consumer that replays `Lot`/`PriceBar`
history: the value-history chart and its benchmark overlay
(`prices/history_service.py`), the dividend-yield lot-replay and technical
metrics (`scoring/service.py`), Carhart factor exposure
(`factors/service.py`), the price-prediction features
(`prediction/features.py`), and the price chart plus all three sparkline
endpoints — so the chart the user actually looks at never shows a fake
cliff. `Position`-based live totals are untouched: confirmed in the audit
that a broker re-import already self-corrects live quantity/avg-price
after a real split, since `Position` is a wholesale-replaced snapshot, not
a `Lot` replay.

Splits are found automatically via FMP's `/stable/splits` endpoint
(`providers/fmp.py::fetch_splits`) plus manual entry for anything FMP
doesn't cover. Originally Yahoo's undocumented chart endpoint
(`providers/yahoo.py::fetch_splits`, still present but no longer called
by detection) — swapped out after Yahoo's real-portfolio scan proved to
rate-limit inconsistently (a raw single-symbol check could return `200`
while the actual multi-instrument scan still hit `429` on the very first
instrument), making the feature impossible to validate live. See DEVLOG
"Decision 3u.34" for the full swap, including a live-confirmed nuance:
FMP's free plan gates individual smaller-cap US symbols outright (`402
PlanLimited`, confirmed against APLD), not just non-US markets — this
lands in `DetectionSummary.failed` exactly like any other non-retryable
per-instrument error, never stopping the rest of the scan (only
`RateLimited` does that). Deliberately single-source for the bulk scan:
no automatic fallback to EODHD or Yahoo when FMP can't answer for a
symbol, and no cross-source conflict detection — both left as separate
future chantiers rather than built pre-emptively.

For the real, live-verified case FMP structurally can't answer (`402
PlanLimited` on APLD, a legitimate free-plan gate rather than a transient
error), `POST /detect-one` (`corporate_actions/service.py::detect_one`)
adds a narrow, manual escape hatch instead: the user picks one instrument
from `CorporateActionsPanel`'s existing dropdown and checks it against
EODHD's `/api/splits` (`providers/eodhd.py::fetch_splits`) specifically.
This is not a contradiction of "no automatic fallback" above — it is
never triggered by the bulk scan, never iterates over the `failed` list,
and never runs against more than one instrument per click; the user
remains the one deciding a symbol is worth EODHD's separate quota. Status
is reported via an explicit enum (`created`, `already_known`, `no_events`,
`not_supported`, `plan_limited`, `rate_limited`, `failed`) so a genuine
"EODHD returned nothing" is never rendered the same way as "EODHD
couldn't be reached" — the same failure/no-event discipline the
`complete` fix above enforces for the bulk scan. See DEVLOG "Decision
3u.35". (In passing, this chantier also fixed a real gap dating back to
the FMP swap: `corporateActions.source.fmp` was missing from all three
i18n locales, so every FMP-sourced action rendered a raw key string in
the UI instead of a label.)

Batch call sites load every
relevant instrument's actions in one query (`load_actions_by_instrument`)
rather than one query per lookup, matching this codebase's existing
batch-first convention. Scope deliberately narrow, per the user's own
list: split and reverse split only — mergers, spin-offs, rights issues,
stock dividends, and ticker changes are out of scope for now.

**Multi-source instrument gathering, deduplicated by id.** Both refresh
endpoints — `POST /api/prices/refresh` and `POST /api/scoring/fundamentals/refresh`
— build their working set the same way: start from the "core" query (held
instruments, or a targeted retry), then extend it with each of the benchmark
instrument, `_watchlist_instruments(db)`, and `_screener_instruments(db)` in
turn, skipping anything whose id is already in the set. Adding a fourth
"instruments that need this batch operation too" source later means adding
one more `instruments.extend(x for x in ... if x.id not in seen)` line, not
redesigning the query.

**Per-instrument, on-request, N-day-TTL enrichment.** `analysis/news_service.py::get_news`
and `analysis/commentary_service.py::get_commentary` share one shape: `cached
= db.get(Model, instrument.id)`, a date-granularity freshness check (`cached.fetched_at.date()
>= today - timedelta(days=N)` — never a full-datetime comparison: a `DateTime`
column round-trips through SQLite as naive while `datetime.now(UTC)` is
aware, so comparing them directly raises `TypeError`; `.date()` on both sides
sidesteps it, same idiom `fundamentals/service.py::_already_fresh_today` and
`prices/service.py::_asked_today` already use), then fetch-and-persist on a
miss. Unlike the batch-refresh patterns above, there's no progress bar and no
lock: each call is one instrument, triggered by expanding one table row, not
a background sweep over the whole portfolio. Reach for this whenever a new
feature needs "fetch one external thing about one instrument occasionally,
cache it for a while" — the shape is identical whether the source is free or
paid; only the TTL and whether a shared quota needs recording differ.

**Batch-first querying.** One query per data source across all relevant
instruments, grouped into a dict in memory — never one query per instrument in
a loop. Every service module (`scoring/service.py`, `prices/history_service.py`,
`routers/watchlist.py`) follows this.

**Shared frontend components** (all in `components/`, all exported for reuse):
`ColumnPicker` + `hooks/useHiddenColumns` (per-table column visibility,
localStorage-backed); `ScoreBreakdown` (the per-pillar/per-metric
breakdown content itself, topped by a plain-language summary sentence +
Points forts/Points à contrôler lists — see "Score summary wording"
below) with `ScoreDetailRow` as a thin `<tr><td colSpan><ScoreBreakdown
.../></td></tr>` wrapper around it; `Sparkline`; `ProgressBar`;
`SortableHeader<K>` (generic over the caller's own sort-key union — don't
widen a table's own `sortValue`/`SortKey` to share it, those stay
table-specific); `ScoreBadge` (+ its `scoreBand` threshold helper);
`PriceStatusBadge`; `InsightsSection` (the news/sentiment + on-request
paid AI commentary content itself) with `InsightsBadge` + `InsightsDetailRow`
as its thin-wrapper pair, same split as `ScoreBreakdown`/`ScoreDetailRow`.
`WatchlistTable` and `ScreenerTable` use both pairs exactly as before —
each with its own independent `expandedId`/`expandedInsightsId` toggle
state, so Score and Insights can be open at once. `PositionsTable` is the
one exception: it embeds `ScoreBreakdown`/`InsightsSection` directly
inside its own consolidated `PositionDetailRow` instead of using the `Row`
wrappers — see "Per-position detail panel" below. `AlertsBell` (top-nav
badge, polls `GET /api/watchlist` every 60s, counts items with
`distance_to_target_pct <= 0` — no backend endpoint of its own, reuses data
the Watchlist page already computes).

**Per-position detail panel** (`PositionDetailRow.tsx`, `PositionsTable.tsx`
only — DEVLOG "Decision 3u.31"). Before this, understanding one held
position meant reading its table row plus two separate expandable
sub-rows (score, insights) plus manually filtering the Transactions and
Dividends pages. `PositionsTable` now has a single `expandedDetailId`
state; its `ScoreBadge`/`InsightsBadge` both toggle that one id instead of
independent state, and `PositionDetailRow` renders one consolidated panel
with six vertical sections — Résumé, Allocation, Analyse (embedding
`ScoreBreakdown`/`InsightsSection` directly), Revenus, Historique (lots,
instrument-scoped transactions, corporate actions), Qualité des données —
not tabs, so nothing is hidden behind secondary navigation. Deliberately
no price chart in v1: raw-vs-adjusted, default period, and benchmark
choice each need their own scoping conversation, and the existing 90-day
row sparkline covers v1's need. On first expand it fetches lots, dividend
detail, corporate actions, and instrument-scoped transactions in one
`Promise.all`, guarded by the same `fetchedForRef` pattern
`InsightsSection` already used to survive React 18 StrictMode's
double-invoke without double-spending a request. An empty subsection
(e.g. no corporate actions ever recorded for that instrument) is omitted
entirely rather than rendered as an empty table.

**Tracking vs. administration split** (`Portfolio.tsx` / `Settings.tsx` —
DEVLOG "Decision 3u.32"). `Portfolio.tsx` holds only reading/tracking
content (KPIs, allocation, positions, the per-position detail panel);
data-maintenance controls (`ImportPanel`, `FundamentalsRefreshButton`,
`ManualPositionForm`, `UnresolvedPanel`) live in `Settings.tsx`, grouped
into four labeled `<section className="settings-group" id="...">` blocks
("Données du portefeuille", "Intégrité et corrections", "Sauvegarde",
"Sources de données"). One exception: `RefreshPanel` stays on
`Portfolio.tsx` — its live-quote phase hands back the recomputed
`Portfolio` only in the direct HTTP response (never persisted, per
`prices/quote_service.py`'s docstring), so it only works wired to the page
whose state it replaces in place; moving it would silently strand that
result nowhere. `Settings.tsx` fetches `GET /api/portfolio` once on its
own (`loadUnresolved`) purely to give `UnresolvedPanel` its `instruments`
prop, now that it's no longer a child of `Portfolio.tsx`'s own fetch — an
accepted, cache-only duplicate call rather than sharing state across
pages for one field. New hash-anchor scrolling (`useLocation().hash` +
`scrollIntoView`, gated on the page's own loading state so it re-fires
once the target section actually exists in the DOM) lets other pages link
straight to one group — `Portfolio.tsx`'s "Gérer les données" line and
`AttentionCard`'s `unresolved_instruments` item both use it.

**Manual-add-entity forms.** `ManualPositionForm.tsx`, `ManualTransactionForm.tsx`,
`AddToWatchlistForm.tsx`, `AddToScreenerForm.tsx` all share one shape: collapsed card with an "Add"
button → expands to a form with a 350ms-debounced company-name autocomplete
(`api.searchSymbols`, skips search once the input contains a "." — that's a
ticker, not a name) → POST → collapse + `onCreated()` callback to reload the
parent's data.

**Inline row editing.** `Transactions.tsx`, `WatchlistTable.tsx` and
`AllocationTargets.tsx` all use the same shape for editing an existing row
in place: an `editingId`/`editDraft` state pair, an "Edit" button that swaps
to Save/Cancel and turns the row's editable cells into inputs, `saveEdit(id)`
calling the resource's `PUT`/`PATCH` and patching that one row (or
reloading). `Transactions.tsx` owns this state at the page level; the other
two keep it local to the component itself, matching where they already keep
their own `expandedId`-style state — page vs. component ownership follows
whichever the rest of that file already does, not a hard rule.

**i18n**: reuse an existing key when the wording is generic enough (e.g.
`prices.progress`'s "{done} / {total} instruments processed" was reused
verbatim for the fundamentals progress bar) rather than adding a near-duplicate
key per feature.

**Structurally non-priceable instruments** (`Instrument.not_priceable_reason`).
One field gates an instrument out of *every* price-related code path at
once: `prices/service.py`/`history_service.py` never fetch for it,
`routers/portfolio.py`'s price resolution and `_unresolved_instruments()`
both exclude it, `scoring`/`fundamentals` already gate on `category`
separately so a new category is excluded there for free, and the
frontend's `MappingCell`/`PriceStatusBadge` both check the same field
before offering a "fix the mapping" affordance. Adding a new
non-priceable category (done twice: `"cfd"`/`"corporate_action"` at
first, `"p2p_aggregate"`/`"employee_savings_fund"` in Decision 3u.39) is
just: set the reason at write time, add a
`positionDetail.notPriceableReasonValue.{reason}` translation (falls
back to a generic "unknown reason" sentence otherwise, never the raw
code), and — the two-time gotcha — grep every place that currently reads
`mapping_status`/`category` directly instead of `not_priceable_reason`,
since a new reason that doesn't fit an existing category exclusion will
silently fall through as "needs fixing" rather than "not priceable."

**A value with no honest cost basis** (Mintos Core P2P aggregate,
Decision 3u.39). When a broker discloses a current value but no
attributable per-unit cost (auto-reinvestment mixes principal and
interest with no way to separate them), don't guess — `avg_price` still
holds a schema-required placeholder, but `routers/portfolio.py::
_current_position_figures()` short-circuits *before* the generic
broker-value fallback for that category, always returning `pl`/`pl_pct`/
`price` as `None` regardless of what the placeholder contains. The
frontend renders the placeholder-holding field as "non applicable," not
as a number — a third, distinct state from "non calculable" (`—`, data
missing but the concept applies) and from a real number, so the user
never mistakes an artefact for a computed fact.

**Declared valuation freshness** (Mintos Core P2P, Amundi ESR funds,
Decision 3u.50). A value with no computable P&L (see above) is still
either a live market quote or a value the source itself *declared* as of
some date — the two are not equally fresh by nature, and conflating them
made a portfolio total that mixed today's XTB quotes with a Mintos
statement from a year ago look uniformly current. `Position.value_as_of`
(set at import time — the winning snapshot's own date, never `opened_at`,
which answers a different question, "since held") plus
`routers/portfolio.py::_declared_valuation_note` (keyed by
`Instrument.not_priceable_reason`, with a per-source cadence in
`DECLARED_VALUE_FRESHNESS_DAYS`) produce a `ValuationNote`
(`app/messages.py`) exposed as `PositionOut.valuation_note` — 'fresh' or
'stale', never a reason to exclude the value itself from any total
(`_aggregate` is untouched by this decision). Surfaced in four places:
the `PriceStatusBadge` 🗓 icon (overrides the generic 🚫 for these two
categories specifically), the value cell's tooltip in `PositionsTable`,
`PortfolioTotals.has_stale_declared_valuations` (a portfolio-total
warning banner, computed in `_build_portfolio_out` from the same notes,
not from `_aggregate`/`_compute_totals`), and `AccountTotals.valuation_note`
(Bug 3u.51 — independent of `AccountTotals.performance_note`: an account
can have a P&L caveat, a declared-value caveat, both, or neither; the
"By account" table footnote list shows one bullet per note per account).

## External data sources (`backend/app/providers/`)

One file per source behind a common interface (`base.py`): `yahoo`, `fmp`,
`twelvedata`, `boursorama`, `frankfurt` (prices); `edgar` (US fundamentals, no
key, 0.5s throttle); `esef` (EU fundamentals, no key, 0.3s throttle, ~7,300-entity
index cached per-process); `wikidata` (sector/industry lookup); plus several
configured-but-currently-idle sources (`barchart`, `eoddata`,
`eodhd`, `finviz`, `intrinio`, `marketstack`, `polygon`, `tiingo`) wired through
`registry.py`'s provider chains. `fx.py` is the FX-rate source.

`alpha_vantage` is no longer idle: alongside `fetch_daily` (prices) it now
also has `fetch_news_sentiment` (`routers/insights.py`, `analysis/news_service.py`)
— both share the same `Throttle` instance (`registry.py::get_alpha_vantage_provider`
pulls the exact chain instance rather than constructing a fresh one), so a
price call and a news call together never exceed the real 5-req/min limit.

`perplexity.py` is a standalone client (not `PriceProvider`-shaped, no chain
membership, no shared throttle — every call is one explicit user action,
never a batch). Paid; guardrails and reasoning in DEVLOG "Decision 0.3".
