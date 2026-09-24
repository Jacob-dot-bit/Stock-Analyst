# Development log

A record of the steps, decisions, bugs and outcomes of the Stock Analyst project.

**What this document is for.** The [README](README.md) describes the *current* state of the
project — what it does and how to use it. This log describes *how it got there*: what was
tried, what broke, why, and what we concluded. It exists so the same mistake is not made
twice, and so a decision already settled is not silently reopened.

## Conventions

One entry per notable event, most recent at the bottom of its section.

- **Decision** — context, the choice made, the reason, the consequences. A reversed
  decision is never deleted: it is ~~struck through~~ with a pointer to the one replacing
  it.
- **Bug** — observed symptom, actual cause, fix, verification. The cause matters more than
  the fix: it is the cause that prevents a recurrence.
- **Step** — what was delivered and how it was verified.

Record a bug **at the moment it is understood**, not afterwards: the cause is quickly
forgotten.

**No personal data in the repository.** Account numbers, portfolio amounts and export
files are kept out of it. Numeric examples are fictional but internally consistent, and
flagged as such. Test fixtures use invented account numbers.

---

# Phase 0 — Scoping (2026-08-11)

## Step — Feasibility research

Initial goal: connect the application to the XTB API to track the portfolio automatically.

## Decision 0.1 — Drop the XTB API, build around file imports

**Context.** Research established that **the XTB API no longer exists**. It was shut down
on **14 March 2025**.

Sources:
- XTB help centre: "*API access is no longer available. The service was discontinued on
  March 14, 2025.*"
  ([xtb.com](https://www.xtb.com/int/help-center/our-platforms-6-4/does-xtb-offer-investment-automation-tools-4))
- The documentation domain `developers.xstore.pro` no longer resolves in DNS.
- Community wrappers are archived
  ([`pawelkn/xapi-python`](https://github.com/pawelkn/xapi-python), archived 2025-08-26).
- XTB offers **no replacement**: no API, no automated trading, no copy trading.

**Decision.** The application is fed by **xStation file exports** and designed to be
**broker-agnostic**.

**Alternative rejected.** Scraping the web platform with the account credentials: almost
certainly against the terms of service, risks the account being blocked, and would require
storing financial credentials. Rejected without hesitation.

**Consequences.**
- No automatic synchronisation: the user drops in a file.
- No credentials are requested or stored — zero risk surface on that front.
- The tool survives a change of broker.
- Parsing becomes the project's main point of fragility → hence the effort spent on
  robustness and tests in phase 1.

## Decision 0.2 — Stack and scope

| Topic | Choice | Reason |
|---|---|---|
| Backend | FastAPI + SQLite | Python for the analysis (pandas); SQLite is plenty for a local single-user app |
| Frontend | React + Vite + TypeScript | An interactive multi-page dashboard was requested |
| Refresh | On demand | No background job to maintain |
| Markets | Worldwide | The portfolio spans US and Europe |
| Sources | Free only | A constraint set up front |
| Qualitative synthesis | Perplexity API | The only accepted expense |

## Decision 0.3 — Guardrails on Perplexity usage

**Context.** Sonar pricing: token cost **plus** a fee of **$5–14 per 1000 requests**. Mass
screening across a few thousand instruments would cost tens of euros per run.

**Decision.** Perplexity is reserved for qualitative analysis of **one instrument at a
time, on explicit request**, with caching (7-day TTL). Never mass screening. The LLM
**does not contribute to the score**: it comments on it.

**Consequence.** The "hidden gems" screener must be designed in two stages — local
filtering over cached data, then network enrichment of the top N only.

---

# Phase 1 — Foundation, XTB import, Portfolio page (2026-08-11)

## Step 1.1 — Skeleton and data model

Delivered: backend/frontend tree, SQLAlchemy models, export parser, symbol mapping layer,
Portfolio page, 81 tests.

## Decision 1.1 — Keep the source row of every import

Every transaction and position stores its originating file row as JSON (the `raw` field).

**Reason.** Allows recomputing or correcting later without asking the user for the file
again. Storage cost is negligible at this scale.

**Outcome.** Paid off in phase 1b: the FX-rate columns, initially unused, were already in
the database.

## Decision 1.2 — Missing data is never zero

A position without a valuation is **excluded from the totals** and flagged, never counted
as zero.

**Reason.** A wrong total that looks correct is more dangerous than one that is explicitly
partial. The same principle will apply to scoring: a pillar without data is dropped and the
weights renormalised.

## Bug 1.1 — `parse_number("1 234,56 EUR")` returned `None`

**Symptom.** A test failed on an amount followed by its currency code.

**Cause.** The cleanup filtered character by character with `[^\d,.\-+eE]`, keeping `e`/`E`
for scientific notation. The "E" of "EUR" survived, producing `"1234.56E"`, which is
invalid.

**Fix.** Extract the first number with a regular expression (`_NUMBER_TOKEN`) instead of
filtering. Scientific notation was explicitly dropped: absent from broker exports, it made
trailing-currency detection ambiguous.

**Unplanned benefit.** Switching to extraction made accounting notation
`(1 234,56)` → `-1234.56` free to support.

## Bug 1.2 — FastAPI refused to start on the `DELETE` route

**Symptom.** `AssertionError: Status code 204 must not have a response body` at module
load.

**Cause.** A `status_code=204` without an explicit `response_class`: FastAPI tries to
serialise a response body, which a 204 forbids.

**Fix.** `response_class=Response` and returning `Response(status_code=204)`.

## Bug 1.3 — Missing tables in the API tests

**Symptom.** `no such table: instruments`, even though `create_all` had run.

**Cause.** `create_engine("sqlite://")` opens a **separate in-memory database per
connection**. Tables created on one connection are invisible to the thread serving HTTP
requests. The service tests passed by luck (same thread, same connection reused), which
masked the problem.

**Fix.** `poolclass=StaticPool` on the test engines.

---

# Phase 2 — Multi-source providers + Settings UI (2026-08-14)

## Step 2.1 — Add 12+ price data providers + Settings page

**Delivered:** 
- 12 new providers (Polygon, Alpha Vantage, IEX, Tiingo, Barchart, Intrinio, EODHD, Stooq, WTD, Quandl, Eoddata, Finviz)
- API keys config in Settings page
- Backend router `/api/settings/providers` and `/api/settings/api-keys`
- Frontend Settings page with i18n (en/fr/pl)
- **Total of 17 price sources** for maximum redundancy

**Verification:** Backend serves prices from multiple sources in fallback order (Yahoo → Polygon → Alpha Vantage → ...). If one rate-limits, automatically tries the next.

## Decision 2.7 — Store API keys in local .env, not database

**Context.** Sensitive financial credentials need secure storage.

**Choice.** Keys are written to `.env` file (project root), never sent to any service. Users can also configure them directly in the Settings UI.

**Reason.** Keeps secrets local, leverages existing Pydantic config loader, survives restarts.

**Consequence.** Requires `python-dotenv` package for writing `.env`. Settings are cached in-memory with `@lru_cache`; `cache_clear()` reloads on API key change.

---

# Phase 2b — UI/UX Enhancements (2026-08-14+)

## Step 2b.1 — Add data refresh timestamp + portfolio weights

**Delivered (2026-08-14):**
1. **Date/time of last refresh** displayed on Portfolio page (`AppMetadata` table,
   single-row, updated on every `/api/prices/refresh` call).
2. **Portfolio weight %** column in holdings table: `weight_percent = market_value /
   total_market_value * 100`, computed server-side in `get_portfolio()`. Positions
   excluded from totals (no valuation) get no weight rather than a misleading 0%.
   Highlighted in orange/red above 15% (concentration risk) with a tooltip.

**Verification.** Manually tested end-to-end: refreshed prices, confirmed the
timestamp updates and the weight column reflects each holding's real share of the
portfolio (a position previously showing "+300%" with no context now reads
"+300%, 0.4% of portfolio" next to one at "+20%, 28% of portfolio" — the intended
fix for a reported UX gap).

**Still to deliver (Phase A, remaining):**
- Sector/asset class distribution pie chart (A4)
- Improved error handling with "Retry failed" button (A5)

**Why.** Current UI shows holdings but lacked:
- When data was last updated (users didn't know if prices were stale) — **fixed**
- Which holdings matter most (AMD +300% on 0.1% of portfolio vs +20% on 30%) — **fixed**
- Visual feedback during long refreshes (feels stuck) — **fixed** (below)
- Portfolio structure at a glance (how many sectors? concentration risk?) — still open

## Step 2b.2 — Real progress bar during price refresh (2026-08-14)

**Delivered.** `GET /api/prices/refresh/status`, polled every 800ms by the frontend
while `POST /api/prices/refresh` is in flight. Shows `{done}/{total} instruments`
plus the symbol currently being fetched, with a fill bar.

**Decision.** No background task or second DB session was needed. FastAPI serves
each sync `def` endpoint on its own thread (`run_in_threadpool`), so while the POST
handler blocks on `_refresh_many_locked`, a concurrent GET to `/refresh/status` from
the same browser tab is handled on a different thread and reads the same in-process
`RefreshProgress` snapshot (guarded by a small lock, copied with `dataclasses.replace`
on read). This is much simpler than spawning a thread with its own `SessionLocal()`
session and was sufficient for a local single-user app.

**Consistency with a prior decision.** `RefreshPanel.tsx` carried a comment reasoning
that "a fake progress bar would be dishonest," which is why the UI previously showed
nothing during the (30-60s) blocking call. That reasoning still holds — what changed
is that the total-and-done counts are now real, tracked instrument-by-instrument
inside `_refresh_many_locked` (`app/prices/service.py`), not simulated. The bar never
advances faster than actual work completes.

**Verification.** Manually tested: triggered a refresh, watched the bar advance with
the current symbol shown, confirmed it reaches 100% exactly when the POST resolves
and the final summary notice replaces it.

## Bug 2b.4 — Portfolio total didn't match the real, current broker value

**Symptom.** User reported the app showing [montant A] while their broker platform showed
[montant B] right after clicking "Refresh prices" — a small (~1.7%) gap that refreshing
repeatedly did not close.

**Cause.** Not a bug in the strict sense, but a genuine architecture gap the user
correctly caught: `POST /api/prices/refresh` only ever writes to the `PriceBar` table
(daily history used for the trend sparkline). It never touches `Position.market_price`
or `Position.broker_market_value` — those fields are written **once, at import time**
(`ingest/service.py:226`) straight from the broker's XTB export, and never recomputed.
So the portfolio totals are a snapshot as of the last import, not a live figure, and no
amount of refreshing can close a gap that only a new import closes. This was already a
documented decision (README: "no FX conversion... totals reconcile to the cent against
the summary rows inside the XTB file itself" — precisely to keep totals trustworthy),
but the UI never told the user that, so "Refresh prices" read as if it should fix this.

**Fix (2026-08-14).** UI-only, no computation changed:
- `prices.subtitle` (RefreshPanel) now states outright that refreshing only updates the
  trend charts, not the totals.
- `portfolio.lastRefresh` reworded from "Updated on {date}" (implied: everything) to
  "Price history refreshed on {date} (trend charts only)".
- New `portfolio.valuesAsOf` notice, shown right above the totals, stating the amounts
  are as of the last import and pointing at a new import as the way to bring them
  current.

**Deferred.** A live-estimated total (`quantity × latest fetched close`) was considered
and explicitly **not** built now: this app's price bars are stored in the instrument's
own currency, and the app has no FX-rate source, so a live estimate for non-EUR
holdings would be silently wrong in exactly the way the existing "no computed totals"
decision was meant to prevent. Revisiting this is Phase B scope and needs an FX-rate
source decided first, not a quick patch.

## Step 2b.3 — Price status badges + targeted retry (A5, 2026-08-14)

**Delivered.**
- `InstrumentOut` now exposes `not_priceable_reason` and a server-computed
  `price_status` (`fresh` | `stale` | `error` | `not_priceable` | `unmapped`),
  derived in `_price_status()` (`routers/portfolio.py`) purely from fields the
  import/refresh pipelines already write (`verified_at`, `prices_checked_at`,
  `not_priceable_reason`, `mapping_status`) — no new column, no new write path.
  Rendered as a small colored badge before the ticker in `PositionsTable`, with a
  tooltip naming the provider and verification date for fresh/stale rows.
- `POST /api/prices/refresh` accepts an optional `symbols` query param to scope a
  run to specific broker symbols. `RefreshPanel` uses it for a "Retry failed"
  button that appears when a run reports rate-limited/not-found/failed/
  still-unavailable outcomes, and calls the retry with `force=true` — required
  because those symbols already have `prices_checked_at` set today, so without
  `force` the daily gate would just report "already checked" again.

**Scoped out deliberately.** "Ignore this instrument" / "mark as manual" from the
original ask were not built: `not_priceable_reason` auto-detection
(`ingest/service.py:detect_not_priceable`) already correctly flags corporate-action
artefacts like `US592CVR0133` without user action, which covered the concrete case
that prompted the request. A manual override endpoint can be added if a real case
turns up that the heuristic misses.

## Step 2b.4 — Portfolio breakdown chart (A4, 2026-08-14)

**Delivered.** `GET /api/portfolio/breakdown?by=category|currency|country` and a
`PortfolioBreakdown` component: a horizontal stacked bar + legend, switchable
across the three dimensions.

**Decision — sector was not used.** `Instrument.sector` exists as a column but is
never populated anywhere in the codebase (no import, no provider writes it) —
verified by grep before building anything on it. A sector chart would have been
100% "Unknown". Category/currency/country were used instead: all three are
broker-supplied at import time already, so the chart needed no new integration.
Sector remains a real gap (would need a Finnhub company-profile provider, not yet
built) — noted for a future phase, not silently dropped.

**Decision — stacked bar, not a pie/donut.** Per the dataviz skill's
choosing-a-form guidance, "part-to-whole" maps to a stacked bar (reads magnitude
more precisely than angle), not a pie. Used the skill's validated 8-color
categorical palette (`--series-1..8` in `index.css`, light and dark values),
re-verified with `scripts/validate_palette.js` rather than assumed from the docs
(passes both modes; 3 light-mode slots need "relief," satisfied by the legend's
always-visible text labels). More than 8 categories fold into an "Other" slice
rather than generating a 9th hue.

**Verification.** Manually tested: switched dimensions, confirmed segment widths
sum to the full bar and match the legend percentages, confirmed the "Other" fold
triggers past 8 slices.

## Step 2b.5 — Live-estimated portfolio value with FX conversion (Phase B, 2026-08-14)

**Context.** Direct follow-up to Bug 2b.4: the user wanted the gap between the
two computed totals actually closed, not just explained. Doing that correctly requires
converting each holding's price into the base currency — the thing the codebase
had explicitly avoided until now for lack of a reliable FX source (see README
"No FX conversion is applied").

**Currency semantics, verified before writing any conversion code** (this is
exactly the kind of mistake the existing code was careful about, so it seemed
worth confirming rather than assuming): `Position.avg_price` and
`Position.market_price` are in the **instrument's own currency** (e.g. USD for
`AAPL.US`) — confirmed via the comment at `xtb_import.py:572` and cross-checked
against `PositionsTable.tsx`, which suffixes `avg_price` with `position.currency`.
`broker_market_value` / `broker_net_pl` / `broker_purchase_value` are in the
**account currency** instead — a different currency for a non-EUR-denominated
holding in a EUR account, which is precisely why the two must never be mixed
casually.

**Delivered.**
- **FX source: Frankfurter.app** (`providers/fx.py`), ECB daily reference rates,
  free and keyless — matches the project's "free sources only" constraint.
- **Daily cache**: new `FxRate` table (`currency`, `base_currency`, `rate_date`,
  `rate`), read/written by `prices/fx_service.get_rate()` — same caching shape as
  `PriceBar`, and for the same reason: Frankfurter publishes one rate per day, so
  asking twice buys nothing.
- **`GET /api/portfolio/live-estimate`**: for each position, `quantity ×
  latest cached PriceBar.close × today's FX rate`. Never calls a price provider
  itself — only reuses what `PriceBar` already has plus Frankfurter for FX — so
  checking this can never trigger a price-provider rate limit.
- **Scope exclusions, on purpose**: CFDs and not-priceable instruments are left
  out entirely, not counted as "excluded" — a CFD's quantity is a contract count,
  not a share count, so `quantity × price` would not mean what it means for a
  stock, and inventing a number there would be worse than omitting it. Positions
  missing a cached price, a known currency, or an FX rate land in
  `excluded_count` instead of being silently treated as zero.
- **`LiveEstimatePanel`** (frontend): a visually secondary card — never styled to
  compete with the primary (official) totals — showing the estimated total, the
  delta versus the last-import total, and the caveat text always visible (not
  behind a tooltip): *"Estimate only... not the same computation as your
  broker's figures above, and not investment advice."*

**Decision — kept fully separate from the official totals, never merged.**
`PortfolioOut.totals` is untouched by this feature. The two numbers can and will
disagree, and that disagreement is the point: it is the size of "how stale is my
last import," which the user can now actually see instead of just being told
about.

**Verification.** Backend: 287 existing tests still pass unchanged (new table,
no schema migration needed since `create_all` only adds missing tables — no
Alembic in this project). Manually confirmed the estimate panel appears after a
price refresh has populated `PriceBar`, shows a plausible delta, and degrades to
"not enough cached data" before any refresh has run.

## Bug 2b.5 — Live estimate came out 57% too low, 23/37 positions "could not be estimated"

**Symptom.** First real-world run of the live estimate: a much lower figure shown
against the real official total — a huge gap, not a plausible one-day market
move — with 23 of 37 positions flagged as missing a price or currency.

**Cause.** `providers/fx.py` pointed at `https://api.frankfurter.app/latest`.
That host now 301-redirects to `https://api.frankfurter.dev/v1/latest` — the
service relocated at some point after this integration was written. `httpx.get()`
does not follow redirects by default, so every FX lookup got back a 301, which
`fetch_rate()` correctly treats as failure (`status_code != 200` →
`FxUnavailable`) — but *silently*, from the caller's point of view: `get_rate()`
returns `None` on any `FxUnavailable`, by design, so a bad host and a currency
the ECB simply doesn't publish look identical from the estimate endpoint. Every
EUR-denominated holding was unaffected (short-circuited before any network call:
`from_currency == to_currency → 1.0`), which is exactly why the failure hit
selectively — every non-EUR position (a large chunk of a portfolio with US
holdings) rather than all of them, which read as plausible enough not to be
instantly obviously "everything is broken."

**Fix.** Point `FRANKFURTER_URL` at the current host
(`api.frankfurter.dev/v1/latest`). Verified live: `fetch_rate("USD", "EUR")` now
returns `0.86453` instead of raising.

**Lesson for later free-tier integrations.** A silent `None`-on-failure return is
the right design for "don't let one bad FX pair wreck the whole estimate," but it
means an infrastructure change on the provider's side (a host move) is
indistinguishable from an expected gap (unsupported currency) unless something
logs the *reason*, not just the outcome. Worth revisiting if another provider
integration goes quiet in the same way: check for a redirect before assuming the
data itself is the problem.

## Step 2b.6 — Manual "Recalculate" for the live estimate (2026-08-14)

**Context.** After the Frankfurter fix, the estimate landed within ~0.5% of the
real total, down from 57%. User asked how often it refreshes.
Answer at the time: only on page load and after another action re-triggers
`load()` (import, price refresh, position add/delete) — no background timer.

**Decision.** Added an on-demand "Recalculate" button rather than a polling
timer. Reasoning: the estimate only ever reads what is already cached (a
`PriceBar` close plus, at most, one Frankfurter call for a currency not yet
cached today) — it never calls a price provider, so there is no rate-limit risk
in letting the user trigger it as often as they like. A timer would poll
Frankfurter on a schedule for no benefit, since the ECB rate does not change
intraday and the cached close only changes after a price refresh anyway.

**Implementation.** `Portfolio.tsx` split the estimate fetch out of `load()`
into its own `loadLiveEstimate()`, passed to `LiveEstimatePanel` as
`onRecompute`; the panel manages its own `busy` state for the button.

**On the residual ~0.5% gap.** Expected, not a bug: the estimate uses the last
*cached* close (not live intraday) and the ECB's once-a-day fixing (not a live
spot rate) — both inherent to using only free, non-real-time sources. Recorded
here so it is not re-investigated as a bug later.

## Step 2b.7 — Budgeted "fetch fresh prices" for the live estimate (2026-08-14)

**Context.** Follow-up to 2b.6: user asked whether the live estimate could
refresh more often using other free sources, not just once a day. Live-tested
Yahoo's chart endpoint directly during this conversation and got back **HTTP
429** — a real, present rate-limit, not a hypothetical one. Combined with the
existing 5s-per-request Yahoo throttle, fetching a live quote for all 37 held
instruments would take **~185 seconds** for that source alone. A "just fetch it
faster" ask ran into a real physical constraint, not a missing feature — flagged
this explicitly rather than silently building something that would feel broken.

**Decision.** Budgeted round, same shape as the existing price-history refresh:
covers as many instruments as a time budget (`settings.refresh_budget_seconds`)
allows, degrades gracefully to the cached close for the rest. Chosen over (a)
loosening the once-a-day cap on the main refresh — multiplies quota spend
without user control — or (b) a full uninterrupted ~3 minute wait — poor UX for
a button that used to be instant.

**Delivered.**
- **`ProviderChain.fetch_quote(ref)`** (`providers/base.py`): mirrors
  `fetch_daily`'s fallback-and-cooldown logic, but only tries providers that
  implement an optional `fetch_quote` method — most of the 17 providers don't,
  and that's fine, they're simply skipped for this purpose rather than treated
  as failures.
- **`YahooProvider.fetch_quote`**: reuses the *same* throttled `_get()` as the
  historical fetch (one rate-limit bucket, not two), reading
  `meta.regularMarketPrice` from the existing chart response — no new endpoint,
  since Yahoo's chart payload already carries a near-real-time price alongside
  the historical series.
- **`prices/quote_service.py`**: budgeted loop + `QuoteProgress` tracker,
  structurally identical to `RefreshProgress` in `service.py` — same
  process-wide lock (one round at a time), same "polled from a separate request
  while the triggering call is still blocked" trick that made A2's progress bar
  work without a background thread.
- **`POST /api/portfolio/live-estimate/refresh`** + **`GET
  .../refresh/status`**: the budgeted round, then recompute the estimate,
  preferring a live quote per instrument where the round reached it and falling
  back to the cached close otherwise (`_compute_live_estimate` refactored to
  take an optional `live_quotes` override — the plain `GET /live-estimate`
  still never calls a price provider and stays free to call on every page load).
- **Frontend**: `LiveEstimatePanel` now has two distinct buttons — "Recalculer"
  (cache-only, instant) and "Prix frais" (budgeted, shows the same progress bar
  component pattern as the main refresh). Each `LiveEstimateItem` now carries
  `price_source` ('live' | 'cached') and `quote_provider`, surfaced as "N
  positions priced with a fresh live quote."

**Deliberately not built:** per-provider quote implementations beyond Yahoo.
Adding `fetch_quote` to another provider (Twelve Data's `/price`, IEX's
`/quote`) is a small, isolated addition when needed — the chain already skips
providers without it, so nothing here needs to change to extend coverage later.

## Bug 2b.6 — "Fetch fresh prices" silently did nothing, no error, no explanation

**Symptom.** Clicking the new button produced an identical estimate, with no
error and no "N positions priced live" message either — indistinguishable from
the button not working at all.

**Cause, found by testing directly rather than guessing.**
`YahooProvider.fetch_quote(ref)` raised `RateLimited` when called directly
(confirmed live: `yahoo.fetch_quote(ref)` → `RateLimited: yahoo is throttling
requests`) — Yahoo is currently the *only* provider with quote support, so one
throttled source meant zero live quotes for the whole round. That part is
expected, budgeted-degrade-to-cache behaviour, not a bug.

**The actual bug:** nothing surfaced *why*. `ProviderChain.fetch_quote()`
catches `RateLimited`/`ProviderError`/`Exception` per provider and moves on —
correct for resilience, but the frontend then had no signal to distinguish
"the round ran and genuinely found nothing" from "the request itself failed."
`LiveEstimatePanel.handleFreshRecompute` had a `try/finally` with **no
`catch`**, so a POST-endpoint error would have thrown silently into an
unhandled promise rejection — a real gap, not yet hit in practice here but
exactly the kind of thing that reads as "broken" with zero diagnostic trail.

**Fix.**
- Added the missing `catch` in `handleFreshRecompute`, surfaced as a `notice
  error` — matches the pattern already used in `RefreshPanel`.
- Added a distinct, non-error "none reached" note when the round completed
  normally but found zero live quotes despite having candidates: *"No fresh
  quote could be fetched this time (the provider that supports it — currently
  Yahoo only — was throttled or unreachable). The cached price was used
  instead; nothing is missing."* — makes the degrade-to-cache outcome visible
  instead of looking identical to "button did nothing."

**Not fixed (accepted for now):** the underlying single-point-of-failure —
only Yahoo implements `fetch_quote`, so if it is throttled, the "fresh prices"
button always falls back to cache, however honestly that is now reported. This
was already the known, documented tradeoff at 2b.7 ("deliberately not built:
per-provider quote implementations beyond Yahoo"); worth revisiting if this
proves to be a frequent, not occasional, occurrence in practice.

## Step 2b.8 — Every enabled provider became quote-capable, not just Yahoo (2026-08-14)

**Context.** User's reaction to Bug 2b.6, fairly: with 17 sources already
integrated, "only Yahoo supports quotes" was a self-inflicted limit, not a real
one. Reconsidered the "deliberately not built" call from 2b.7 in that light.

**Decision — reuse `fetch_daily` as the fallback quote mechanism, rather than
writing a dedicated `fetch_quote` per provider.** `ProviderChain.fetch_quote`
now tries a provider's dedicated `fetch_quote` if it has one (Yahoo does), and
for every other enabled provider, calls its existing `fetch_daily` over a short
5-day window and takes the most recent close — the same endpoint each provider
already implements, already throttled and cooldown-tracked, just asked for a
few days instead of a full history. Zero new per-provider code, and every
provider that becomes enabled later (any of the 12 from phase 2, once a key is
added in Settings) is automatically quote-capable too.

**Verified live**, with Yahoo still in cooldown from the earlier testing in
this session: `chain.fetch_quote(InstrumentRef(provider_symbol="AAPL", ...))` →
`(305.26, 'twelvedata')` — fell through Yahoo (cooldown), Boursorama and
Frankfurt (can't serve a US symbol), landed on Twelve Data, which was already
configured with a key from earlier setup. Confirms the redundancy is real, not
theoretical: of the 17 integrated sources, 8 are currently enabled (the ones
with either no key requirement or a key already set — `yahoo`, `boursorama`,
`frankfurt`, `twelvedata`, `fmp`, `stooq`, `eoddata`, `finviz`); the other 9
activate automatically the moment a key is added via Settings, no code change
needed.

**Also fixed:** the "no fresh quote" explanatory message and the code comment
both said "currently Yahoo only," which stopped being true with this change —
reworded to "every configured source that could serve these instruments."

## Step 2b.9 — Signup links on the Settings page (2026-08-14)

**Context.** After seeing quote coverage improve via multi-source fallback, user
asked to add each keyed provider's free-signup link directly on the Settings
page, rather than having to look them up elsewhere.

**Delivered.** `ProviderStatus` gained `signup_url`, populated in
`routers/settings.py` from the same URLs already documented in `.env.example`
(Polygon, Alpha Vantage, Twelve Data, FMP, IEX, Tiingo, Barchart, Intrinio,
EODHD, Stooq, WTD, Quandl, Eoddata). Omitted for `yahoo`/`boursorama`/`frankfurt`
— nothing to sign up for. `Settings.tsx` renders it as a small "Get a free key ↗"
link next to each provider's status badge, opening in a new tab.

**Also fixed in passing:** `Settings.tsx`'s inline styles referenced CSS custom
properties that don't exist in this app's theme (`--color-border`,
`--color-bg-secondary`, `--color-success`, `--color-text` — no such variables
in `index.css`, which uses `--border`, `--surface-alt`, `--positive`, `--text`).
The provider status badges were silently rendering with no color or border
since the page shipped. Corrected to the real variable names.

## Bug 2b.7 — Three dead API-key fields, one silently-broken one

**Symptom.** User asked why some providers show an API key input and others
don't, and on inspection found the inconsistency wasn't only about "needs a key
vs doesn't" — some fields were there but pointless.

**Cause, found by reading the actual provider code rather than the settings
list.** `StooqProvider.__init__`, `EoddataProvider.__init__` and
`FinvizProvider.__init__` all take **no** `api_key` parameter — none of the
three ever reads `stooq_api_key` / `eoddata_api_key` / `finviz_api_key`. Those
three config fields, their `.env.example` entries, and their Settings UI input
boxes were all present but connected to nothing: typing a key into any of them
and saving would produce a "success" message while changing no actual
behaviour. Leftover from writing the 12 phase-2 providers in a batch without
checking, per provider, whether the key was actually wired to anything.

**Separately, a real (if not yet user-hit) bug:** `IexProvider.name = "iex"`,
but the settings field is `iex_cloud_api_key` / `iex_cloud` throughout
`routers/settings.py`. `Settings.tsx` keys its per-provider input by
`provider.name`, so a pasted IEX key would have been sent to the backend as
`{"iex": "..."}` — a field `UpdateApiKeysRequest` doesn't have, silently
dropped by Pydantic's default `extra="ignore"`. The save would report success
and the key would never reach `.env`. Caught while auditing the other three,
not from a user report — worth remembering that `provider.name` and the
settings field name need to match exactly, since nothing currently enforces
that at the type level.

**Fix.**
- Removed `stooq_api_key`, `eoddata_api_key`, `finviz_api_key` from
  `config.py` (fields, placeholder validator, `*_enabled` properties),
  `.env.example`, and every dict in `routers/settings.py`.
- Renamed `IexProvider.name` to `"iex_cloud"`, matching the settings field
  everywhere else.
- `ProviderStatus` gained `has_api_key: bool`, computed from membership in the
  same `signup_urls` dict that already had to stay in sync with
  `UpdateApiKeysRequest` — one source of truth instead of three parallel lists
  that could drift. `Settings.tsx` now renders the key input only when
  `has_api_key` is true; keyless providers show "No key needed — works out of
  the box." instead of a dead input field.

**Lesson.** When a batch of similar integrations gets `key: str | None`
scaffolding by default, verify per-item that the key is actually consumed
before shipping a UI for it — three providers went through backend, `.env.example`,
and frontend review without anyone (including this session) noticing they
never read the value.

## Step 2b.10 — Settings page only lists what it can actually change (2026-08-14)

**Context.** Follow-up question from the same conversation: even after 2.4's
fix, the page still listed all 17 providers, six of them (Yahoo, Boursorama,
Frankfurt, Stooq, Eoddata, Finviz) with no key field — `is_enabled()` is
unconditionally `True` for all six, so their "Enabled" badge was never
actionable either. User asked, reasonably: what is the point of a row with
nothing to interact with, on a page whose entire purpose is configuring keys.

**Decision.** Filter the list to `has_api_key` providers only. The six keyless
ones collapsed into a single line: *"Also active, no setup needed: yahoo,
boursorama, frankfurt, stooq, eoddata, finviz."* — visible (so the "why do I
already have coverage here" question is still answerable) without a full card
per provider implying a control that isn't there.

**Not done:** an enable/disable toggle for keyless providers, which would have
been the alternative way to make their row "actionable." Rejected: these
providers are deliberately always-on baseline coverage (Yahoo especially — the
first link in the fallback chain), and a toggle to turn off a free, keyless
source has no real use case that a key-focused Settings page needs to serve.

## Bug 2b.8 — Full signup-link audit: 2 dead providers, 1 broken URL, 2 stale links

**Context.** Triggered by the user hitting one bad link (Polygon → redirected
to `massive.com`). Rather than patch that single link, live-tested every
signup URL and, for the ones that looked suspicious, the actual API endpoint
each provider's code calls — since a marketing-site rename (harmless) and an
API shutdown (fatal) can look identical from a signup link alone.

**Findings, all verified live, not assumed:**

| Provider | Marketing site | Actual API (`api.*`) | Verdict |
|---|---|---|---|
| Polygon | 301 → `massive.com` | `api.polygon.io` → 401 (alive) | Rebrand only — link fixed |
| Barchart | 200, unchanged | `ondemand.barchart.com` → 301 → `www.barchartondemand.com` | **Same bug as Frankfurter** (2b's Bug): `httpx.get` doesn't follow redirects, so every call silently failed on "invalid JSON response" instead of a clear "moved" |
| EODHD | 404 on old knowledgebase path | `eodhd.com/api/eod/...` → 401 (alive) | Doc path moved to `/register` — link fixed, API untouched |
| **IEX Cloud** | connection refused (`000`) | `cloud.iexapis.com` → **TLS handshake reset by peer** | **Service shut down.** Not a redirect, not a rename — nothing answers on port 443 at all |
| **World Trading Data** | 301 → `marketstack.com` | `api.worldtradingdata.com` → 200, body is a JSON message: *"This API endpoint is deprecated and now has been shut down... update your integration to use the new marketstack API endpoint"* | **Explicitly, officially dead.** Marketstack is a different product with a different API shape — not a URL swap |
| Quandl (WIKI dataset) | 200 | `quandl.com/api/v3/datasets/WIKI/...` → Incapsula bot-wall (403) | The free WIKI dataset was discontinued in 2018, well before this session; Nasdaq Data Link (Quandl's successor at `data.nasdaq.com`) may have *other* free datasets, but not this one |
| Tiingo, Intrinio, Alpha Vantage, FMP, Twelve Data | — | all returned correct "invalid test key" errors or (Alpha Vantage) real data | Confirmed alive, no action needed |

**Fix.**
- **Removed IEX Cloud, World Trading Data, and Quandl entirely** —
  `providers/iex.py`, `wtd.py`, `quandl.py` deleted; every reference in
  `registry.py`, `config.py` (fields, validator, `*_enabled` properties),
  `.env.example`, and `routers/settings.py` (descriptions, signup_urls,
  `ApiKeysStatus`, `UpdateApiKeysRequest`, the `.env` write mapping) removed
  along with them. A "fix the link" patch was rejected for these three: WTD's
  replacement is a different API entirely, and Quandl's replacement dataset
  (if any, on Nasdaq Data Link) hasn't been identified or built — shipping a
  provider that always fails is worse than not shipping it, exactly the
  Stooq/Eoddata/Finviz lesson from Bug 2b.7 but one level more serious (there,
  the key was unused; here, the whole service is gone).
- **Fixed Barchart's URL** to `www.barchartondemand.com`, with a code comment
  cross-referencing the Frankfurter fix so the same redirect-not-followed
  pattern is recognisable next time instead of re-diagnosed from scratch.
- **Fixed EODHD's and Polygon's signup links.**
- **Provider count: 17 → 14.** The chain is smaller but every remaining member
  has been confirmed to actually answer.

**Lesson, extending Bug 2b.6/2.4's theme.** Three separate integration
problems (Frankfurter, Polygon, Barchart) all had the same root shape: a
service moved and the old host still resolves and often still answers *something*
(a redirect, a marketing page), which reads as "probably fine" until the
literal response body is inspected. The reliable test is not "does the URL
load" but "does the specific endpoint the code calls return the data shape the
code expects" — worth making a standing habit for any future provider work
rather than a one-off audit.

## Step 2b.11 — Marketstack added as World Trading Data's replacement (Bug 2.6, 2026-08-14)

**Context.** Direct pushback on Bug 2b.8's call to remove World Trading Data
outright: WTD's shutdown message didn't just say "dead," it named a specific
successor (marketstack.com) — a "moved," not a "gone," and the fix for a move
is redirecting the integration, not deleting it. Fair correction; verified
before building anything, same discipline as the rest of this session.

**Verified live before writing code.** `api.marketstack.com/v1/eod` with a bad
key returned a proper `invalid_access_key` error (401) — the service is real
and alive, not another dead end. Free tier confirmed from the pricing page:
**100 requests per month** (not per day) — roughly two orders of magnitude
thinner than every other free tier in this chain (Twelve Data: 800/day,
Tiingo: 500/day).

**Delivered.** `providers/marketstack.py`, following the same `PriceProvider`
pattern as the other 15. Registered **14th of 15** in `registry.py` — after
every more generous source, before only Finviz's fragile scraping — so it is
reached mainly when nothing else covered a given instrument, keeping monthly
usage low without needing a special-cased throttle. `MARKETSTACK_API_KEY`
added to `config.py`, `.env.example`, and `routers/settings.py` (all four
dicts, matching Bug 2b.7's one-key-one-place-to-configure-it discipline).

**Distinction from Bug 2b.8's IEX Cloud / Quandl calls, worth keeping straight:**
IEX Cloud gave no migration message at all — just a refused TLS handshake,
nothing to redirect to. Quandl's WIKI endpoint gave a bot-detection wall, not a
"moved to X" message either. World Trading Data was different in kind: its own
API told us exactly where it went. "The vendor says it moved" and "the vendor
is unreachable" call for different responses, and conflating the two the first
time around is what prompted this correction.

**Provider count: 14 → 15.**

## Follow-up — re-checked IEX Cloud and Quandl for the same "moved, not dead" pattern

**Context.** Fair question after Marketstack landed: were IEX Cloud and Quandl
dismissed too quickly, the same mistake WTD almost suffered?

**IEX Cloud — confirmed, more conclusively than before.**
`www.iexcloud.io` (the marketing site, not just the API) now serves a Namecheap
**parked-domain page**: *"has been recently registered with namecheap.com."*
The company does not control its own domain anymore. No successor message
exists anywhere to find, unlike WTD's explicit pointer — this is the "genuinely
gone" case, not the "moved" case.

**Quandl — re-investigated, conclusion unchanged but for a clearer reason.**
Nasdaq Data Link (Quandl's parent) is a live, real company — unlike IEX Cloud.
But: the `WIKI` and `EOD` stock-price datasets both still sit behind the same
Incapsula bot-wall under the new domain. A different dataset,
`SHARADAR/SEP`, *did* respond — with a fake `api_key=test` — but returned only
data frozen at end-2018 (`lastupdated: 2026-08-10` in the metadata, yet no row
newer than 2018-12-31), which reads as a paid dataset's free preview sample,
not current free data. No dataset found with WTD/Marketstack's clarity ("100
free requests/month, current data"). Left unintegrated — a real key might
unlock `SHARADAR/SEP` fully, but that is an assumption this session isn't
willing to build a provider on without verifying it first.

## Step 2b.12 — "Test key" button per provider (2026-08-14)

**Context.** After a session spent finding dead/moved providers by manual curl
investigation, the natural next ask: let the user do that same check from the
UI, for their own key, without needing a terminal.

**Delivered.**
- **`POST /api/settings/verify-key`** (`routers/settings.py`): instantiates
  the real provider class with the given key and calls its actual
  `fetch_daily` against a fixed probe (`AAPL.US`, last 5 days) — the same code
  path a real refresh would use, not a separate "ping" endpoint that could
  drift from what actually gets called in practice. Works on either a
  not-yet-saved key (typed but not submitted) or the currently-saved one
  (`api_key` omitted in the request → reads from `get_settings()` server-side,
  so the frontend never needs to know the real value to test it).
- Response distinguishes three cases, not just pass/fail: a clean success: (`"received N day(s) of data"`);
  rate-limited (`RateLimited` caught separately — a provider that throttles
  us is proof the key itself was accepted, so this reports `valid: true` with
  an explanatory note, not a failure); and a rejected key (`ProviderError` →
  `valid: false` with the provider's own error text, e.g. "HTTP 401").
- **Frontend**: a "Test" button beside each key field; result line below it
  (✓ green / ✗ red) using the same `--positive`/`--negative` tokens as the
  rest of the app. Editing a field after testing clears its stale result —
  otherwise a "✓ valid" could sit next to a since-changed, unverified value.

**Reused rather than duplicated:** the verification call goes through each
provider's real `fetch_daily`, the same method the price refresh uses — no
separate lightweight "ping" implementation to keep in sync with the real
fetch logic as providers change.

## Bug 2b.9 — Saved key never took effect until backend restart

**Symptom.** User tested an Alpha Vantage key (not yet saved) with the new
"Test" button, got a valid result, clicked Save, and the provider still
showed "Disabled" afterward.

**Cause.** `get_provider_chain()` (`providers/registry.py`) is `@lru_cache`d —
by design, so per-provider throttles stay process-wide (see its own docstring).
`update_api_keys()` (`routers/settings.py`) cleared `get_settings`'s cache
after writing `.env`, which correctly makes `get_settings()` return the new
key — but never cleared `get_provider_chain`'s cache too. The chain object,
once built, keeps the provider instances it was built with **forever** —
`AlphaVantageProvider(api_key=None)` from whenever `get_provider_chain()` first
ran, permanently, regardless of how many times settings are saved afterward.
Only a full backend restart (which resets both caches) ever picked up a
freshly-saved key.

**Fix.** `update_api_keys()` now calls `get_provider_chain.cache_clear()`
alongside `get_settings.cache_clear()` — two independent caches, both need
invalidating.

**Why the "Test" button caught this immediately.** `verify-key` builds its own
throwaway provider instance per call (`provider_cls(api_key=key)`), bypassing
`get_provider_chain()` entirely — so a key correctly tested "valid" even while
the *real* provider chain was still stuck on the stale, keyless instance. The
save button and the provider list use the cached chain; the test button
doesn't. That gap between the two is exactly what surfaced this.

## Bug 2b.10 — Alpha Vantage's daily-quota response misdiagnosed as "symbol not found"

**Symptom.** Testing an Alpha Vantage key against `AAPL` — about as
unambiguous a symbol as exists — returned "valid" but with *"the provider
answered; it just doesn't have the test symbol"*, which does not make sense
for AAPL specifically.

**Cause.** `AlphaVantageProvider.fetch_daily` only recognised two error
shapes: `"Error Message"` (bad symbol) and `"Note"` (the older per-minute
throttle message). Alpha Vantage's free tier now caps at **25 requests/day**
and reports that limit via a **third**, newer key — `"Information"` — which
the code never checked. A daily-quota response carries no `"Time Series
(Daily)"` key either, so it fell through to the empty-data check and was
reported as `SymbolNotFound`, which the "Test" endpoint then (correctly, given
what it was told) summarised as "valid key, symbol just not covered" — a
technically-consistent but misleading conclusion built on a wrong diagnosis
upstream.

**Fix.** Added a check for `data.get("Information")`, raising `RateLimited`
with the message text — the daily-quota case is now reported the same way the
per-minute one already was.

**Why this shipped unnoticed.** No existing test exercised Alpha Vantage's
daily-quota response shape (network tests are skipped by default; see
README), and the "Test" button is the first thing in this project that calls
a provider with a real key on demand, outside the once-a-day-per-instrument
refresh cadence — which is exactly what surfaced it.

## Bug 2b.11 — Tiingo's free tier dropped historical date ranges entirely

**Symptom.** User tested a Tiingo key, got `HTTP 400`. The bare status code
gave no clue why — same problem as the earlier Barchart/Frankfurter
investigations, so the fix started the same way: read the actual response
body, not just the code.

**Diagnosis, done incrementally as the real message surfaced:**
1. First fix: `TiingoProvider` was raising `ProviderUnavailable(f"HTTP
   {status}")` on any ≥400, discarding the body entirely. Added
   `_error_detail()` to include it.
2. That surfaced a **second, unrelated bug**: `_error_detail()` assumed the
   error body was always a JSON object (`.get("detail", ...)`) and crashed
   with `'list' object has no attribute 'get'` the moment Tiingo's body turned
   out to be a JSON array. Fixed by checking `isinstance(body, dict)` before
   calling `.get()` — an error-reporting path must never itself throw, or it
   silently replaces the real error with a worse one.
3. With both fixed, the actual message came through: *"This experimental
   feature has been officially been deprecated. The bulk endpoint with
   startDate and endDate specified for historical data is no longer
   supported as of 2024-07-29. You may use the bulk endpoint as long as
   startDate and endDate are not specified (i.e. the latest date's
   values)."* — Tiingo's own official docs (fetched mid-session) still
   describe the deprecated `startDate`/`endDate` usage with no mention of this
   change; the only way to find it was hitting the live API and reading what
   it actually says, the same lesson as Frankfurter/Polygon/Barchart earlier
   in this session, now four-for-four.

**Fix.** `TiingoProvider.fetch_daily` now fails immediately with a clear
message and **no HTTP call** — Tiingo can no longer serve a date range at
all, so there is nothing to gain from asking, and failing without a request
costs none of the 500/day quota. A new `TiingoProvider.fetch_quote` — the
*same* endpoint, just without `startDate`/`endDate` — gives the latest day's
price, which is exactly what the live-estimate "fresh prices" feature (2b.7)
needs. Tiingo moved from "historical provider" to "quote provider" without
losing its place in either chain.

**`verify-key` also needed a fix.** It always called `fetch_daily` to test a
key, which — for Tiingo now — fails unconditionally regardless of key
validity, so it would report "Key rejected" for even a perfectly good key.
Added `QUOTE_ONLY_PROVIDERS = {"tiingo"}` so the test endpoint calls
`fetch_quote` instead for providers where that is the only thing that
actually works.

**Provider count unaffected (still 15)** — Tiingo stays registered, its role
just narrowed from two capabilities to one.

## Bug 2b.12 — Polygon: legacy host, and a parsing bug never exercised in this session

**Context.** User shared Massive's official `llms.txt`-linked API docs
(`massive.com/docs/rest/llms.txt`), suggested specifically to keep an
AI agent from hallucinating endpoint details — fetched them rather than
continuing to rely on the `api.polygon.io` host verified back at Bug 2b.8.

**Finding 1 — the rebrand runs deeper than the marketing site.** Massive's
docs document `api.massive.com` as the base host and never mention
`api.polygon.io` at all. Live-tested both: today, both answer identically
(same `/v2/aggs/ticker/.../range/.../...` path, same `apiKey` param, same
error shape for a bad key). `api.polygon.io` isn't *broken* — but it is
undocumented and unsupported going forward, exactly the position
Frankfurter's old host was in right before it started 301-redirecting.
Switched `PolygonProvider` to `api.massive.com` pre-emptively rather than
waiting for the same failure mode to repeat a third time.

**Finding 2 — an unrelated, more serious bug this surfaced while re-reading
the code against the docs' sample response.** `PolygonProvider` parsed each
bar's timestamp as `date.fromisoformat(result["t"][:10])`, treating `t` as an
ISO date string. Massive's documented sample response shows `t` as an
**integer Unix millisecond timestamp** (e.g. `1577941200000`) — `[:10]` on an
int raises `TypeError` immediately. Every test of this provider in the
session so far (Bug 2b.8's host check, the "Test key" button work) only ever
exercised the auth-rejection path (a bad key returns 401 before parsing ever
runs), so this would have crashed on the **first real, successful** fetch —
never caught because nothing in this session had a valid Polygon key to
actually reach that code path until now. Fixed: `datetime.fromtimestamp(t /
1000, tz=UTC).date()`, verified against the docs' own example
(`1577941200000` → `2020-01-02`, matches).

**Lesson, sharpened once more.** Three of this session's provider bugs now
came from *never having exercised the success path* — a wrong host or a
placeholder key reliably tests the failure branches, but says nothing about
whether the code past that point is correct. Worth remembering next time a
new provider integration "passes" testing: rejection-path testing is not
success-path testing.

**Not adopted:** Massive's Python SDK and MCP server (also linked in the
same message). The hand-rolled `httpx` call, once fixed, is consistent with
how all 14 other providers in this codebase are built — swapping just this
one to a vendor SDK would add a second, inconsistent integration pattern for
no capability this app needs that raw HTTP doesn't already provide.

## Bug 2b.13 — Five providers sent an empty ticker to every US-listing request

**Symptom.** Testing the (now host/parsing-fixed) Polygon key still failed,
now with a body-surfaced message: `"Ticker was incorrectly formatted."` — a
completely different class of problem from the host/parsing bugs just fixed.

**Diagnosis.** `PolygonProvider.fetch_daily` computed
`symbol = ref.provider_symbol.rpartition(".")[0]`, intended to strip a
country suffix (e.g. `"TTE.PA"` → `"TTE"`). But `provider_symbol` is already
the **resolved, provider-ready** symbol (`symbols/mapping.py`'s `resolve()`
builds it as `f"{root}{yahoo_suffix}"`), and the Yahoo suffix for a US listing
is the *empty string* — so a US ticker's `provider_symbol` is already bare,
e.g. `"AAPL"`, with no dot at all. `"AAPL".rpartition(".")[0]` on a string
with no `"."` returns `""` (confirmed directly:
`>>> "AAPL".rpartition(".")[0]` → `''`), not the original string. Every
`fetch_daily` call for a US-listed instrument — Polygon's *entire* covered
market, per its `can_serve` gate (`is_us_listing`) — was silently sending an
empty ticker to the API. It would have failed exactly this way for every
single US holding, always, since the provider was written.

**Same bug, four more places.** `grep -rl 'rpartition("\.")\[0\]'` across
`providers/` turned up the identical line, verbatim, in `tiingo.py`,
`alpha_vantage.py`, `intrinio.py`, and `finviz.py` — five providers built in
the same batch (phase 2), evidently from the same starting template, all
carrying the same wrong assumption about what `provider_symbol` looks like
for a bare US ticker.

**Fix.** `.rpartition(".")[0]` → `.split(".")[0]` in all five files.
`"AAPL".split(".")[0]` → `"AAPL"` (unchanged, correct); `"TTE.PA".split(".")[0]`
→ `"TTE"` (suffix stripped, correct) — one expression that handles both
shapes, instead of one that silently breaks on the more common of the two.
Verified live: Polygon's error changed from `"Ticker was incorrectly
formatted"` to `"Unknown API Key"` (the expected rejection for a fake test
key) — confirming the real ticker now reaches the API.

**Known remaining edge case, not fixed.** A US ticker whose *root itself*
contains a dot (e.g. `BRK.B`-style names) would still be truncated by
`.split(".")[0]` — indistinguishable, by string shape alone, from a
country-suffixed symbol. Fixing that needs cross-referencing
`SUFFIX_MAP`'s known country suffixes rather than a blind split, and is a
narrower, rarer problem than the one just fixed (every plain US ticker,
always) — left as a follow-up if a real held instrument ever hits it.

**Why this shipped unnoticed for so long.** Every test of these five
providers up to this point — Bug 2b.8's host audits, the "Test key" button's
own rollout — exercised either the auth-rejection path (a bad key, which
returns before the symbol is even validated on some providers) or, for
Polygon specifically, was blocked first by the host bug (Bug 2b.12) and then
the timestamp-parsing bug, each masking what was underneath. This is the
third bug in a row surfaced only once a *real* key reached the actual
request-building code — reinforcing Bug 2b.12's lesson: rejection-path
testing proves nothing about the success path, and neither does "the error
changed" without checking that the new error is a *smaller, more specific*
problem than the last one, not just a different label for the same one.

**Verified fixed, with real keys, same day.** User re-tested all five
affected/adjacent providers via the "Test key" button:

| Provider | Result |
|---|---|
| Polygon | ✓ received 4 day(s) of data |
| Alpha Vantage | ✓ valid (rate-limited, which itself confirms the key and ticker were both accepted) |
| Twelve Data | ✓ received 4 day(s) of data |
| FMP | ✓ received 5 day(s) of data |
| Tiingo | ✓ latest quote: 305.26 |

Cross-checked Tiingo's general docs overview page too (no mention of an
account-level toggle for historical access, consistent with what Bug 2b.11
already established from the API's own error message) — nothing further to
fix there. This closes out the run of provider bugs found by actually
exercising real keys through the "Test key" feature, rather than only ever
testing the rejection path.

## Step 2b.13 — Three new FMP capabilities: quote, sector enrichment, name search (2026-08-14)

**Context.** User shared FMP's own onboarding docs (four starter endpoints:
search-by-name, quote, profile, income-statement). Two of the four map
directly onto real, previously-unmet needs from this session; implemented
all three usable ones (income-statement is phase-3/scoring scope, deferred).

**1. `FmpProvider.fetch_quote`** (`/stable/quote`) — joins Yahoo and Tiingo as
a live-quote source for the "Prix frais" feature (2b.7). Same US-only limit
as `fetch_daily`.

**2. `FmpProvider.fetch_profile`** (`/stable/profile`) + `POST
/api/portfolio/enrich-sectors` — the significant one. `Instrument.sector` has
existed as an unused column since the very first schema (models.py), and A4's
sector breakdown was explicitly scoped *out* back then for lack of any source
that provided it (verified live at the time: `sector` was populated nowhere
in the codebase). FMP's profile endpoint closes that gap. Deliberately **not**
part of the daily refresh: sector barely changes, so a dedicated one-off
endpoint (skips any instrument that already has a `sector`) avoids spending
FMP's 250/day quota re-asking settled questions. `BREAKDOWN_DIMENSIONS`
gained `"sector"`; `PortfolioBreakdown.tsx` gained a fourth tab with a "Fetch
sector data (FMP)" button shown only on that tab.

**3. `FmpProvider.search_by_name`** (`/stable/search-name`) + `GET
/api/portfolio/symbol-search` — powers a debounced autocomplete on
`ManualPositionForm`'s symbol field. Search fires only when the typed text
has no `"."` (a `.`-bearing string is read as the user already typing a
broker-style ticker like `AAPL.US`, not a company name) and is ≥2 characters,
350ms after the last keystroke. Picking a suggestion appends `.US` — FMP's
free tier is US-only, so every suggestion is a US listing by construction.

**Field names not independently verified against a real response.** FMP's
official docs blocked automated fetches (403) and no third-party source had
the exact JSON shapes; implemented from FMP's long-standing, widely-known
field conventions (`price`, `sector`, `industry`, `country`, `symbol`,
`name`), parsed defensively throughout (`.get()` everywhere, `None`/`[]` on
any unexpected shape) so a wrong field name degrades to "no data" rather than
a crash — same discipline as Tiingo's `_error_detail`. Live-tested with a
fake key: all three return empty/`None` cleanly, confirming no crash on the
error-response shape at least; the success shape remains to be confirmed
once used with a real key.

**Note — DEVLOG numbering collision, found and fixed.** This session's "Bug
2.X" and one "Decision 2.1" (starting from the "Phase 2"/"Phase 2b" sections
this session began, before this file's much larger pre-existing project
history further down was ever read) collided with unrelated pre-existing
entries using the same numbers. Fixed by moving this session's colliding
entries into the free `2b.4`–`2b.13` range (this session's `Bug 2.1`–`Bug
2.11` → `Bug 2b.4`–`Bug 2b.13`) and `Decision 2.7` (this session's
`Decision 2.1` → `Decision 2.7`, the next free number after the pre-existing
`Decision 2.1`–`2.6`) — chosen to continue the *pre-existing* numbering
sequences without colliding with them, even though these entries appear
earlier in the file than the pre-existing ones they follow numerically.
This session's `Step 2b.1`–`2b.13` never collided with anything and were
left as-is. One rename pass (`Bug 2.2` → `Bug 2b.5`) briefly renamed the
*pre-existing* "network test failed" entry by accident (`replace_all` on a
bare "Bug 2.2" matched both), caught immediately by re-grepping headings
after every rename and reverted.

## Note — live verification of Step 2b.13, and a caveat on Intrinio (2026-08-15)

App launched (backend + frontend, both already running from the user's own
session — reused rather than starting duplicates) and inspected directly
rather than taking results on faith.

**Sector enrichment confirmed working end-to-end.** 23 enriched, 0 failed,
breakdown chart correctly shows Technology 43.8%, Financial Services 3.7%,
etc., with the expected "Unknown" bucket (42.6%) for non-US holdings FMP's
free tier cannot cover — matches the design in Step 2b.13, not a bug.

**Intrinio is trial-only, not a permanent free tier.** User reports Intrinio
only offers a time-limited free trial rather than an ongoing free plan like
the other keyed providers here. Unlike IEX Cloud/WTD/Quandl (Bug 2b.8, "Bug
2.6"), this isn't dead — it works today — but it will stop working once the
trial lapses, silently degrading to `is_enabled() == True` with a key that no
longer authenticates (same failure shape as an expired/revoked key on any
provider). Not fixed here — no code change needed since `is_enabled()`
correctly reflects "a key is configured," not "a key that will keep working
indefinitely" — but worth remembering if Intrinio starts failing after
working today: check trial status before assuming a code regression.

**Live-estimate gap and same-day "0 mis à jour" re-confirmed as expected,
not investigated further** — both already explained and accepted at Bug
2b.4/2b.6/2b.7 (cached close + daily FX rate vs. real-time; once-per-day
per-instrument refresh cadence).

## Decision 2b.1 — Real-time price refresh updates via WebSocket or polling

**Context.** Current refresh returns entire report at the end. No visibility during the operation (can take 30-60s with free tier throttling).

**Choice.** Add WebSocket endpoint `/ws/prices/refresh` that streams updates as each instrument finishes.

**Alternative rejected.** Server-Sent Events (SSE): simpler but unidirectional. WebSocket allows frontend to cancel or request retries mid-stream.

**Consequence.** Progress bar updates in real-time showing "12/37 done", "5 rate-limited", "20 seconds elapsed".

**Lesson.** A test that passes by luck on a connection pool is a false positive.

## Decision 1.3 — Show automatic mappings as "unverified"

**Context.** Suffix conversion (`.FR` → `.PA`) only rewrites the suffix, never the root of
the symbol. `ERICB.SE` becomes `ERICB.ST` where Yahoo expects `ERIC-B.ST` — the result is
wrong but looks valid.

**Decision.** An automatic mapping is displayed **"unverified"** in grey, not in green as
if validated. Only a manual correction earns "confirmed". A "fix" button is available on
every row, including already-resolved ones.

**Reason.** Showing a never-tested hypothesis in green implies a confidence nothing
supports.

**Follow-up.** In phase 2, a mapping that has actually served to fetch prices will be able
to graduate to "verified".

## Phase outcome — 81 tests, end-to-end import working

Verified in the browser against a synthetic file. **Caveat at that point**: the real format
had not yet been confronted. That was the number-one identified risk, hence the request to
the user for a real export.

---

# Phase 1b — Meeting the real files (2026-08-12)

Two production exports supplied by the user: a brokerage account and a tax-wrapper account.
**Initial result: "0 positions, 0 operations, no table recognised".**

This confrontation exposed **seven bugs** the synthetic file could never have surfaced —
the assumed structure was wrong on nearly every point.

## Bug 1b.1 — The workbook looked entirely empty *(cause of the reported symptom)*

**Symptom.** No table recognised; `max_row = 1` on all three sheets.

**Cause.** XTB exports declare a **wrong** `A1:A1` dimension in their metadata. In
`read_only` mode openpyxl trusts that declaration without inspecting the data, and returns
a single cell.

**Fix.** Load the workbook in normal mode (`read_only=False`). The memory overhead is
negligible: a few hundred rows per file.

**Lesson.** `read_only=True` is an optimisation that assumes correct metadata. On files
produced by a third party, that assumption does not hold.

## Bug 1b.2 — The company name was taken for a ticker

**Symptom.** No usable symbol even once the data was being read.

**Cause.** Column confusion. In the real format, **`Ticker` holds the symbol** (`CP.US`)
and **`Instrument` the company name** (`Canadian Pacific`). The `instrument` alias was
mapped to `symbol`.

**Fix.** `ticker` → `symbol`, `instrument` → `name`, with `ticker` explicitly winning. The
company name is now used and displayed under the symbol.

## Bug 1b.3 — Positions would have been counted twice

**Symptom.** Caught during structural analysis, before it could produce a wrong total.

**Cause.** Open positions come in **two levels**:

```
My Trades | ASML       | ASML.NL | STOCK |     | 1.0 | ...   <- aggregate row
My Trades | 1636247573 | ASML.NL |       | BUY | 1.0 | ...   <- lot
```

One holding = one aggregate row + N lot rows. On the real files, **38 positions occupy 153
rows**. Treating them uniformly would have **doubled the portfolio**.

**Distinguishing rule adopted.** Aggregate row = `Type` empty and `Category` set; lot = the
opposite. Verified across both files in full: 38 aggregate rows and 115 lots, **no
ambiguity**.

**Fix.** Only aggregate rows become positions. Lots are used to date the entry (the
earliest), count the tranches, infer the direction and recover the current price. A
fallback treats lots as positions when no aggregate level exists — so nothing is lost on a
format variant.

## Bug 1b.4 — Unique-constraint violation on import

**Symptom.** `IntegrityError: UNIQUE constraint failed: transactions.external_id,
transactions.type` on the brokerage file. The first import failed silently from the
client's point of view (empty response).

**Cause — twofold.**

1. My first inspection truncated the display at 16 columns, leading to the wrong conclusion
   that closed positions had no identifier. They do: `Position ID`, column 24 of 25.
2. That identifier **is not unique**. A holding closed in several parts produces several
   rows sharing one `Position ID`: **223 rows for 220 identifiers**.

**Fix.** The deduplication key combines the identifier **and** the execution details
(symbol, open and close timestamps, volume, price), plus an occurrence counter for
byte-identical rows. Stable across imports, unique per row.

**Lesson.** Never conclude anything about a file's structure from a truncated view. The
inspection script now prints every column.

## Bug 1b.5 — Duplicates within a single import went undetected

**Symptom.** Found while fixing 1b.4: the constraint still fired despite the existence
check.

**Cause.** The check ran a `SELECT` against the database, but objects added to the session
and not yet flushed are invisible to a query. Two rows sharing a key in the same file both
passed the check, then failed the constraint at flush time.

**Fix.** An in-memory `seen` set complements the database check to cover intra-import
duplicates.

## Bug 1b.6 — Numeric identifiers rendered as floats

**Symptom.** `external_id` came out as `"1677685567.0"` instead of `"1677685567"`.

**Cause.** openpyxl returns whole numbers from a workbook as `float`.

**Fix.** A `_clean_id` helper that normalises integral floats.

**Why it mattered.** A badly formatted identifier still works for deduplication as long as
it is *consistent*, but it breaks any future reconciliation against another source, and
looks wrong in the database.

## Bug 1b.7 — The "Price" column was empty on every row

**Symptom.** Spotted visually in the UI after a successful import.

**Cause.** `Current price` is only populated on lot rows, not on the aggregate row.

**Fix.** The price is taken from the first available lot.

**Trap avoided.** Deriving it as `market value / quantity` would have been tempting and
**wrong**: market value is in the account currency (EUR), average cost in the instrument's
currency (USD). The table would have shown two incomparable prices side by side.

## Decision 1b.1 — The broker category outranks any naming heuristic

**Context.** My heuristic classified `GOLD.US` as a commodity because of the word "GOLD" in
the symbol. **`GOLD.US` is Barrick Gold**, a mining equity listed on the NYSE and perfectly
analysable. It was being wrongly excluded from all future analysis.

**Decision.** The export's `Category` column (`STOCK`, `ETF`, `CFD`) is authoritative. The
symbol heuristic is now only a fallback for manual entries, where no category exists.

**Consequence.** CFDs are no longer reported as anomalies: having no mapping is the
expected behaviour for them, not a problem to fix. Warnings now list only genuinely
doubtful cases.

**Measured result.** Flagged symbols dropped from 7 to 1 on the real files. The remaining
one, `US592CVR0133`, is a CVR — a contingent value right with no tracked listing, so
legitimately unresolved.

## Decision 1b.2 — The position snapshot is replaced account by account

**Context.** An XTB export covers **a single account**. The user has two, so two separate
files.

**Problem caught before it caused damage.** The initial logic deleted *all* imported
positions before inserting the new ones. Importing the tax-wrapper statement would
therefore have **wiped the brokerage account's holdings**.

**Decision.** Deletion is limited to the accounts present in the file, identified by the
`Product` column. Falls back to a global replacement when the file carries no account
information.

**Verification.** Dedicated test: import A, then B, then A again — B's positions stay
intact.

## Decision 1b.3 — Purchase value is derived, not approximated

**Context.** The export provides no "purchase value" column for open positions (it exists
only on closed ones).

**Decision.** `purchase value = market value − unrealised P&L`. Both are in the account
currency, so the derivation is **exact**, not an approximation.

**Alternative rejected.** `quantity × average cost`: both of those are in the instrument's
currency, which would have mixed USD and EUR in a single total.

## Phase outcome — reconciled to the cent

> The figures below are **anonymised**: illustrative values, internally consistent but
> fictional. The real numbers are not in this repository.

```
TOTAL           38 positions | value 8,730.40 € | unrealised +2,420.40 € | +38.36 %
  My Trades     27 positions | invested 4,210.00 € | value 6,315.40 € | +50.01 %
  PEA           11 positions | invested 2,100.00 € | value 2,415.00 € | +15.00 %
```

**The validation method itself is real.** Each "Open Positions" sheet contains its own
summary rows (`Product | Value` and `Product | Profit`), computed by XTB independently of
the position detail. The totals rebuilt by the application match those rows **exactly, to
the cent** — for both accounts.

That is the best validation available: a source of truth inside the file itself, which no
parsing error could reproduce by chance. A doubling of positions (bug 1b.3) or a bad
purchase-value derivation (decision 1b.3) would have shown up immediately.

Other checks: 1,395 transactions imported, 223 closed positions, **0 positions excluded**
for lack of data, re-importing both files → **0 inserts** (idempotency confirmed on real
data).

**128 tests pass.** The fixtures now mirror the real format: 25 columns, two-level
structure, partial closes sharing an identifier, "Total" rows to discard.

## Technical note — no schema migrations

The schema evolves through `create_all`, with no migration tool. On every model change the
development database is **dropped and rebuilt by re-import**. Acceptable while the source
of truth remains the export files.

**Revisit when** non-reconstructible data appears (a hand-maintained watchlist, score
history, personal notes): Alembic will then be needed. The watchlist lands in phase 4 —
that is the trigger to watch for.

---

# Phase 1c — Bringing it under version control (2026-08-12)

## Bug 1c.1 — Real account numbers hardcoded

**Symptom.** Caught while preparing the git setup, before any publication.

**Cause.** Test fixtures had been built by copying the structure of the real files,
account numbers included. They appeared in 5 files across roughly forty places, including
a source-code docstring.

**Fix.** Replaced with fictional numbers. All 128 tests passed unchanged: no assertion
depended on those values, which confirms they had no reason to be there.

**Lesson.** Building a fixture from a real file pulls personal data into the code without
anyone thinking about it. Reproduce the *structure*, never the *content*.

## Decision 1c.1 — No personal data in the repository

Fictional account numbers in fixtures, illustrative amounts flagged as such in this log,
and a `.gitignore` excluding `.env`, the SQLite database and export files. Raw statements
stay outside the project.

## Decision 1c.2 — History split into logical commits, with real dates

**Decision.** Nine commits, one per coherent unit of work (tooling, foundation, symbol
mapping, parser, persistence, API, frontend, documentation), rather than one monolithic
initial commit. Every commit carrying tests is independently green — verified by cloning
and running the suite at each revision.

**What was rejected.** Backdating the commits to simulate development spread over several
weeks. The history reflects how the work actually unfolded: its readability comes from the
split, not from an invented chronology.

---

# Phase 1d — English codebase and internationalisation (2026-08-13)

The repository is meant to be public, so the code, comments and documentation moved to
English, and the UI gained English / French / Polish switching.

## Decision 1d.1 — The API returns message codes, not sentences

**Context.** The backend was returning import diagnostics as French prose
("Colonnes non reconnues dans « Closed Positions »…"). No amount of frontend work can
translate that: the meaning is fixed the moment the backend commits to a language.

**Decision.** The API is **language-neutral**. Every human-readable message is a `code`
plus its parameters:

```json
{ "code": "import.unresolvedSymbols", "params": { "count": 2, "symbols": ["FOO.XX"] } }
```

The same treatment applies to the sheet summaries (`{sheet, kind, count, source_rows}`)
and to symbol-mapping reasons.

**Reason.** Import diagnostics are the most valuable thing this backend produces — they
say which rows were skipped and why. Locking them to one language would make them useless
to every other reader.

**Consequence.** Tests assert on codes rather than on sentences, which is more robust:
rewording a message no longer breaks a test. A dedicated test enforces the contract — no
warning may contain a space in its code.

## Decision 1d.2 — Hand-rolled i18n layer on top of `Intl.PluralRules`

**Decision.** A small typed translation layer (~110 lines) rather than a library.

**Reason.** The need is modest — three languages, ~104 keys, one interpolation format —
but the plural handling is not: **Polish has three plural categories** (`one`, `few` for
2–4, `many` for 0 and 5+). The usual `count === 1 ? singular : plural` is wrong twice over
in Polish. `Intl.PluralRules` is built into the platform and solves it correctly, with no
dependency.

**Safeguards.** A missing key falls back to English before falling back to the raw code, so
a gap degrades to a readable sentence rather than an identifier. In development, a
load-time check reports any key present in English and missing elsewhere.

**Verification.** A script compares the three catalogues: 104 keys, no gaps, no extras.

**Also covered.** Numbers and dates go through `Intl.NumberFormat` / `Intl.DateTimeFormat`
bound to the active locale — so English shows `12,345.67` and `08/12/2026`, French
`12 345,67` and `12/08/2026`, Polish `12 345,67` and `12.08.2026`. Language names in the
switcher stay in their own language: someone looking for "Polski" should not need to know
the word for it in the current interface language.

---

# Phase 2 — Provider layer and market prices (2026-08-13)

Two findings during implementation invalidated part of the approved plan. Both were
measured, not assumed.

## Decision 2.1 — ~~Stooq as the fallback price source~~ → dropped

**What changed.** Stooq no longer serves CSV. Every URL form now returns an HTML page
carrying a JavaScript proof-of-work challenge:

```
This site requires JavaScript to verify your browser.
(async()=>{const c="AAAA…",d=4,…crypto.subtle.digest("SHA-256",…)
```

**Decision.** Stooq is removed as a data source. Solving that challenge programmatically
would mean defeating a bot-detection mechanism, which is not something this project will
do — regardless of how easy the hashcash itself is.

**Replaced by** Twelve Data (decision 2.3).

## Bug 2.1 — Yahoo rate-limits far harder than assumed

**Symptom.** Four requests in quick succession were enough to earn `HTTP 429`. The block
then persisted for **over thirty minutes**, across both `query1` and `query2` hosts, from
the same IP.

**Verification that it was not a local problem.** SEC EDGAR answered `200` from the same
machine throughout, so outbound networking was healthy — the block is Yahoo-side and
IP-scoped.

**Consequence for the design.** With 38 holdings, a naive "refresh everything now" would
fail most of the way through and leave the user unable to tell what had updated. The
refresh was therefore built around the limit rather than in spite of it:

* **cache first** — stored bars are never re-fetched; a refresh asks only for missing
  days, which after the initial load is a handful;
* **skip what is fresh** — an instrument updated today is left alone;
* **serialised with a minimum gap** between calls, since bursts are what get an address
  blocked, not steady traffic;
* **a time budget** — the run stops cleanly and reports how many instruments remain,
  instead of hanging or half-failing;
* **per-instrument outcomes** — partial success is the normal case, not an error.

**Observed behaviour under the real failure**, with the IP already blocked: 8 instruments
reported `prices.rateLimited`, the budget cut the run at 64 seconds, 29 were reported as
remaining, and nothing crashed. That is the intended behaviour — the design was validated
by the failure, even though no data came back.

## Decision 2.2 — "Rate-limited" is a distinct outcome from "failed"

A throttled provider means *come back later*; an unknown symbol means *this will never
work*. Collapsing the two would leave the user retrying something that cannot succeed, or
giving up on something that would.

`FetchResult.rate_limited` is deliberately true only when **every** attempt was throttled:
if one provider throttled and another said the symbol does not exist, the actionable
answer is the second one.

## Decision 2.3 — Twelve Data as the keyed fallback

Chosen to replace Stooq: a free tier with an email signup (no card), a documented 800
requests/day and 8/minute, and coverage of non-US venues — which matters, since this
portfolio spans several European markets.

**Honest caveat.** The provider is written against the documented response shape and
covered by unit tests, but has **not** been exercised against the live API: no key was
available while writing it. The first real call is the one to watch. It is key-gated, so
its absence changes nothing until someone configures it.

## Decision 2.4 — A mapping becomes "verified" only when data actually arrives

Phase 1 introduced the "unverified" label for automatic suffix conversions (decision 1.3).
It now graduates: the first time a provider returns real bars for a symbol,
`verified_at` and `verified_provider` are recorded and the badge turns green.

Verification and provenance are kept as **separate facts**: a manually corrected mapping
stays `MANUAL` and gains `verified_at`. Overwriting one with the other would lose the
information that a human chose that symbol.

## Decision 2.5 — Yahoo through its chart endpoint, not through yfinance

The plan named `yfinance`. The direct chart endpoint is what that library calls for price
history anyway, so calling it directly removes a large dependency that breaks several
times a year without losing anything we use. Fewer layers between us and the data means
fewer ways to break — and the endpoint sits behind `PriceProvider` precisely because it
is unofficial and can change.

## Phase outcome

**174 tests pass.** The provider layer is covered with mocked transports: parsing,
null-padding, 429 handling, retry-then-give-up, chain fallback, and the distinction
between throttling and a bad symbol. The refresh service is covered for caching,
freshness, budget exhaustion and mapping verification. Nine end-to-end tests drive the
real API with an injected provider.

**Not verified live:** the actual HTTP call to Yahoo, because this machine's IP is
blocked. That path is covered by a `@pytest.mark.network` test, excluded by default.

## Bug 2.2 — The network test failed instead of skipping, and the diagnosis was wrong twice

**Symptom.** Running `pytest -m network` produced a red failure: `RateLimited: yahoo is
throttling requests`.

**First wrong assumption (mine).** I had described the 429 as a cooldown to wait out. It
was still in place more than an hour later, so "try again in a few minutes" was too
optimistic.

**Second wrong assumption (also mine), and how it was disproved.** An *immediate* 429 on
the very first request of a fresh process looks less like volume throttling than like a
missing session — Yahoo's API is known to want cookies. So that was tested rather than
assumed:

| Attempt | Result |
|---|---|
| Plain request, no cookies | 429 |
| After seeding cookies from `fc.yahoo.com` and `finance.yahoo.com` | 429 |
| `/v1/test/getcrumb` (to obtain the crumb token) | **429** — the token endpoint itself is blocked |
| `finance.yahoo.com/quote/AAPL` (the HTML site) | 200, 1.5 MB |

The HTML site answers normally while every path on `query1.finance.yahoo.com` returns
429, including the endpoint that would hand out the session token. So it is an IP-level
block on the API host — not a session problem. The cookie hypothesis was wrong, and
testing it cost three requests rather than an afternoon of building the wrong fix.

**Fix, part 1.** The network test now **skips** rather than fails when throttled. Being
rate-limited says nothing about whether our parsing is correct; a red test for a third
party's behaviour only trains people to ignore red tests.

**Fix, part 2.** The refresh report gained an actionable message. Repeating "rate
limited" 38 times tells the user nothing they can act on, so when every instrument was
throttled *and* no keyed fallback is configured, the report says so once and names the
remedy.

## Decision 2.6 — Twelve Data is recommended, not merely optional

Reachability was checked from the blocked machine: Twelve Data answered `401 — apikey
parameter is incorrect or not specified`, which is the correct response to a keyless
request and proves the host is reachable. Alpha Vantage also answered with real data.

So the practical situation is: **Yahoo may simply not work from a given network**, while
the fallback does. `TWELVEDATA_API_KEY` is therefore documented as recommended rather
than optional, and the app points the user at it when throttling leaves it with nothing.

**On the difference from Stooq.** Accepting cookies and reading a public JSON endpoint is
ordinary HTTP client behaviour. Stooq's proof-of-work page is an explicit challenge whose
only purpose is to establish that a browser is running it. Working around the second is
evasion; the first is not — which is why one source was dropped and the other kept.

The UI was inspected against seeded bars — 37 sparklines rendering, coloured by
direction, with verified badges — and the seed was then **deleted**, so no fabricated
prices remain in the database.

---

# Phase 2b — First live provider calls (2026-08-13)

A real Twelve Data key arrived, so the provider written blind (decision 2.3) met the
live API for the first time. It worked — and immediately exposed three problems that no
amount of mocked testing could have surfaced.

## Bug 2b.1 — The freshness test defeated the entire cache

**Symptom.** Chasing an odd "0 bars" line in a refresh report led to comparing
`fetched_at` timestamps, which showed most instruments had been fetched **twice**.

**Cause.** Freshness was "is the newest stored bar from the last trading day". Free feeds
lag: Twelve Data's most recent bar was **2026-08-11** while the last expected trading day
was **2026-08-13**. That comparison is therefore *permanently* false, so every instrument
looked stale on every run and the whole portfolio was re-fetched each time — precisely
what the cache existed to prevent, and a direct waste of a limited daily quota.

**Fix.** Freshness is now "have we already asked today", tracked in
`Instrument.prices_checked_at`. Daily bars are published once, so a second question the
same day cannot return anything new.

Throttled instruments are deliberately **not** marked as asked: rate limiting is
temporary and they must be retried on the next run, unlike a wrong symbol, which will
not fix itself before tomorrow.

**Verification on real data**, across consecutive runs — each pass now advances instead
of redoing the previous one:

| Pass | Updated | Already fresh | Remaining |
|---|---|---|---|
| 1 | 7 | 0 | 29 |
| 2 | 7 | 8 | 21 |
| 3 | 7 | 16 | 13 |
| 4 | 2 | 24 | 5 |
| 5 | 0 | 32 | 0 |

## Bug 2b.2 — Two refreshes ran at once

**Symptom.** The same double-fetch investigation. The server log showed two requests:
`POST /api/prices/refresh?force=false` from the browser, and `POST /api/prices/refresh`
from a terminal, overlapping.

**Cause.** Nothing prevented concurrent runs. Data stayed correct — the upsert and the
unique constraint held — but the quota spent was doubled for no benefit.

**Fix.** A process-wide lock, acquired **non-blocking**: making the second caller wait
would hide the problem behind a slow response, whereas "a refresh is already running" is
something the user can act on.

## Bug 2b.3 — "Already fresh" was claimed for instruments with no data at all

**Symptom.** After every instrument had been asked once, a refresh reported *37 already
fresh* — while only 23 had any price data.

**Cause.** The freshness fix keyed purely on "asked today", which is also true of an
instrument that was asked and got nothing.

**Fix.** A separate outcome, `prices.stillUnavailable`, when an instrument has been asked
but nothing is stored, and it counts as a shortfall rather than a skip. "Fresh" must mean
*we have current data*, not merely *we asked*: a reassuring label over an empty series is
worse than an honest gap.

## Decision 2b.1 — Twelve Data's free tier is US-only

**Measured, not assumed.** Their own error message settles it:

> `This symbol is available starting with the Grow or Venture plan`

Symbol format was ruled out first — `ASML.AS`, `ASML` + `exchange=AMS`, `ASML` +
`exchange=XAMS` all returned 404 before the `country=Netherlands` variant produced the
message above.

**Consequence on this portfolio:** 23 of 37 instruments now carry real prices, and the
14 without are *every single European holding* (`.FR`, `.NL`). The split is exactly the
provider's plan boundary.

A 404 is now distinguished from a plan restriction: `PlanLimited` says the symbol is
correct and there is nothing to fix locally, where `SymbolNotFound` would send the user
chasing a mapping problem that does not exist.

**Still open.** Yahoo remains the only free source covering European venues, and it is
IP-blocked here. Nothing in the architecture needs to change — the chain is built for
exactly this — but the practical gap is real and is not papered over in the UI: those 14
rows show no trend line and stay marked *unverified*.

## Phase outcome

**193 tests pass.** All three bugs above have regression tests. Verified end to end on
real data: 38 positions, 23 with live prices and a green *verified* badge, 14 European
holdings honestly showing no data.

Test isolation was also fixed along the way: the suite read whatever was in the
developer's `.env`, so a test asserting "no integration is enabled" passed or failed
depending on who ran it — and a failure message could have printed a real API key. An
autouse fixture now clears credentials for every test.

---

# Phase 2c — A free European price source (2026-08-13)

Twelve Data's free tier being US-only left 14 European holdings with no data at all.
This phase closes that gap.

## Decision 2c.1 — Bot-detection challenges stay out of scope, even when asked twice

The request came up again to work around anti-bot protections and document the
workaround. The answer is unchanged: Stooq's proof-of-work page exists precisely to
establish that a browser is executing it, so defeating it means stepping past an access
control the operator put there deliberately — and this repository is public.

That is a narrow line, not a blanket refusal. Accepting cookies, sending a normal
User-Agent and reading a public JSON endpoint are ordinary HTTP client behaviour, and
Yahoo and Frankfurt are both used on exactly that basis. The distinction is whether the
site has erected a challenge whose only purpose is to exclude non-browsers.

The gap was closed without crossing it.

## Decision 2c.2 — Boerse Frankfurt as the European source

Probed several candidates before landing:

| Source | Result |
|---|---|
| Yahoo | Still 429 from this IP, hours later |
| Euronext `live.euronext.com` | Returns an **AES-encrypted** payload its frontend decrypts — same category as a challenge |
| Boursorama | 503 on the history endpoint |
| Boerse Frankfurt `quote_box` | 200 with real data |
| Boerse Frankfurt `tradingview/history` | **200, full OHLCV daily history** |

Frankfurt exposes a TradingView UDF endpoint needing no key, no session and no
challenge. Verified live: 284 daily bars for ASML and for TotalEnergies.

**Caveat that matters when reading the numbers:** these are the *Frankfurt* listing's
prices, not the home market's. For a Paris- or Amsterdam-listed share the two track
closely — the cross-check below shows 0.0–2.7% — but they are different venues and
Frankfurt volume on a foreign listing is much thinner.

## Bug 2c.1 — One "symbol" string assumed every provider shared a namespace

**Symptom.** Frankfurt accepts an ISIN and nothing else. Tickers, slugs and company
names were all tested against the live endpoint and rejected.

**Cause.** `ProviderChain.fetch_daily(symbol, ...)` forced every provider to pretend
they used the same identifier. Yahoo wants a venue-suffixed ticker, Twelve Data a bare
one, Frankfurt an ISIN.

**Fix.** An `InstrumentRef` carrying every identifier. Each provider takes the whole
reference and picks what it needs, raising `SymbolNotFound` when its own identifier is
missing — so the chain simply moves on.

## Decision 2c.3 — ISINs are entered and corroborated, never guessed

Frankfurt's search endpoint **ignores its search term**: asked for "TotalEnergies" it
returns the highest-turnover German stocks. OpenFIGI resolves tickers correctly but
returns FIGIs, not ISINs. A Wikidata query returned nothing usable.

So ISINs cannot be resolved automatically from a ticker. And a wrong ISIN is the worst
possible failure here: it would silently return **another company's prices**, which is
far more damaging than showing no data.

The ISIN is therefore user-supplied, with one exception that is not an inference: when
the broker's ticker field *literally contains* an ISIN — seen on a CVR line
(`US592CVR0133`) — it is recorded as one.

**How the seeded ISINs were verified.** Rather than trusting them, each was cross-checked
against the market price XTB itself had already reported for that holding. A wrong ISIN
would show a wildly different price:

| Symbol | XTB price | Frankfurt | Gap |
|---|---|---|---|
| AF.FR | 12.29 | 12.30 | 0.1% |
| MT.NL | 64.36 | 64.34 | 0.0% |
| SAN.FR | 75.41 | 75.19 | 0.3% |
| ASML.NL | 1558.00 | 1576.20 | 1.2% |
| MC.FR | 478.75 | 466.05 | 2.7% |

Nine of nine corroborated. The residual spread is the venue difference, not an error.

## Phase outcome

**213 tests pass.** Coverage went from 23 of 38 holdings priced to **32 of 38**: 23 via
Twelve Data, 9 via Frankfurt.

The six still without prices are honest gaps, not silent ones: five ETFs whose ISIN
nobody has entered yet, and one CFD, which has no fundamentals by nature. Each can be
fixed in the UI by typing an ISIN, and the interface explains why it is not filled in
automatically.

## Bug 2c.2 — "No source covers this market" when the truth was "we never had an identifier"

**Symptom.** Five ETFs reported *no configured provider covers this market on its free
plan*. That was wrong: Frankfurt had never been offered them at all, because they had no
ISIN recorded.

**Cause.** `stillUnavailable` was emitted for any instrument asked today with nothing
stored, collapsing two different situations — *every source declined* and *no source
could even try*.

**Why it mattered.** The message sent the user looking for a coverage problem, when a
12-character field was the actual fix. A misleading diagnosis is worse than a vague one.

**Fix.** A distinct `prices.needsIsin`, which names the action. The pair now forms an
honest progression: no identifier → *needs an ISIN*; identifier present but nothing
found → *still unavailable*.

## Decision 2c.4 — ETF ISINs proposed, but only the corroborated one applied

The five ETFs were searched and candidate ISINs found with matching tickers. Each was
then checked the same way as the equities — against the price XTB already reported:

| Symbol | Candidate | Result |
|---|---|---|
| INR.FR | FR0010361683 | 25.71 vs 25.86 → **0.6%, accepted** |
| DCAM.FR | FR001400U5Q4 | not listed in Frankfurt |
| PAEEM.FR | FR0013412020 | not listed in Frankfurt |
| CAC.FR | 3 candidates | none listed in Frankfurt |
| SPEA.FR | 3 candidates | none listed in Frankfurt |

Only the corroborated one was applied. The other four were left unset **on purpose**:
they could not be verified, and — more to the point — Frankfurt does not list those
funds, so a correct ISIN would change nothing today. Recording an unverified identifier
to create the appearance of completeness is exactly the failure mode this project keeps
refusing.

These four are Euronext Paris listings that Yahoo does cover under the symbols already
derived (`DCAM.PA`, `PAEEM.PA`...). They will resolve on their own the day Yahoo is
reachable — no ISIN needed.

**Coverage: 33 of 38 holdings priced.**

## Bug 2c.3 — The time budget was spent on instruments that needed no work

**Symptom.** A run reported *8 updated, 0 already fresh, 29 remaining* — while most of
those 29 were already up to date and would have been settled instantly.

**Cause.** The budget loop walked the instruments in one pass, so it expired among
entries that cost nothing. Skipping is free; fetching is not. Mixing them meant the
deadline was consumed by list position rather than by work.

**Fix.** Partition first: everything settleable without a network call is resolved
before the timed loop starts. `remaining` now means *remaining fetches*, which is the
only number a user can act on.

**Effect on the same portfolio:** 16 instruments settled per run instead of 8, and the
already-fresh ones are counted instead of being invisible.

**Test note.** The original budget test pinned an exact number of clock reads and broke
as soon as the implementation read the clock once more. It now uses a clock that
advances on every read and asserts the invariant — settled plus remaining equals the
total — rather than a tick count.

## Decision 2c.5 — Four French PEA ETFs have no free source, and that is stated plainly

Verified rather than assumed, and on the right endpoint this time: the first check used
Frankfurt's *quote* endpoint, so the *history* endpoint was retested directly. It
answers `s=no_data` for every candidate ISIN of `DCAM.FR`, `SPEA.FR`, `PAEEM.FR` and
`CAC.FR`.

Other routes were probed and abandoned rather than forced: Amundi's own site, justETF
and Boursorama returned 404/400/410 on their public paths. Continuing would have meant
guessing endpoint URLs, which is not evidence.

These four are Euronext Paris listings that Yahoo covers under the `.PA` symbols already
derived — no ISIN required. They will fill in by themselves once Yahoo is reachable from
the network in use. Until then the UI shows no trend line and says why, which is the
honest state.

---

# Phase 2d — Exhausting the free European sources (2026-08-13)

Four French PEA ETFs still had no data. This phase closed the search — with a negative
result worth recording, so nobody repeats it.

## What was tested, and what it proved

| Source | Outcome |
|---|---|
| Yahoo | 429, still, hours later. Covers everything — when reachable |
| Boerse Frankfurt | `s=no_data` on the **history** endpoint for every candidate ISIN. Note: the first check used the *quote* endpoint, which was a testing error on my part |
| Tradegate | Answers, and the price is right (6.276 vs XTB's 6.246). But its charts are served as **PNG images** — there is no history to read |
| Euronext | Returns an **AES-encrypted** payload its own frontend decrypts |
| Amundi, justETF, Boursorama | 404 / 400 / 410 on public paths |
| Twelve Data (free) | US only — its own message names the paid plan |
| FMP (free) | **US only.** `TTE.PA` and `DCAM.PA` both answer HTTP 402: *"not available under your current subscription"* |

## Decision 2d.1 — Stop looking for a free Euronext ETF source

Two commercial free tiers were checked and both stop at the US border. Excluding non-US
venues is evidently how these plans are monetised, so a third signup is unlikely to end
differently. Continuing would have meant guessing endpoint URLs on retail brokers' sites,
which is not evidence — and the one time I started doing that, it produced nothing.

**The gap is narrower than "Europe".** Frankfurt covers European *shares* perfectly well:
10 of this portfolio's holdings, including TotalEnergies, LVMH and ASML, are priced
through it. What is missing is four French PEA ETFs, which are niche instruments listed
only in Paris.

**The honest options**, in order of cost:

1. Run the app from a network where Yahoo is reachable — free, covers everything, needs
   no key and no ISIN.
2. A paid data plan.
3. Accept the gap: 4 instruments out of 38, shown as an explicit blank rather than a
   fabricated number.

## Bug 2d.1 — FMP's v3 endpoint is retired, and I called it anyway

**Symptom.** Every FMP symbol, including `AAPL`, came back as *plan limited*.

**Cause.** Two mistakes at once. The `/api/v3/` path is retired — it answers *"Legacy
Endpoint: no longer supported"* — and my error classifier matched that message on the
word "supported" and filed it as a subscription boundary.

**Why the misclassification mattered more than the wrong URL.** It would have sent the
user to a pricing page to pay for something no amount of money fixes. A dead endpoint and
a plan boundary need different words.

**Fix.** The `/stable/` API, and a retired endpoint now raises `ProviderUnavailable`.
Verified: `AAPL` and `NVDA` return real bars, `TTE.PA` returns a clean plan boundary.

FMP is kept as a third US source rather than removed — it works, just not for what it was
added for.

## Note — an API key was exposed in the session

While diagnosing a malformed `.env` (the key had been pasted without its
`FMP_API_KEY=` prefix), a formatting command printed the key value in clear text. It was
flagged immediately and rotation recommended. The lesson is in the tooling, not the
carelessness: inspection commands that touch `.env` must print names and lengths only,
never values.

## Decision 2d.2 — Respect rate limits rather than evade them

The question came up of randomising IP or MAC addresses to get around the Yahoo block.

**On MAC specifically:** it would have no effect whatsoever. A MAC address is a
layer-2 identifier that never leaves the local network segment — Yahoo has never seen it
and never will.

**On IP rotation:** rotating identifiers to defeat an anti-abuse control is out of scope
here, for the same reason Stooq's proof-of-work page was. Using a different network that
is not blocked is ordinary use of a legitimate connection; cycling addresses to break the
blocking mechanism is not the same act.

**The engineering answer, which is the real one.** That block came from *development*
traffic — dozens of probe requests in bursts — not from the application. But nothing in
the code prevented it from happening again, and that was a genuine gap:

* a **provider cooldown**: after a 429, that source is left alone for 15 minutes instead
  of being retried on each of the next thirty instruments. Hammering through a throttle
  is what turns a short limit into a long block;
* the cooldown is **per provider**, so backing off from one does not stop the chain
  finding another;
* the Yahoo interval moved from 2s to **5s**. A portfolio refresh is not
  latency-sensitive, and being slower is what keeps it working;
* the reason is still reported while cooling down — silence would look like a bug.

Combined with the existing cache-first rule and one-question-per-instrument-per-day, a
normal refresh now makes a few dozen well-spaced requests a day. That is well inside what
these endpoints tolerate, which is the actual way to not get blocked.

---

# Phase 3a — Fundamentals from SEC EDGAR (2026-08-13)

Prompted by a fair objection: *"we want the most data possible, otherwise why build the
app"*. That reframed the priority correctly. Four missing ETF price series is 10% of one
pillar; **having no fundamentals at all is 100% of three pillars**. Prices alone cannot
answer "hold or sell".

SEC EDGAR is the best source in the project — the figures come from the companies' own
regulatory filings, not a vendor's reconstruction. Free, no key, no meaningful quota.

## Bug 3a.1 — One tag chosen for a whole series

**Symptom.** NVIDIA showed FY2022 revenue next to FY2026 net income.

**Cause.** `_extract` took the first candidate tag that had *any* data. NVIDIA reports
revenue under `RevenueFromContractWithCustomerExcludingAssessedTax` through FY2022 and
switches afterwards, so the series stopped four years short — while profit, on a stable
tag, was current.

Worth noting: the module docstring warned about exactly this before the code did it.

**Fix.** Merge per fiscal year across tags, higher-priority tag winning for each year.

## Bug 3a.2 — Foreign filers returned nothing

**Symptom.** ASML and TotalEnergies: every concept empty.

**Cause.** Three assumptions, all wrong for non-US filers:

| Assumption | Reality |
|---|---|
| Annual reports are `10-K` | Foreign private issuers file `20-F` (and `20-F/A`) |
| Figures are in USD | **ASML reports in EUR** — reading only the USD unit found nothing |
| The taxonomy is `us-gaap` | **TotalEnergies files under IFRS**, where revenue is `Revenue` and profit is `ProfitLoss` |

**Fix.** Both forms and their amendments, both taxonomies, and any reporting currency —
with the currency **stored on every figure**. That last part is not cosmetic: a ratio
built from EUR fundamentals and a USD share price is wrong in a way no unit test catches.

## Bug 3a.3 — Fundamentals of entirely unrelated companies

**Symptom.** A coverage run reported fundamentals for 31 of 38 holdings. Reading the
names revealed what those numbers actually were:

| Holding | Resolved to | Actually |
|---|---|---|
| `AI.FR` | C3.ai, Inc. | **Air Liquide** |
| `ORA.FR` | Ormat Technologies | **Orange** |
| `SAN.FR` | Banco Santander | **Sanofi** |
| `DSY.FR` | Big Tree Cloud Holdings | **Dassault Systèmes** |
| `MC.FR` | Moelis & Co | **LVMH** |
| `CAC.FR` | Camden National Corp | a CAC 40 ETF |

**Cause.** The country suffix was stripped and the bare root looked up in the SEC index —
which is keyed on **US** tickers. `AI` in the US is C3.ai; `AI.FR` is Air Liquide.
Different companies entirely.

**Why it is the worst class of bug in this project.** Every one of those would have
produced a complete, plausible set of financials — revenue, margins, debt — attached to
the wrong company, and fed them straight into a hold-or-sell score. Nothing about the
output would have looked wrong.

**Fix.** The registrant name found at a ticker must match the company name the broker
reported, or the match is refused. The check is permissive on formatting
("TotalEnergies" ≡ "TotalEnergies SE") and strict on substance, and ignores legal-form
words, which identify nothing.

**Refinement after a false rejection.** The check initially also rejected `AMD.US`,
whose registrant is "Advanced Micro Devices Inc" against a broker name of "AMD". The rule
is now scoped: a name match is required for **non-US** instruments only. For a US listing
the broker ticker and the SEC ticker are the same namespace, so the lookup is exact by
construction and demanding a name match only discards valid data.

## Phase outcome

**25 of 38 holdings now carry verified fundamentals** — revenue, profit, equity, assets,
debt, cash flow and more, over five to six fiscal years each, in the filer's own
reporting currency.

Of the 13 without: 7 are European companies whose US ticker belongs to someone else and
which do not file with the SEC under their own name; 5 are French ETFs and a CVR, which
have no fundamentals by nature; 1 is a BDC reporting no conventional revenue line.

**250 tests pass.** All three bugs above have regression tests naming the actual
companies involved, because the abstraction is not what made them dangerous.

## Bug 3a.4 — The panel demanded a correction that does not exist

**Symptom.** `US592CVR0133` sat permanently under *"symbols without a mapping — until
corrected, they will not be analysed"*, with an empty field waiting for a provider
symbol.

**Cause — two layers.** The instrument is a CVR: a contingent value right from a
corporate action, not a listed security. It has no ticker, no quote and no accounts, and
its broker symbol *is* its ISIN. ISIN auto-detection was added after that row was
created, so the field stayed empty; and even once filled, the panel keyed on
`mapping_status` alone and would have kept showing it.

**Why it mattered.** A panel that asks the user to fix something has to contain only
fixable things. Otherwise the one row that never clears teaches the user to ignore the
whole panel — including the day it lists something they really could correct.

**Fix, in two parts.**

* Re-importing now **backfills** the ISIN on instruments created before detection
  existed, rather than leaving them permanently broken.
* The panel excludes anything already carrying an ISIN. Having an identifier and no data
  is a coverage gap, not missing information, and the two call for different words.

The CVR still appears in the positions table with its value. It is not hidden — it is
simply no longer presented as a defect.

## Decision 3a.1 — Look the filer up by name when the ticker belongs to someone else

`ORA.FR` is Orange; `ORA` in the US is Ormat Technologies. The name check (bug 3a.3)
correctly refused that match, but refusing left the holding with no fundamentals at all
when Orange does file with the SEC — under an ADR ticker nobody could guess.

So when a ticker is absent or belongs to a different company, the index is searched **by
name** instead. That direction cannot collide: the name is what is being matched on.

**The search rule is deliberately stricter than the verification rule.** `names_match`
accepts a single shared token, which is right once a ticker has narrowed the field to one
candidate, and useless across 10,000 registrants — "Air Liquide" collects Air Products,
Air Brake Technologies and Madison Air Solutions on the word "Air" alone. Searching
therefore demands every significant word, prefers an exact name, and **refuses
ambiguity outright**. Several tickers sharing one CIK (ordinary shares plus an ADR) are
not ambiguity.

Returning nothing costs one data point. Guessing attaches another company's accounts to
a holding, which is the failure this whole layer is built to avoid.

**Result:** Orange recovered (44.1bn EUR). Air Liquide and Sanofi are found in the index
but file nothing usable in XBRL. Dassault Systèmes, LVMH and Air France are not SEC
filers at all, and are now refused with that reason rather than silently mismatched.

**One caveat the scoring will have to respect:** Orange's latest filed year is FY2023,
because its ADR registration lapsed. The figures are real but two years stale. Every
figure carries its fiscal year and period end precisely so staleness can be surfaced
rather than assumed away.

**Coverage: 26 of 38 holdings with verified fundamentals.**

---

# Phase 2e — Boursorama closes the Euronext gap (2026-08-14)

Pushed back on with: *"you're not going to tell me that in the whole internet there is no
free source for these curves"*. That was right, and the reason I had not found one was a
method problem, not an availability problem.

## How it was found — by reading, not guessing

Every earlier attempt at Amundi, justETF and Boursorama had **invented plausible URLs**
and got 404/400/410. That is not searching.

The page declares its own endpoint. Fetching the ETF page and grepping its HTML surfaced
a chart bundle, `build/quote-chart*.js`; grepping the bundle surfaced
`window.VGP={urlWS:"/bourse/action/graph/ws/", callType:"GET"}`. Two requests, no
guessing, and the endpoint was `GetTicksEOD`.

**The lesson is the method.** Hours went into inventing URLs; reading what the page says
it calls took minutes.

## Bug 2e.1 — A missing header read as a rate limit

**Symptom.** The endpoint returned data, then began answering `410` with an empty body.
It looked exactly like the Yahoo block: worked, then stopped. A 45-second pause changed
nothing, so it was recorded as throttling.

**Cause.** Not throttling at all. The working requests carried
`X-Requested-With: XMLHttpRequest`, copied from the page; later ones had dropped it. With
the header, `200`; without it, `410`. Every time.

**Lesson.** "It worked and then stopped" is not evidence of rate limiting. The variable
that changed was in my own request, not on the server.

## Decision 2e.1 — Sending that header is in scope

It is the conventional header every AJAX library sets, it describes the request
accurately, and it is neither a token, a secret nor a challenge. Same category as the
browser-like User-Agent already used for Yahoo and Frankfurt.

That is the line, and it has not moved: Stooq's proof-of-work page and Euronext's
AES-encrypted payload exist *specifically* to exclude non-browsers, and both were left
alone. A header stating what the request is is not a circumvention.

## Decision 2e.2 — Verify by the name in the response

Boursorama prefixes tickers by type — `1rP` for Paris shares, `1rT` for trackers — and
the response includes the instrument's name. The prefix comes from the broker's
category, and the returned name is checked against the broker's name.

Not decoration: this project had already attached C3.ai's financials to Air Liquide by
trusting a symbol. A price series is just as easy to get wrong quietly, and here the
check is free.

## Outcome — 37 of 38 holdings priced

| Provider | Holdings |
|---|---|
| Twelve Data | 23 |
| Frankfurt | 10 |
| **Boursorama** | **4** |

All four French PEA ETFs recovered, with ~255 daily bars each, and closes matching the
prices XTB reported: DCAM 6.275 vs 6.246, CAC 87.25 vs 87.96, AI 169.14 vs 171.70.

Boursorama also covers the Paris-listed shares currently served by Frankfurt — the
*home* market rather than a secondary German listing — so it sits ahead of Frankfurt in
the chain and those will move over as they refresh.

The one remaining holding without prices is the CVR, which has no quotation at all.

**266 tests pass.**

## Decision 2e.3 — Some instruments have no price, and that is not a failure

The last holding without a price was `US592CVR0133`, "CONTRA METSERA INC CVR". Rather
than hunt for a sixth provider, the question was what the instrument actually is.

Pfizer acquired Metsera for $65.60 per share **plus** a contingent value right worth up
to $20.65 more, tied to three clinical and regulatory milestones. That CVR is
**non-transferable**: no ticker, no listing, no market. It cannot be bought or sold, so
no source anywhere quotes it. XTB itself reports a price of 0.00 against a nominal
placeholder value.

This is not a coverage gap. It is a property of the instrument, and no provider could
ever close it.

**Implementation.** `not_priceable_reason` marks such instruments. Detection is
deliberately narrow — it requires **both** a corporate-action name (CVR, CONTRA, RIGHTS,
WHEN ISSUED) **and** an ISIN-shaped symbol rather than a ticker. CVR Energy, a real
listed company, is untouched.

They are skipped before any provider is called, counted **separately from failures**, and
explained once. A permanent "failed" line teaches people to ignore the report.

## Note — the migration debt came due earlier than predicted

Adding that column broke the running database: `create_all` creates missing tables, never
missing columns. The DEVLOG had flagged this and guessed phase 4's watchlist would be the
trigger. It was price history instead — 10,193 bars that cost several rate-limited
refresh cycles to collect, and that a rebuild would have thrown away.

Handled with an `ALTER TABLE`, preserving the data. But the point stands and is now
concrete: **Alembic is needed before the next schema change**, not before phase 4.

## Decision 2e.4 — Route by market, and make the redundancy inspectable

Asked for more sources so that exhausting one leaves others. The chain already fell
through on failure, but it tried **every** provider in the same fixed order — so a French
holding spent a request on Twelve Data and another on FMP to be told, twice, something
already measured: their free tiers stop at the US border.

That is quota and wall-clock burned to learn nothing, and it is the opposite of
resilience: the sources meant to be the reserve were being drained on calls that could
not succeed.

**Providers now declare what they can serve.** `can_serve(ref)` is consulted before any
call, and a skip is deliberately **not** recorded as a failed attempt — nothing was
attempted, and listing it would bury the real reasons in noise.

| Provider | Scope | Basis |
|---|---|---|
| Yahoo | worldwide | needs only a symbol |
| Boursorama | Euronext Paris | verified live |
| Frankfurt | anything with an ISIN | keyed on ISIN alone |
| Twelve Data | US only | HTTP 402 on `TTE.PA`, measured |
| FMP | US only | HTTP 402 on `TTE.PA` and `DCAM.PA`, measured |

**`GET /api/prices/providers`** reports each source's state and how much of the portfolio
it could serve. Redundancy that cannot be inspected is a claim rather than a property,
and this answers "what happens if one stops" without breaking one to find out.

**Measured on the real portfolio:** 33 holdings have three independent sources, 4 have
two, and **none depends on a single source**. Losing any one provider — Yahoo blocked, a
quota exhausted, an endpoint changed — costs nothing.

## Decision 2e.5 — Alpha Vantage was the last free candidate, and it does not qualify

Kept coming up as the one untested free tier, so it was checked properly rather than
left as a maybe.

* **`TIME_SERIES_DAILY` is a premium endpoint.** Daily history — the only thing this
  application needs — is paywalled regardless of market. That alone disqualifies it.
* **25 requests/day**, against 37 priced holdings. Even if the endpoint were free, one
  full refresh would not fit in a day.
* Their own material describes non-US coverage as thinner than providers built around
  global exchanges.

Its symbol-search endpoint was probed with the demo key to inspect the universe directly;
the demo key is restricted to documented examples, so that route was closed too.

**The search for additional free price sources is closed.** Not for lack of trying: five
sources are wired, every holding has at least two and most have three, and the remaining
candidates are either paywalled where it matters (Alpha Vantage, EODHD, Marketstack) or
behind a bot-detection challenge this project will not defeat (Stooq, Euronext).

Effort is better spent on the scoring engine than on a sixth source that would serve
nothing the existing five cannot.

---

## Decision 2f.1 — Two live-estimate actions, not three (2026-08-15)

The portfolio page offered three separate "update data" buttons: *Rafraîchir les
cours* (refreshes the cached daily-bar history, budgeted), *Recalculer* (rereads
whatever is already cached for the live estimate, instant), and *Prix frais*
(spends real provider quota fetching genuinely live quotes for the live estimate,
budgeted). Asked directly whether that is good practice — it was not.

`loadLiveEstimate()` was already being called automatically at the end of every
`load()` in `Portfolio.tsx` (after import, after a price refresh, after adding or
deleting a position). *Recalculer* only ever repeated that same cache read on
demand — it never produced a number the user would not already be looking at,
since nothing changes the cache between one `load()` and the next except the
other two actions, both of which already trigger a reload themselves.

**Removed the *Recalculer* button entirely** (`LiveEstimatePanel.tsx`'s
`onRecompute` prop, `busy` state, and the `liveEstimate.recompute(ing)` i18n
keys in en/fr/pl). The live estimate still recomputes from cache automatically
wherever it already did; the panel now offers only *Prix frais*, the one action
that actually fetches something new. Two buttons left, each doing something the
other cannot: one refreshes the historical cache, the other spends quota on a
live quote.

---

## Decision 2f.2 — One "Actualiser" button, not two (2026-08-15)

Asked directly again, this time about the remaining two: real platforms don't make
the user choose between "update the history" and "update the live price" — they
either poll live automatically, or offer one button that means "make everything as
fresh as possible now." True automatic polling is not realistic here (see Decision
2d.2 — free sources throttle after a handful of rapid requests), so the fix is the
second shape: one button, two budgeted phases run back to back under the hood.

`RefreshPanel` now triggers `POST /api/prices/refresh` (history) and, once that
completes, `POST /api/portfolio/live-estimate/refresh` (live quotes) in the same
click, with a phase-labelled progress bar for whichever is running. `LiveEstimatePanel`
lost its own trigger entirely and became purely presentational — it renders whatever
`estimate` prop it is given, which `RefreshPanel` now supplies directly via
`onFreshEstimate` after the live-quote phase finishes.

**One subtlety that would have silently discarded live quotes:** `Portfolio.tsx`'s
`load()` already fires a cache-only `loadLiveEstimate()` GET as a side effect (for
the import/position-change cases where that is exactly right). Live quotes are
never persisted (`quote_service.py`'s own docstring says so — kept in memory for
one response only), so if `RefreshPanel` called `onFreshEstimate(freshResult)` and
then triggered that same `load()`, the cache-only GET would immediately overwrite
the fresh result with the stale cached one. Fixed by giving `load()` an
`opts.skipLiveEstimate` flag, set only by `RefreshPanel`'s callback — every other
caller (import, delete, manual add) is unaffected and still gets the automatic
cache-only reload it always had.

"Retry failed" stays scoped to the history phase only: the live-quote phase has no
per-symbol retry, it always covers the whole portfolio, so re-running it for a
three-symbol retry would spend the full live-quote budget for zero new coverage.

**Also fixed while in this area — the live estimate's freshness was unlabelled.**
Asked whether the "valeur actuelle estimée" figure reflects the live quotes just
fetched or older cached closes — it was impossible to tell from the UI in the
all-cached case (the old "N positions au prix en direct" line only rendered when
`liveCount > 0`). `LiveEstimatePanel` now always renders a freshness line: either
the live count (as before) or, when every value is cached, the most recent cached
close date pulled from `LiveEstimateItem.close_date`. True in every state, including
right after page load with no fetch yet attempted.

**And the import/live split got explicit dates.** "Valeur de marché", "Résultat
latent" and "Performance" (all broker-reported, from the last import, never
recomputed — Bug 2.1) now carry `· import du {date}` directly on the stat label
itself, plus the same note under "Par compte" — not just in the paragraph above the
stat grid, which is easy to stop reading after the first glance.

---

## Decision 2f.3 — Primary totals recompute live; the frozen-import design is retired (2026-08-15)

Asked directly for the thing "Decision 2f.2"'s import-date labels had been working
around: stop labelling "Valeur de marché" / "Résultat latent" / "Performance" as
frozen at import, and make them actually current. This reverses "Bug 2.1"'s original
call (never recompute the broker's own figures, keep them "trustworthy to the
cent") — that call made sense when the only alternative was a fragile, easily-wrong
recomputation; it stopped making sense once this app had a working, budgeted,
multi-source pricing pipeline of its own, and two competing "how much is this worth"
numbers on one page had become the more confusing failure mode.

**What actually changed, in `routers/portfolio.py`:** a new `_current_position_figures`
resolves, per position, the best price available — a live quote from this round, else
the latest cached daily close, else the broker's own frozen import figure — and
returns value/P&L/P&L% in `base_currency`. That frozen fallback is not a bug case,
it is the permanent, correct answer for **CFDs** (a contract count has no live-quote
equivalent, quantity × price would not mean what it means for a stock) and the
temporary answer for anything genuinely never priced yet. Cost basis
(`invested_value`) stays sourced from the broker import — `broker_purchase_value`,
which used the FX rate at the time of purchase, a number this app has no record of
and should not try to guess. `_compute_totals`, `_compute_account_totals`,
`GET /portfolio/breakdown` and the weight-percent calculation all switched from
summing `broker_market_value`/`broker_net_pl` to summing these current figures —
deliberately touching the per-account table and the per-position table (`VALUE`/
`UNREALISED`/`PERF.`/`PRICE` columns) in the same change, not just the header stats:
leaving the row-level numbers frozen while the header went live would have
reproduced the exact "which number is real" confusion one level down.

**The old `GET /live-estimate` / `POST /live-estimate/refresh` pair is gone.**
`GET /portfolio` now does cache-only current pricing itself (no provider calls,
safe on every load — the property that endpoint used to provide). What ran a
budgeted live-quote round now lives at `POST /portfolio/refresh-live`, and instead
of returning a separate `LiveEstimateOut` it returns the same `PortfolioOut` shape
as the plain GET, fully recomputed with whatever quotes it fetched — so
`RefreshPanel`'s second phase (see "Decision 2f.2") replaces the page's state
directly with one response, no extra round trip.

**The secondary "Valeur actuelle estimée" card is retired**, per the user's explicit
choice among three options (remove it / shrink it to a freshness note / keep it
as-is) — asked because it would otherwise duplicate what the primary totals now
show. Its one genuinely useful bit, per-instrument freshness, already has a home:
the existing `PriceStatusBadge` (✓/⏱/❌) on each row of the positions table.

---

# Up next

| Phase | Content | Status |
|---|---|---|
| 3 | Scoring engine (4 pillars — Value/Growth/Quality/Technical, `scoring.yaml`) | done — see Decision 3r.1 |
| 4 | Watchlist and entry timing | done — see Decision 3u.8 |
| 5 | Hidden gems page (screener) | done — see Decision 3u.11 |
| 6 | News/sentiment (Alpha Vantage) + qualitative commentary (Perplexity) | done — see Decision 3u.12 |

**Open items for phase 2**

- Promote mappings from "unverified" to "verified" once a provider has actually served
  data for that symbol.
- FX rates (`Open/Close Conversion Rate`) are captured but not yet used — useful for
  splitting performance between instrument effect and currency effect.
- `yfinance` will break periodically (unofficial endpoints): the fallback chain to Stooq
  needs to be tested for real, not merely written.
- **Introduce Alembic before the next schema change.** No longer hypothetical: adding a column already required a hand-written ALTER TABLE to avoid discarding 10,193 collected price bars.

**Research notes for phase 3 (scoring) — not decided, not started**

Prompted by looking at [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents)
(a multi-agent LLM trading-decision framework — evaluated and **not** adopted: no
portfolio awareness, per-ticker CLI workflow, undocumented LLM cost that could run to
tens of euros per full-portfolio pass; see the conversation this came from for the full
comparison). What's worth keeping from that detour is not the framework itself but the
observation that prompted it: there is more than one recognised way to score a stock,
they don't agree with each other, and some are better-evidenced than others. Before
inventing "5 pillars" from scratch, worth surveying named, existing methodologies and
picking deliberately rather than by default:

- **Value investing (Buffett/Graham style)** — moat, earnings consistency, ROE, debt
  levels, price vs intrinsic value. Well-documented, decades of track record, but
  historically weaker on high-growth/pre-profit names.
- **Growth investing** — revenue/earnings growth rate, TAM, reinvestment rate. Different
  ratio set entirely from value; the two philosophies routinely disagree on the same stock.
- **Quality/momentum factors** (academic factor investing — Fama-French style) — has
  published, peer-reviewed backtested evidence behind it, which most "guru style" framings
  don't.
- **Technical/quant signals** — price action, moving averages, RSI/MACD. Already
  data this app can compute from cached `PriceBar` history without a new source.
- **News/sentiment-driven** — reacts to recent events rather than fundamentals; this is
  the category Perplexity (phase 6) already covers, deliberately kept separate from the
  score per Decision 0.3.

Open question worth resolving **before** phase 3 starts, not during: is this app scoring
against **one** chosen philosophy (e.g. "this is a value-investing tool") or blending
several into pillars, and if blending, how are the (frequently contradictory) verdicts
reconciled without the score becoming an unweighted average of methods that disagree
with each other. Precision/reliability differs by method and worth a real
comparison — not assumed equal — before `scoring.yaml` gets designed.

---

## Decision 3b.1 — A real historical value chart, built on a ledger the export already had (2026-08-15)

Asked for a "historical portfolio value" chart. The naive version — replay *today's*
holdings against past prices — was rejected on request: it answers "how would my
current basket have done," not "how did my money actually do," and only the second
question supports an honest benchmark comparison later (item #9), since it reflects
real buy/sell timing rather than a reshuffled snapshot.

The blocker looked like missing data — no transaction history exists, only the current
`Position` aggregate and a generic `Transaction` ledger for closed trades — until
re-reading `xtb_import.py`'s own `_build_open_positions`. It already parses **every
individual lot row** (volume, open price, open time) to compute `Position.opened_at`
(the min of lot times) and `lots_count`, then throws the lots away. `_build_closed_positions`
already keeps `opened_at`/`open_price`/`closed_at`/`close_price` per row too — it just
never made it past `Transaction`'s narrower column set. Nothing needed guessing; the
per-trade granularity was one throwaway statement away.

**New `Lot` table** (`models.py`): one row per actual fill, open (`closed_at`/`close_price`
null) or closed (both set). Deduplicated on re-import the same way `Transaction` is
(`UniqueConstraint(external_id, lot_type)`) — reusing `_build_closed_positions`'s existing
per-row key for closed lots, since it already solves "Position ID not unique across
partial closes." Open lots are pure upsert, never wiped per account the way `Position`
is — a lot that closes between two imports must stay in history after its `Position`
row is gone. Verified live against a re-import of the same file: 7 lots (3 open, 4
closed, including a partial-close pair) both times, no duplication.

Manually entered positions get one synthetic `Lot` too (`create_manual_position`), so
reconstruction has a single source of truth instead of a special case. `delete_position`
now cascade-deletes only that position's still-*open* lots — closed lots are settled
history, untouched regardless of what happens to the current position.

**No Alembic needed for this.** `Lot` is a brand-new table; `Base.metadata.create_all`
(already run at every startup) creates it with zero risk to existing data — the
overdue-migration-tool debt (DEVLOG, repeatedly) is about altering *existing* tables,
which this change doesn't do.

`prices/history_service.py`'s `compute_value_history` replays the ledger day by day:
holdings = lots with `opened_at ≤ day` and (`closed_at` null or `> day`); price = latest
cached close forward-filled through gaps; a day with holdings that can't be priced
reports `value: null`, never a guessed zero — but a day with *no* holdings at all
correctly reports a true `0.0`, a deliberate distinction (nothing existed yet / was
fully sold, vs. something existed but couldn't be priced). `invested` (cost basis) is
computed in parallel and needs no price at all, so it's populated even on days `value`
isn't. CFDs are excluded, same rule as the live "current value" path — a contract count
has no history to replay. Range is capped at whichever is later of the earliest real lot
or `today − INITIAL_HISTORY_DAYS` (400), flagged via `capped_by_history` rather than
silently truncated.

## Decision 3b.2 — Frankfurter's range endpoint, live-verified before relying on it

The live "current value" FX lookup (`get_rate`) only ever needed today's rate. A chart
needs one rate per day for up to 400 days per currency — one HTTP call per day would be
absurd, so this checked Frankfurter's range endpoint (`/v1/{start}..{end}`) directly
against the real API rather than trusting the docs, per the project's standing discipline
(see "Bug 2d.1", "Decision 2e.2"):

- One call *does* cover the whole span (confirmed: `2025-05-29..2025-06-03` returns all
  four covered business days in one response).
- **Weekends/holidays are simply absent** from the response — no forward-fill from
  Frankfurter itself. `get_rate_range` forward-fills app-side, same posture as `PriceBar`
  gaps.
- A span entirely outside ECB coverage returns HTTP `404`, not `200` with empty rates —
  must be caught before parsing, not assumed away.
- (Noted but not relied on: the single-date endpoint silently snaps an off-day request
  back to the prior business day's rate under the *requested* date's key — irrelevant
  once the range endpoint is used, since it doesn't do this.)

`get_rate_range` checks the `FxRate` cache for every expected business day in range
first, and only calls out when at least one is missing — so a chart reloaded later the
same day, or by another currency pair already seen, costs zero network calls.

## Outcome — verified end to end (2026-08-15)

303 tests passing (287 → 303: Lot creation/dedup, `get_rate_range` forward-fill/caching/
404-handling, `compute_value_history`'s null-vs-zero distinction, CFD exclusion, capped
range). Live-checked in the browser: the chart renders its empty state cleanly against
the real portfolio (0 `Lot` rows today, since these 37 positions were imported before
this feature existed — the ledger only backfills on the *next* import). Rendering itself
verified by patching the page's `fetch` to return synthetic points without touching the
real database: both series draw at the correct SVG coordinates, and a null-value prefix
in the "value" series is correctly skipped rather than joined across the gap.

**Not done yet, on purpose**: re-importing the real XTB export to backfill `Lot` history
for the existing portfolio (needs the user's file); benchmark comparison (item #9),
scoped as the next step once this ledger exists — was the whole reason "real
reconstruction" was chosen over a cheaper backtest in the first place.

---

## Decision 3c.1 — Wikidata as a second sector source, for what FMP's free tier can't reach (2026-08-15)

Prompted by the real portfolio's sector breakdown showing 41.8% "Inconnu" — much more
than the ETF-only gap that would be structurally unavoidable. Investigated rather than
assumed: every US holding already had a correct, FMP-sourced sector; the entire gap was
9 European stocks (LVMH, ASML, TotalEnergies, Sanofi, Air Liquide, ArcelorMittal, Air
France-KLM, Dassault Systèmes, Orange) plus 5 ETFs and one CVR — the latter two
permanently unfixable by *any* data source (an ETF holds a basket, not one sector; a CVR
has no fundamentals), the European stocks a genuine, potentially closeable gap.

**Checked four sources live before building anything, per the project's standing
discipline of verifying against the real API rather than the docs:**

- **Yahoo** (`quoteSummary`/`assetProfile`) — 429 even at the `getcrumb` step. Unlike
  the `chart` endpoint this app already relies on for prices, Yahoo's profile endpoint
  has been hardened enough since roughly 2024 that unauthenticated access is not
  practically usable.
- **Twelve Data** (`/profile`, `/statistics`) — HTTP 403, "available exclusively with
  grow/pro/ultra/venture/enterprise plans." Free tier has neither.
- **FMP** (`/stable/profile`) — HTTP 402 even on a plain European symbol, confirming
  (not just repeating) the existing "US-only free tier" finding at the sector-lookup
  endpoint specifically, not only the price-history one.
- **Alpha Vantage** (`OVERVIEW`) — empty `{}` for a Paris-suffixed symbol, consistent
  with "Decision 2e.5"'s prior finding that non-US coverage is thin to nonexistent.

**Wikidata worked** — free, keyless, no meaningful rate limit for occasional one-off
enrichment — but two real problems needed solving before it was trustworthy, both found
by testing against the actual 9 holdings, not assumed:

1. **Vocabulary mismatch.** Wikidata's `industry` (P452) is free-text and far more
   granular than FMP's GICS-style sectors ("semiconductor industry" vs. "Technology").
   Mixing the two in one breakdown chart would put NVDA under "Technology" and ASML
   under "semiconductor industry" as if they were different sectors — worse for
   readability than "Inconnu". Fixed with `INDUSTRY_TO_SECTOR`, a manually built mapping
   table (`providers/wikidata.py`) — not exhaustive by design, an unmapped industry is
   dropped rather than shown raw.
2. **Entity resolution.** Searching by company name is not reliable alone: "TotalEnergies"
   also matched a cycling team of the same name; "Air Liquide" and "ArcelorMittal" and
   "Dassault Systemes" all had a country-suffixed subsidiary (Austria, Poland, Czech
   Republic) rank ahead of or alongside the real parent company in search results, one of
   which (`Dassault Systemes CZ`) carried outright wrong data (`automotive industry`).
   Filtering candidates to those carrying a stock exchange (P414) — the strongest
   available signal of "this is the publicly traded entity, not a subsidiary or an
   unrelated namesake" — combined with keeping search-rank order (SPARQL's `VALUES`
   does not preserve it) resolved all 9 correctly, including the one initial failure
   (Air France-KLM, which is `wdt:P31` "organization" rather than a strict subclass of
   "business" — dropping that type filter entirely in favour of the P414 check alone is
   what fixed it, verified against a known-good `Apple Inc` control case too).

**Wired into the existing `POST /enrich-sectors`**, not a new endpoint: FMP is tried
first when a key is configured, Wikidata second for whatever FMP couldn't or wouldn't
serve. ETFs and CFDs are now explicitly excluded from both — before this change FMP's
own `can_serve` (US-listing check) happened to keep them out too, but only as a side
effect; explicit exclusion means that stays true regardless of what either source's
`can_serve`-equivalent does.

**Outcome, live on the real portfolio:** 7 of 9 European holdings enriched exactly as
predicted from the manual live testing above (ASML→Technology, LVMH→Consumer Cyclical,
TotalEnergies→Energy, Sanofi→Healthcare, Air Liquide→Basic Materials,
ArcelorMittal→Basic Materials, Dassault Systèmes→Technology); Air France-KLM and Orange
correctly stayed "Inconnu" (no mappable industry data on Wikidata for either — an honest
gap, not a resolution failure). "Inconnu" dropped from 41.8% to 19.9% of the portfolio,
the remainder being the 5 ETFs, the CVR, and those two. 8 new tests in
`test_wikidata.py` (mocked, no live network calls in the suite) covering the rank-order
selection, the "correct entity, no mappable industry" stop condition, and defensive
parsing. 311 tests passing (303 → 311).

---

## Decision 3d.1 — A transactions page, and P&L split into realised/unrealised (2026-08-16)

Items #9 and #10 from the original UI list, requested together: both build directly on
the `Lot` ledger and `get_rate_range` infrastructure from "Decision 3b.1" — the whole
point of choosing a real reconstruction over a cheap backtest back then.

**Transactions had zero exposure anywhere** — `Transaction` (dividends, fees, trades,
cash movements, already imported and sitting in the database this whole time) had no
router, no schema in use, no page. `TransactionOut` existed in `schemas.py` but nothing
ever imported it. New `routers/transactions.py`: `GET /api/transactions`, filterable by
type (grouped into user-meaningful buckets — dividends, trades, fees, cash — not the raw
9-value `TxType` enum) and date range, with a summary that **honours the same filters as
the list** (a "this year" filter summarises this year's dividends, not all-time) rather
than a fixed lifetime total.

**`account` recovered from `raw`, not a new column.** `Transaction` has no `account`
field, and adding one means an ALTER TABLE on a table that already holds real imported
rows — exactly the debt this project has avoided since Alembic was ruled unnecessary for
brand-new tables (Decision 3b.1) but never actually introduced. The value was never lost:
the parser already writes it into `raw` (the verbatim source row) under whatever header
text the export used — "Product" in English, "Produit"/"Compte" in French. Recovering it
with a **hardcoded `raw.get("Product")` would have silently broken on a French export** —
caught before shipping by reusing `xtb_import._match_column`, the exact same
normalised-alias lookup the parser itself used to build `raw` in the first place, rather
than assuming the literal header text.

**Realised P&L, one query.** `CLOSED_TRADE.amount` already *is* realised P&L per
position — summed with one `SUM(amount) WHERE type = CLOSED_TRADE` and added as a fifth
stat tile on the main Portfolio page, next to "Résultat latent" (item #3). A real,
non-zero figure on the real portfolio, confirmed live.

Verified live end to end: 1395 real transactions surfaced (previously invisible),
correct per-transaction account recovery ("My Trades"/"PEA") on real English-language
export data, summary math checked against the actual dividend/tax/fee/realised-P&L
figures. 7 new tests in `test_transactions_api.py` covering both English and French
`raw` header spellings specifically, since that was the one thing that could not be
verified from English fixture data alone.

## Decision 3e.1 — Benchmark comparison via a cash-flow-matched shadow portfolio (2026-08-16)

Item #9. The chosen index: **S&P 500**, matching the portfolio's own ~80% US
concentration — decided with the user rather than assumed.

**Not a price-ratio overlay.** For each real `Lot`, the benchmark series asks "how many
benchmark units would this same cash have bought, on the same real opening date" (a
*shadow quantity*), and — critically — **closes that shadow position on the same day the
real lot closed.** The real `value` series only ever counts currently-active lots; once a
position is sold, its cash leaves the tracked portfolio entirely (there is no "cash lot").
A shadow portfolio that kept compounding sold-off money forever would be comparing "money
currently at risk" against "money ever put in, forever compounding" — not the same
question, and inconsistent with what `value`/`invested` already mean. Cash-flow-matched
sells keep the benchmark line honestly comparable to the real one, same units, same axis,
not a normalised percentage.

**Representing the benchmark cost nothing new to build.** It is just another `Instrument`
row (`get_or_create_benchmark_instrument`, `prices/history_service.py`), constructed
directly from config rather than resolved via `symbols.mapping` — there is no broker row
to resolve from, both symbols come straight from settings. Once it exists,
`routers/prices.py`'s refresh endpoint adds it to the instrument list (it is invisible to
the existing `JOIN Position` query, on purpose — it is never a real holding) and the
*entire* existing provider-chain/`PriceBar` machinery serves it unmodified.

**The ticker was live-verified, not assumed — and the verification is exactly why an ETF
was chosen over a raw index ticker.** Yahoo was rate-limited in the dev sandbox at
verification time (unrelated IP-level throttling, not a real-deployment issue — see the
"can we get around the Yahoo block" exchange). Rather than treat that as a blocker, the
real provider chain was exercised end to end for `SPY`: it failed over to Polygon
automatically and returned 22 real daily bars, closing at $776.34 on 2026-08-14 — the
exact resilience the 15-provider chain exists for. A tradable ETF ticker earns this for
free; a raw index symbol (`^GSPC`) would have needed new provider-specific handling to
even attempt.

**Missing data stays missing.** A lot whose real open date has no cached benchmark price
or FX rate contributes nothing to the shadow series that day — same "never a guessed
number" rule as `value`/`invested`. `benchmark_available` (a benchmark is configured at
all) is tracked separately from each point's own `benchmark: null` (this specific day
could not be priced), since the two mean different things to the frontend caption.

`compute_value_history` extended in place rather than duplicated: the shadow-quantity
precompute reuses the exact same `PriceBar`/FX batch-loading the real series already
does, just widened from the display-capped `start` back to the *true* earliest lot — a
lot opened before the chart's visible window still needs a real benchmark price on its
real open date. Frontend: a third, dashed polyline (`ValueHistoryChart.tsx`, `--series-3`,
already defined, no new CSS), only drawn when `benchmark_available`, with copy explicit
that the line is a simulation, not a raw price ratio — this was flagged during planning
as the one place a misreading (a naive "line goes up more" comparison) would be worse
than no line at all.

**Test isolation note**: the benchmark defaults *on* (an S&P 500 ETF, not an unset API
key), which broke 4 pre-existing price-refresh tests written before it existed — each
suddenly saw one extra instrument in its counts. Fixed at the source: `conftest.py`'s
existing `isolate_credentials` autouse fixture (which already normalises API-key state
for every test) now also actively disables the benchmark by default; a test exercising it
enables it explicitly via a fresh `Settings(...)` instance, not env-var juggling against
the cache. 4 new tests in `test_history_service.py::TestBenchmarkOverlay` (same-currency,
cross-currency, unconfigured, configured-but-unpriced). 322 tests passing (311 → 322).

---

## Bug 3f.1 — The progress bar vanished on navigating away and back mid-refresh (2026-08-17)

Reported: start "Actualiser", switch to Settings, come back — the button looks idle
again, as if nothing had happened, even though the refresh was still genuinely running.

Both status endpoints (`GET /api/prices/refresh/status`, `GET /api/portfolio/refresh-live/
status`) are already process-wide, not tied to any one request — the backend was never
confused about what was running. The bug was entirely in `RefreshPanel.tsx`: `busy`/
`phase`/`historyStatus`/`liveStatus` are local component state, and React Router
navigation unmounts the whole `Portfolio` page (and everything inside it) on route change.
Coming back mounts a *new* `RefreshPanel` with fresh, empty state — nothing had actually
reset server-side, the panel just stopped looking at it.

**Fixed by checking both status endpoints once on mount** and resuming polling/the
progress bar if either is still `running`, instead of assuming idle. Phase 1's report is
recoverable this way regardless of which panel instance is watching, since
`RefreshStatusOut` already carries the full `report` alongside progress — a resumed
phase-1 completion is exactly as informative as one this panel started itself.

**Phase 2 has a real, narrower limit that this does not paper over.** The live-priced
portfolio a `POST /api/portfolio/refresh-live` call produces only ever existed in that
one HTTP response body — `QuoteStatusOut` carries progress, not the result. A live-quote
round that finishes while unmounted still spends real provider quota and computes real
prices; there is simply nothing left holding onto them for a panel that resumes watching
after the fact. The fix falls back to a cache-only reload once such a round ends (same
path the retry button already uses) rather than showing nothing — correct, but not as
fresh as if the original tab had stayed on the page. Making phase 2's result durable
(persisting live quotes somewhere queryable, or a small "last completed round" cache)
would close this properly; not done here since it is a real design decision — a
different cache to invalidate, a different kind of "freshness" to reason about — not a
one-line fix, and not what was asked for.

Verified live: started a refresh, switched to Settings, switched back — the progress bar
reappeared mid-stream at its real, current count instead of a blank "Refresh" button.

## Decision 3g.1 — Full transaction management: create, correct, delete (2026-08-18)

Item #10 of the original list was only ever half-built ("Decision 3d.1" gave the ledger a
read-only view). The user caught this directly when it was reported as done in a status
summary — it wasn't, only *visibility* was — so this closes the actual gap: hand-entered
transactions, correcting a wrong amount/date/account/comment, and deleting a row.

**Manual creation is deliberately restricted to cash-flow types** — dividends, tax, fees,
deposits, withdrawals, interest, other. `MANUAL_TX_TYPES` in `routers/transactions.py`
excludes BUY/SELL/CLOSED_TRADE on purpose: those are what the `Lot` ledger (and the real
historical value chart built on it, "Decision 3b.1") actually reasons about. A manual
Transaction row of a trade type with no matching Lot would be a convincing-looking phantom
trade — visible in the ledger, invisible to the chart. Adding or correcting a holding
still goes through `POST /api/portfolio/positions`, which creates the Position and its
Lot together. The same restriction applies to `PATCH` — a row can't be *retyped into* a
trade type — but an existing imported CLOSED_TRADE row can still have its amount or
comment corrected, since the restriction is about creating new phantom trades, not about
editing history that's already backed by a real Lot.

**No new column for `account`.** Same reasoning as `_account_from_raw` in "Decision 3d.1":
`Transaction` has no `account` column, and won't gain one without a migration tool in
place. Create/update both write it into `raw["Product"]`, the exact key the read path
already scans for — one code path serves imported and manually-entered rows alike.

**Frontend**: `ManualTransactionForm.tsx` mirrors `ManualPositionForm.tsx`'s collapsed-card-
to-form pattern; the type dropdown only ever offers the seven manual types, so there is no
way to construct an invalid request from the UI. Editing is inline, per row (a `<tr>`
becomes input cells on "Edit" — no modal component exists anywhere in this app, matching
its existing lightweight-table-editing convention), and deletion is a plain button with no
confirmation step, matching `PositionsTable.tsx`'s existing delete pattern.

Backend: 11 new tests (`TestCreateManualTransaction`, `TestUpdateTransaction`,
`TestDeleteTransaction`), full suite green at 333 passed. Verified live end to end in the
browser: created a manual dividend (42.50 EUR, account "PEA", comment "Test manuel"),
edited its amount to 99.99 inline and confirmed the row updated with no page reload, then
deleted it and confirmed it disappeared from the ledger — no console errors at any step.

## Decision 3h.1 — Import preview, history, and undo, restricted to the newest import (2026-08-18)

Item #6 of the original list: show what an import *would* do before committing it, list
past imports, and allow undoing a mistake — none of which existed. Selecting a file
committed straight to the database, and while `GET /api/imports` and a typed frontend
client method already existed, nothing ever called them.

**Preview reuses the real ingest logic rather than reimplementing it.** `import_export_file`
(`ingest/service.py`) gained a `commit: bool = True` keyword. With `commit=False` it runs
the exact same parse/insert/dedup path — so the counts shown are exactly what a real
import would do, not an estimate — then instead of committing, captures the summary
fields into a plain dict and calls `db.rollback()`. Fields have to be read *before* the
rollback: SQLAlchemy expires every ORM instance in the session on `rollback()` regardless
of `expire_on_commit`, so reading `batch.warnings` etc. afterward would fail. A flag
rather than a duplicate function, specifically so the identical dedup/warning logic
always runs — a naive "count rows in the file" preview would lie whenever dedup would
have skipped a row, and the unresolved-symbols warning block already runs before the
commit point regardless, so preview warnings come out accurate too, for free. New route
`POST /api/imports/xtb/preview` (kept separate from the committing endpoint so
`response_model` isn't ambiguous between `ImportBatchOut` and `ImportPreviewOut`).

**Undo — `DELETE /api/imports/{id}` — is restricted to the single most recent import.**
`Lot` and `Transaction` dedupe globally on `(external_id, type_or_lot_type)`
(`_insert_deduped`), so a row's `import_batch_id` records which import *first inserted*
it, not which import *owns* it. XTB exports typically re-export full account history each
time, so heavy overlap between successive imports is the normal case. If undo deleted
`WHERE import_batch_id == N` for an import that isn't the newest, and a later import M
had seen the same `external_id` but skipped it (deduped against N's already-existing
row), undoing N would delete real data M's own export still supports. Restricting undo to
`id == MAX(id)` (compared by id, not `imported_at` — the latter is set client-side in
Python at object-construction time and isn't a reliable ordering) closes this completely:
nothing after the newest import exists, so nothing could have deduped against its rows.
`Position` deletion is actually safe regardless of order — each import hard-deletes and
fully replaces the Position rows for the accounts it covers, so a Position's
`import_batch_id` always means real, exclusive ownership — but the same LIFO rule applies
to it anyway, for one uniform, easy-to-audit rule across all three tables instead of two
different safety arguments. **Accepted trade-off**: undoing an older import requires
undoing everything imported after it first, in reverse order — fine for a rare "wrong
file" cleanup in a single-user app, not worth building per-row reference counting for.

`Instrument` rows are never touched by undo, matching the existing "deleting an
instrument must not silently erase historical lot data" posture (`models.py`) — an
orphaned unresolved-symbol `Instrument` left behind after an undo is expected clutter,
not a bug.

Frontend (`ImportPanel.tsx`): selecting a file now runs a preview first (same
`ImportReport` component, reused unchanged since it only ever read the 7 fields both
`ImportBatch` and the new `ImportPreview` share) with Confirmer/Annuler; confirming
re-uploads the same `File` to the real commit endpoint. A collapsible "Historique des
imports" section (wired to the previously-dead `api.listImports()`) lists past imports,
most recent first, with an "Annuler" button on the top row only — no confirmation dialog,
consistent with "Decision 3g.1"'s established delete pattern.

Backend: 10 new tests in `test_imports_api.py`, including the core safety regression —
import A creates a transaction, import B re-sees the same external id (deduped, stays
owned by A) plus a new one, undo B, assert A's transaction survives and only B's own row
is gone. Full suite green at 343 passed. Verified live end to end against the running dev
servers with a synthetic file under a throwaway account name (so the real imported
portfolio data couldn't be touched): preview showed correct counts before anything was
persisted, confirming it committed and refreshed the portfolio and history, undo removed
the position/history entry and left the rest of the real portfolio untouched, and a
direct `DELETE` on an older import returned 400 with the expected message once a newer
one existed — no console errors at any step.

## Decision 3i.1 — Text search and configurable columns on the two big tables (2026-08-18)

Item #7 of the original list. `PositionsTable.tsx` (13 columns, ~38 rows) and the
Transactions page table (7 columns, up to ~1,395 rows behind the existing type/date
filters) had no text search and no way to hide a column — everything else on the list
(accounts breakdown, unresolved-symbols panel) is small enough not to need this.
Frontend-only: both features filter/hide client-side over data already fetched, no new
API surface.

**Search** is a plain text field added to each table's existing filter row, filtering
client-side: symbol/name for positions, comment/symbol/account for transactions. On the
Transactions page it deliberately only narrows what the *table shows* — the stat tiles
above it (`net dividends`, `fees`, `realised P&L`) keep reflecting the server-side
type/date-filtered set, not the further text-narrowed one, the same way `PositionsTable`'s
existing account filter has never recomputed anything outside the table either. Verified
live: typing "asml" narrowed the transactions table to 15 matching rows while the stat
tiles stayed unchanged.

**Configurable columns** are the first dropdown/popover of any kind in this app — nothing
like it existed (the closest precedent, `details.raw` in `ImportPanel.tsx`, is a plain
disclosure for a debug dump, not a menu). New `useHiddenColumns(storageKey)` hook
(`frontend/src/hooks/`, a new directory) persists the *hidden* column keys — not the
visible ones — to `localStorage`, mirroring the exact read-once/write-on-change shape
`i18n/index.tsx` already established for the locale preference: a column added later
defaults to visible for existing users instead of silently disappearing. New
`ColumnPicker.tsx` component (a `<details>` checklist, visually modelled on the existing
`.symbol-suggestions` absolute-positioned panel used by the manual-position symbol
autocomplete, so it reads as the same visual language rather than a new one) is shared by
both tables. Each optional `<th>`/`<td>` pair is wrapped in `{!hidden.has(key) && (...)}`;
the identity column (instrument / date) and the trailing actions column are never
offered and always render. On the Transactions table this wrapping had to be applied
identically to *both* the editing-row and non-editing-row branches — verified live by
hiding "Account", starting an inline edit, and confirming both the header and the
edit-mode row still had exactly 6 matching cells (down from 7), so a column disappearing
mid-edit can't desync the two `<tr>` shapes.

Verified live end to end on both pages: search narrows correctly, hiding columns keeps
header/row alignment intact, hidden columns survive a full page reload
(`localStorage` round-trip), and toggling them back restores the original layout — no
console errors at any step. `npx tsc --noEmit` and `npm run lint` clean; backend untouched,
343 passed unaffected.

## Bug 3j.1 — An unresolved symbol could not be removed without first "correcting" it (2026-08-18)

Reported directly: the "Symbol without a mapping" panel offered only `MappingCell`'s
"corriger" flow — no way to get rid of a bad entry that isn't a real, correctable
instrument at all. Confirmed against the real database: `DHHDH` (instrument id 109) had
zero rows in `positions`/`lots`/`transactions`/`watchlist_items` — a fully orphaned
`Instrument`, almost certainly a parsing artefact, with a stray `symbol_overrides` row
from an earlier attempt to fix it (`provider_symbol = "BFNBFBFNGNGNGNGNGN"`, plainly not
a real Yahoo symbol).

**New `DELETE /api/portfolio/instruments/{id}`** (`routers/portfolio.py`). Refuses with
400 whenever the instrument still has a `Position`, `Lot`, `Transaction`, or
`WatchlistItem` referencing it — the same concern `models.py`'s "deleting an instrument
must not silently erase historical lot data" comment already documents for `Lot`, now
enforced at the API boundary instead of only being a comment. When nothing references it,
deletes the instrument's `SymbolOverride` row (if any) alongside the instrument itself, so
a second bad attempt at the same broker symbol doesn't inherit stale garbage.

Frontend: a "Delete" button added next to "corriger" in `UnresolvedPanel.tsx`'s per-row
actions — fixing and deleting are now both offered, not just fixing.

Backend: 3 new tests in `TestDeleteInstrument` (`test_api.py`) — deletes a genuinely
orphaned instrument, refuses when a position still references it, 404 for an unknown id.
Full suite green at 346 passed. Verified live against the real database: deleted the
actual `DHHDH` row that prompted this (confirmed gone via direct SQL, `symbol_overrides`
row gone with it), confirmed the safety guard by attempting to delete a real held
instrument (`ASML.NL`) and getting the expected 400, and reproduced the original bug from
scratch (create a manual position, delete only the position, leaving the instrument
dangling and unresolved) to confirm the new "Delete" button in the actual "Symbol without
a mapping" panel removes it and the panel disappears once nothing unresolved remains — no
console errors.

## Decision 3k.1 — Lightweight local hardening instead of encryption at rest (2026-08-18)

Item #8 of the original list, "sécurité des données." Audited what actually exists today:
the SQLite DB (`data/stock_analyst.db`) was `644` (world-readable), `.env` (provider API
keys, plaintext, "Decision 2.7") was `664`, and the backend has **zero authentication of
any kind** — CORS restricts what a browser's JS can read back, but does nothing against a
plain script or another machine, so the only real boundary was "uvicorn happens to default
to binding `127.0.0.1`." Presented the user with the real trade-off before building
anything: lightweight permission/network hardening (no new dependency, no friction) versus
full SQLCipher encryption-at-rest (a new compiled dependency, a data migration, and a
passphrase prompt on every single app start, for a personal single-user tool whose DB has
never left the local disk). **User chose lightweight hardening.**

**File permissions**, tightened wherever the file is created or rewritten, not just once:
`get_settings()` (`config.py`) chmods `DATA_DIR` to `700` and either `.env` location to
`600` every time it runs (cheap — it's `@lru_cache`d, so this is once per process, and
retroactively fixes a pre-existing file's permissions on the next startup); `init_db()`
(`db.py`) chmods the SQLite file to `600` after `create_all`; `update_api_keys()`
(`routers/settings.py`) chmods `.env` to `600` again after every rewrite, since a plain
`open(path, "w")` on a not-yet-existing file inherits the process umask (typically
group/world-readable) — the very rewrite path that reintroduces the DHHDH-symbol-override
kind of bug is also the path most likely to leave the file loosely permissioned again.

**Loopback-only middleware** (`main.py`): refuses any request whose client isn't
`127.0.0.1`/`::1` with a 403, so an accidental `--host 0.0.0.0` (e.g. "let me check my
portfolio from my phone") can't silently turn a local-only, unauthenticated API into one
reachable by anything on the LAN. `"testclient"` is allow-listed too — Starlette's
`TestClient` always presents that literal string as its client host (its in-process ASGI
transport convention), which can never appear on a real socket, so allow-listing it costs
nothing against a real attacker. Tested with `httpx.ASGITransport(app, client=(host,
port))` instead of `TestClient` (which can't be pointed at an arbitrary host at all in the
installed version) — no new test dependency, `asyncio.run()` drives the one async call
directly rather than pulling in `pytest-asyncio`.

**`.gitignore`** widened from `data/*.db`/`data/*.sqlite` to `data/*.db*`/`data/*.sqlite*`
— the exact-suffix glob would have missed SQLite's WAL/SHM/journal sidecar files
(`stock_analyst.db-wal` etc.) had journal mode ever changed; this app doesn't use WAL
today, so it was a latent gap rather than an active leak, cheap to close regardless.

3 new tests (`test_loopback_middleware.py`) plus the existing suite unaffected — 349
passed. Verified live: `data/stock_analyst.db` and `.env` are `600`/`700` on disk after a
normal run; the real dev backend (auto-reloaded) still answers `127.0.0.1`/`localhost`
requests normally through the Vite proxy with no console errors, confirming the loopback
guard doesn't break the app's own normal traffic pattern.

## Decision 3l.1 — Surface rate-limit exhaustion on the Settings page (2026-08-19)

Asked directly: add visibility into API "épuisement" (rate-limit exhaustion) somewhere.
Turned out this was mostly already built and just never wired up: `GET /api/prices/
providers` (`routers/prices.py:117-151`) already computes a real, per-provider
`cooling_down` flag (backed by `Cooldown` in `providers/base.py:180-207` — an in-memory,
timestamp-based backoff that clears itself ~15 minutes after a provider raises
`RateLimited`) plus `serves_holdings`/`total_holdings` coverage — but the frontend never
called that endpoint. `Settings.tsx` only ever fetched the unrelated `/api/settings/
providers` (key configuration: name/description/enabled/signup link), so the exhaustion
signal existed server-side and was simply invisible.

No backend work needed — just wired the existing endpoint into the existing page. New
`api.getProviderAvailability()` (`client.ts`) + `ProviderAvailability` type (`types.ts`)
fetch it alongside the calls `Settings.tsx` already made (on mount and after saving keys,
since a newly-set key can flip a provider from disabled to enabled or clear whatever
cooldown it inherited). A shared `ProviderAvailabilityInfo` component renders a red
"Rate-limited" badge when `cooling_down` is true, plus a "{served}/{total} of your
holdings" coverage note — both keyed providers (in their existing cards) and the keyless
ones (Yahoo, Boursorama, Frankfurt, Stooq, Eoddata, Finviz — previously just a
comma-joined name list with zero status info) now show this.

No actual request-count/quota-remaining tracking exists anywhere in this app (only
hardcoded free-tier numbers in description strings, e.g. "FMP: 250 req/day free") — this
surfaces the real binary "is it backing off right now" signal that already existed, not a
new "47/250 used today" counter, which would need new tracking state and is a materially
bigger feature if ever wanted later.

Verified live: real `GET /api/prices/providers` data renders correctly with no cooldowns
currently active (all badges correctly absent); confirmed the badge itself renders with
the right text/tooltip/red styling by temporarily patching `window.fetch` in the browser
to return `cooling_down: true` for Yahoo — badge appeared exactly on that provider, no
badge on any other, no console errors; unmocked-provider (`undefined` availability) case
also confirmed to render nothing rather than crash. `npx tsc --noEmit`/`npm run lint`
clean; backend untouched, 349 passed unaffected.

## Decision 3m.1 — Real per-provider quota counters, not just the cooldown badge (2026-08-19)

Follow-up to "Decision 3l.1": the user actually wanted to know how many requests are
left against each provider's real free-tier limit, not just whether one is currently
backing off. No usage counter existed anywhere — only hardcoded description strings
like "FMP: 250 req/day free".

**Scope, cut down from all 15 providers to 7**: `twelvedata`/`fmp`/`tiingo`/`barchart`/
`intrinio`/`eodhd` (daily) and `marketstack` (monthly) have a documented, meaningful
limit to show "X of N" against. `polygon`/`alpha_vantage` are 5-requests-**per-minute**
— a number that's stale the instant anyone reads it on a settings page, which is what
`Throttle`/`Cooldown` already handle internally — excluded on purpose. The 6 keyless
providers have no documented quota anywhere, even in their own files: nothing to show
a denominator against, so they keep only the existing cooldown badge.

**Counting point had to be a callback, not `result.attempts`.** `ProviderChain.
fetch_daily`'s cooldown-skip (`providers/base.py:226`, no real network call) and a
real call that also gets rate-limited (`:239`) both produce an identical
`Attempt(provider.name, "rate_limited")` — confirmed by the existing
`test_a_throttled_provider_is_not_asked_again_immediately` test
(`throttled.calls == 1` after 5 rounds). `result.attempts` genuinely cannot
distinguish "skipped" from "asked again and refused" after the fact. Added an
optional `on_attempt: Callable[[str], None] | None = None` to both `fetch_daily` and
`fetch_quote`, invoked only immediately before the real call — default `None`, zero
behavioural change for every existing caller/test.

**New `ProviderUsage` table** (`provider`, `period_key`, `count`) — `period_key` is a
plain calendar string (`"2026-08-19"` or `"2026-08"`), so a new period just has no row
yet; nothing to reset or prune on a schedule. New `prices/provider_usage.py`:
`QUOTA_LIMITS` + `record_usage(db, provider_name)`, which **commits immediately**
rather than flushing — `enrich_sectors` (`routers/portfolio.py`) only calls its own
`db.commit()` when an instrument was actually enriched, so a flush-only increment
would be silently discarded on a request where every FMP profile lookup came back
empty.

**Three call sites wired, all already had `db` in scope**: `prices/service.py::
refresh_instrument` (passes the callback straight into `chain.fetch_daily`);
`prices/quote_service.py::fetch_live_quotes` (gained an `on_attempt` param, threaded
from `routers/portfolio.py::refresh_live_prices`); and `enrich_sectors`/
`symbol_search` in `routers/portfolio.py`, which call `FmpProvider.fetch_profile`/
`search_by_name` **directly**, bypassing `ProviderChain` entirely — `record_usage(db,
"fmp")` added right after each, since all of FMP's endpoints draw from the same
250/day bucket. `symbol_search` had no `db` parameter at all ("Read-only, no DB access
needed") — added one, purely to record the request.

**Known limitation, stated plainly rather than hidden**: counting starts from zero
the moment this shipped. Any real usage against a provider from before today is
invisible — "used today" undercounts on day one until the next UTC midnight. Same
bootstrap gap `Cooldown` already has; not solvable without an out-of-band way to ask
a provider its own usage, which free tiers don't expose.

Backend: 4 new tests in `TestOnAttemptCallback` (`test_providers.py` — fires once on
a real call, never on a cooldown-skip or a `can_serve()`-skip, fires via `fetch_quote`'s
`fetch_daily` fallback too) plus 6 in `test_provider_usage.py` (period-key formatting,
row creation, accumulation, untracked-provider no-op, monthly vs. daily keying,
independent per-provider counts). Full suite green at 360 passed. Verified live
against the real running backend: called `GET /api/portfolio/symbol-search` three
times for real, confirmed `provider_usage` gained a `fmp` row with `count=3` and
`period_key` correctly on the *UTC* date (not local, which had already rolled to the
next day); `GET /api/prices/providers` showed `quota_used: 3` for fmp and `null` for
Yahoo; Settings page rendered "3/250 used today" on the real card, and (via a
temporarily patched `window.fetch` returning `quota_used: 230`) confirmed the
near-limit styling turns the note red/bold past 80% — no console errors at any step.

## Decision 3m.2 — Track Polygon and Alpha Vantage too, per-minute (2026-08-19)

Reported directly after 3m.1 shipped: Polygon and Alpha Vantage's cards still showed
only coverage, no usage — the deliberate exclusion (a per-minute figure being "stale
the instant anyone reads it") wasn't what the user wanted; they wanted the number
regardless of how fast it moves. Reversed that call.

Added both to `QUOTA_LIMITS` (5/minute each) and a third `period_key_for` branch —
`"%Y-%m-%d %H:%M"` — so a `ProviderUsage` row for a per-minute provider just rolls
over to a fresh key every sixty seconds, same "no row yet = the period reset" pattern
"day"/"month" already use, no special-cased reset logic needed. Widened
`ProviderUsage.period_key` from `String(10)` to `String(16)` to fit the longer key
(SQLite doesn't actually enforce VARCHAR length, so this was a documentation fix, not
a real migration concern). Frontend gained a third `settings.periodMinute` label
("cette minute"/"this minute"/"w tej minucie").

2 new tests (minute-key formatting, Polygon keys by minute not day). Full suite green
at 362 passed. Verified live: `GET /api/prices/providers` showed `quota_used: 1` for
Polygon at one point during testing (real activity from browser use), then a second
check less than a minute later — after the minute's key had naturally rolled over —
showed `0/5 used this minute` on both cards, demonstrating the reset actually happens
without any cleanup job. No console errors.

## Decision 3n.1 — Parallelize the price refresh across instruments, not across providers (2026-08-19)

Asked directly to speed up refreshes. Two ways to parallelize were real options: race
several providers in the fallback chain for one instrument and keep whichever answers
first, or process several *different* instruments concurrently, each still trying its
own provider fallback chain in order. The first wastes quota on providers whose answer
turned out not to be needed — exactly what `can_serve()`'s "quota spent to learn
something already known" design already exists to avoid, and in direct tension with
the usage tracking just built (3m.1/3m.2). **User picked the second, explicitly.**

**Nothing about this was safe to just do**, though — three pieces of previously
single-threaded state needed fixing first:
- `Throttle`/`Cooldown` (`providers/base.py`) were unsynchronized mutable state,
  correct only because the refresh loop had always been strictly sequential. Both now
  hold a `threading.Lock()` around their check-then-act bodies. For `Throttle`,
  holding the lock *through* the `sleep()` is the actual point, not just protecting
  the read-modify-write: when two threads want the same provider at once, one must
  wait its turn while the other proceeds — that *is* what "space calls to one
  provider apart" means under concurrency. Verified live: a forced refresh of the
  real 37-instrument portfolio routed 23 calls through Polygon (12s/request, 5/min)
  and they landed spread across four different one-minute buckets in
  `provider_usage` (9/5/5/4) rather than bursting — the lock held.
- `record_usage` (`prices/provider_usage.py`) gets its own lock: two worker threads
  incrementing the same provider's counter at once is a textbook lost-update race
  (both read count=N, both write N+1). Proven closed with a real test — 20 threads,
  each its own DB session, incrementing "fmp" concurrently — final count is exactly
  20, not less.
- A worker thread cannot reuse the session or ORM objects the request's own thread
  loaded — SQLAlchemy `Session`s aren't thread-safe. New `_refresh_instrument_threaded`
  (`prices/service.py`) opens its own session **bound to the caller's own engine**
  (`sessionmaker(bind=db.get_bind())`), not a hardcoded import of the production
  `SessionLocal` — the test suite overrides `get_db` to point at an isolated
  database via `app.dependency_overrides`, and a worker that quietly reconnected to
  the real one instead would silently write somewhere no test or the rest of the
  request was ever looking (caught this exact bug: the first pass imported
  `SessionLocal` directly and 10 tests failed with `updated: 0` because the writes
  landed in the wrong database entirely).

**A second, subtler test-infrastructure issue**: several test fixtures built their
in-memory SQLite engine with `poolclass=StaticPool` — deliberately, so every session
shares the one connection an in-memory `:memory:` database needs to stay visible
across separate `Session` objects. That single shared DBAPI connection is not safe
to drive from multiple threads at once (`sqlite3.InterfaceError: bad parameter or
other API misuse`), regardless of any lock at the SQLAlchemy layer — it's a lower-level
violation than anything Throttle/Cooldown/record_usage's locks touch. Fixed by
switching the affected fixtures (`test_prices_api.py`, `test_price_service.py`,
plus a `file_engine` fixture added to `test_provider_usage.py` for its own
concurrency test) from `StaticPool` + `:memory:` to a real temp file via pytest's
`tmp_path` — genuinely separate pooled connections per session, exactly matching how
production's file-based engine already behaves (confirmed empirically: production's
`QueuePool` hands out distinct underlying connections; `StaticPool` does not, by
design). `db.py` also gained `"timeout": 30` in `connect_args` (was unset, so the
DBAPI default 5s) — SQLite still serializes writers at the file level even with
separate connections, and concurrent per-instrument commits deserve more room to
queue than 5s.

**The parallel loop itself** (`prices/service.py::_refresh_many_locked`,
`prices/quote_service.py::fetch_live_quotes`, both restructured identically): a
bounded pool (`MAX_CONCURRENT_REFRESHES = 4`, kept modest — the whole portfolio is
~40 instruments across a handful of providers, and a bigger pool just means more
*different* providers get hit within the same second no matter how well each is
individually throttled) that refills a slot each time a future actually *completes*,
not in a plain submit-then-budget-check loop — `executor.submit` returns instantly,
so checking the time budget in a submit loop would barely ever trigger before
everything was already queued. Checking again at each real completion keeps the same
"budget bounds what starts, not what's already running" character the sequential
version had.

**One deliberately-accepted behavioral consequence**, caught by an existing test
that stopped being valid rather than by a bug: `test_work_is_kept_when_a_later_
instrument_is_rate_limited` relied on instrument A always being processed — and
committed — strictly *before* instrument B failed, in the same batch, sharing one
provider. Under real concurrency that ordering isn't guaranteed: if B's failure
starts the provider's cooldown before A's own cooldown check runs, A can get skipped
too, even though A itself was never rate-limited. This is inherent to true
concurrency over a shared rate-limited resource, not a defect — the same thing would
happen to any concurrent client. Rewrote the test (`test_work_already_done_survives_
a_later_rate_limit`) to check the actual guarantee — a completed, committed run's
data survives a *later* run's failure — across two separate `refresh_many` calls
instead of a race inside one.

`RefreshProgress.current_symbol` now means "whichever instrument most recently
finished," not "the one in flight" — cosmetic, not fixed here, flagged so it doesn't
read as an unnoticed bug later.

10 new/changed tests: `Throttle`/`Cooldown` real-threading serialization proofs
(`test_providers.py`), the `record_usage` lost-update-race proof
(`test_provider_usage.py`), a 12-instrument concurrent `refresh_many` correctness
test and the rewritten rate-limit test (`test_price_service.py`), and a new
`test_quote_service.py` (the live-quote round had no tests at all before this).
`FakeProvider.calls` also gained its own lock — the test double had no self-throttle
the way every real provider does, so a shared-instance concurrency test would have
been flaky on the test harness's own account, not a real signal. Full suite green at
368 passed, run 3× with no flakes plus 5 more repeats scoped to just the
concurrency-sensitive files.

**Live verification against the real portfolio (37 held instruments)**: a forced
history refresh completed in ~309s (the 300s budget plus overhead) with **37 updated,
0 failed, 1 remaining** — correctly reported, not silently dropped. `provider_usage`
showed real, plausible call distribution (Polygon's 23 calls spread across four
distinct one-minute buckets, matching its 12s/request throttle). The live-quote round
was watched mid-flight in the actual browser: the RefreshPanel's progress bar
advanced steadily and correctly through "Step 2/2 — Live quotes, N/37 processed ·
SYMBOL" exactly as before, no console errors at any point. No `database is locked`
errors, no stuck cooldowns, no lost updates — everything the new locks/session
handling were built to prevent.

## Decision 3n.2 — Doubled concurrency, then found the real remaining bottleneck was provider order (2026-08-19)

Asked to speed refreshes up further after 3n.1. Bumped `MAX_CONCURRENT_REFRESHES` from
4 to 8 (user's explicit call, presented with the trade-off — more simultaneous
connections to free tiers, a bit more SQLite write contention, no additional quota
waste since Throttle still paces each provider individually regardless of pool size).

**The live re-test showed the pool size wasn't the real constraint any more.** A
forced refresh with the wider pool took *longer* in absolute terms (361s vs 3n.1's
309s) despite completing strictly more work (38/38 vs 37/38 remaining). Root cause,
confirmed from `provider_usage`: 24 of 38 instruments (63%) were served by Polygon,
whose own 12s/request throttle is a hard floor no pool size changes — Polygon alone
accounted for ~288s of unavoidable serialised time. User confirmed this matches their
actual daily experience, not just today's testing: a normal "Actualiser" click
regularly takes several minutes.

**Why so much of the portfolio lands on Polygon**: `registry.py`'s fallback order had
it as slot #2, immediately after Yahoo — and Yahoo (documented repeatedly in this
DEVLOG as rate-limiting after roughly four rapid requests) realistically only serves
a handful of instruments before cooling down for the rest of any given refresh. Every
US holding Yahoo couldn't reach fell straight to Polygon. Checked `GET /api/prices/
providers`: Twelve Data reports the exact same `serves_holdings: 23` as Polygon for
this portfolio — fully substitutable coverage — but throttles to 8s/request against
an 800/day quota, versus Polygon's 12s against a much tighter 5/minute. Twelve Data
was slot #6 purely because it was added to the registry earlier in the project's
history than Polygon's slot assignment, not from any documented reliability
comparison (checked `DEVLOG.md` for one — "Decision 2.3"/"2.6" call Twelve Data
"recommended, not merely optional," nothing suggests Polygon was preferred over it).

**Swapped their order** (`registry.py`) — Twelve Data now tried right after Yahoo,
Polygon third. Zero new logic, an ordering-only change, covered by the existing full
test suite (368 passed) plus a live check that `GET /api/prices/providers` reports
the new order after the dev server's auto-reload. Expected effect on this portfolio's
worst case: the ~23 shared instruments now serialise at 8s instead of 12s each when
Yahoo is unavailable (~184s instead of ~276s for that share alone), and hit a
per-minute cap only a third as restrictive.

Not re-verified with another full forced refresh — two already run today for 3n.1/
3n.2 testing is enough real quota spent for one day; the next normal refresh (the
user's own, not a forced test) is the honest measurement.

## Decision 3o.1 — Persist the last live quote, so a reload doesn't lose it (2026-08-19)

Traced from the user comparing our displayed market value against the real XTB
platform and seeing a real gap (~159€ on this portfolio). Root cause, confirmed with
real data: `quote_service.py`'s live quotes were deliberately never persisted (kept
in memory, one HTTP response's lifetime only — correct, so they'd never corrupt
`PriceBar`'s daily-close semantics) — but that meant the instant a user reloaded the
page or came back later, the app fell straight back to whatever daily close was
cached, which can genuinely be 1-2 days stale purely from free-tier provider lag
(confirmed live: Polygon hadn't posted AMD's Aug-18 close yet when Twelve Data
already had it for AAPL). A successful live refresh looked, seconds later, like it
had never happened.

**New `LastQuote` table** (`models.py`) — one row per instrument, no history, just
the most recent live price/provider/timestamp. Kept separate from `PriceBar` on
purpose, same reasoning `quote_service.py`'s docstring already gives for not writing
live quotes into daily bars in the first place.

**Write side**: `refresh_live_prices` (`routers/portfolio.py`) now calls
`_save_last_quotes(db, live_quotes)` right after `fetch_live_quotes` returns —
upserts each instrument's row, one commit. `fetch_live_quotes`/`quote_service.py`
itself is untouched — it stays exactly as before (no DB coupling added there), all
the new persistence logic lives in the router, which already had `db` and already
received the result.

**Read side**: `_resolve_current_price` gained a third tier between "this request's
own fresh live quote" and "cached daily close" — a persisted `LastQuote`, but only
used when it is **at least as recent as the cached bar** (`saved_quote.fetched_at >=
latest_bar.fetched_at`). Without that comparison, a live quote from yesterday could
outrank a daily bar that updated overnight — backwards. Reuses the `price_source =
'live'` label for a persisted-but-not-brand-new quote rather than inventing a fourth
state: what matters to the label is "sourced from a live quote round" vs "sourced
from the daily-bar cache," not how many minutes old it is.

4 new tests (`test_last_quote.py`, using the same real-file-engine `client` fixture
pattern as `test_prices_api.py`, for the same StaticPool-concurrency reason): a live
quote survives a subsequent plain GET with no live_quotes of its own; a second
refresh updates the existing row rather than duplicating it; a `PriceBar` fetched
*after* a saved quote correctly outranks it; an empty live-quote round (nothing
enabled) saves nothing. Full suite green at 372 passed.

Verified live against the real database and running app: inserted one realistic
`LastQuote` row directly (avoiding a full 4+-minute real API round on top of several
already run today for 3n.1-3n.2), reloaded the real Portfolio page with no refresh in
flight, and confirmed the browser displayed exactly that persisted price with
`price_source: "live"` — no console errors. Row removed afterward so no synthetic
data was left in the user's real portfolio.

## Decision 3p.1 — Realized P&L attribution: instrument effect vs currency effect (2026-08-19)

Phase-2 open item: XTB's export gives an Open/Close Conversion Rate for every
closed trade, but the app only ever parsed it into `raw` and never used it. Ask,
confirmed with the user: split each closed trade's realized P&L into how much came
from the stock's own price moving versus how much came from the exchange rate
moving since the trade opened. Scoped to **closed trades only** — XTB only reports
these rates for closed positions; unrealized/open-position attribution would need a
different mechanism (the historical FX range lookup already built for the value
chart) and is deliberately left for later.

**No schema change.** `open_fx_rate`/`close_fx_rate` were already parsed by
`xtb_import.py` and land in every closed trade's `Transaction.raw`/`Lot.raw` — just
never read back out. Recovered at serve time with the exact pattern
`_account_from_raw` already established: `_fx_rates_from_raw(raw)` scans
`raw.items()`, matches headers via the parser's own `_match_column` (language-
independent). The open price isn't on `Transaction` at all (only close price) — it's
on the matching `Lot` (`lot_type=CLOSED`, same `external_id`), batch-fetched once per
`list_transactions` request via `_closed_lots_by_external_id`, not per row.

**Formula** (`_closed_trade_effects`): `instrument_effect = (transaction.price -
lot.open_price) * transaction.quantity * open_fx_rate` — pure price P&L, FX held
fixed at the open-day rate. `currency_effect = transaction.amount -
instrument_effect` — deliberately a **residual** against the real broker-reported
`amount`, not an independent FX computation, so the two numbers always reconcile
exactly to the trade's real P&L. Trade-off stated plainly in the UI ("Currency &
fees", not "Currency effect"): the residual also absorbs commission, swap and
rounding, since nothing in this codebase reconciles exactly how XTB nets those into
`net_pl`. Returns `(None, None)` when data is missing — no matching lot, no
conversion-rate columns in `raw`, or `open_fx_rate` of `0` — same "unknown stays
None, never a guessed zero" convention used everywhere else.

**Real-data finding during live verification, not anticipated by the plan**: of 249
closed trades in the real portfolio, only 187 are resolvable. 26 have no matching
`CLOSED` lot at all; another 36 have a matching lot but blank conversion-rate columns
in `raw`. Both gaps are concentrated in CFD closes (Core S&P Small-Cap, FRA40,
BITCOIN, ...) — XTB doesn't report conversion rates for CFDs, which are already
margin-traded in account currency, and apparently doesn't always produce a matching
closed-lot record for them either (a pre-existing lot-matching characteristic,
unrelated to this feature, not investigated further). The per-row math is exact on
every resolvable row (`instrument_effect + currency_effect == amount`, checked
directly against the real DB), but the plan's original assumption — that the stat
subline's two totals would sum to the existing "Realised P&L" figure — does not hold
here: 3,162.89 + (-692.61) = 2,470.28 against a portfolio-wide realized P&L of
465.54, because the 62 unresolved trades (net -2,004.74) are excluded from the split
but included in the total. Fixed by adding `closed_trades_with_effect`/
`closed_trades_total` to `TransactionSummaryOut` and rendering a coverage note next
to the subline whenever it's a partial count ("187 of 249 closed trades — the rest,
mostly CFDs, have no conversion-rate data to split") instead of letting the UI imply
a reconciliation that isn't there.

**API**: `TransactionOut` gains `instrument_effect`/`currency_effect` (populated only
for `CLOSED_TRADE` rows). `TransactionSummaryOut` gains `total_instrument_effect`/
`total_currency_effect` plus the two coverage counts above.

**Frontend**: two new hideable columns in `Transactions.tsx`, wired through the
existing `ColumnPicker`/`useHiddenColumns` (`Decision 3i.1`) — `—` for any row that
isn't a resolvable closed trade. New subline under "Realised P&L" with the effect
split and, when partial, the coverage note.

11 new/extended backend tests: `_fx_rates_from_raw` parses English and French
headers, returns `(None, None)` for missing raw / no conversion columns;
`_closed_trade_effects` reconciles exactly on a realistic divergent-rate fixture (a
new `closed_row(open_fx_rate=..., close_fx_rate=...)` parameter in `conftest.py`,
since existing fixtures hardcoded both rates to `1.0` and had never exercised
non-identity FX math), returns `None` for no matching lot / no rate / zero rate; one
end-to-end test now covers a resolvable closed trade, a dividend (`—`), and an
unresolved CFD-style closed trade in the same request, asserting both the per-row
split and the summary's coverage counts. Full suite green at 381 passed.

Verified live against the real database and running app: confirmed via direct API
calls and the real database that per-row arithmetic reconciles exactly (e.g. the
Canadian Pacific close: amount 2.83 → instrument_effect 12.22, currency_effect
-9.39); opened the Transactions page and confirmed the two new columns appear in the
column picker (on by default), real closed trades (CP.US, NESN.CH) show non-1.0-
derived numbers, dividend/withholding-tax/buy/sell rows all show `—`, the new stat
subline appears with the coverage note, and there are no browser console errors.

## Decision 3q.1 — Finally remove Stooq: Decision 2.1 was never actually carried out (2026-08-19)

Phase-2 open item: `providers/registry.py`'s module docstring has claimed since early
in the project that "Stooq was the original fallback and has been removed" (see
Decision 2.1: its export endpoint started answering with a JavaScript proof-of-work
challenge instead of CSV, and defeating that would mean circumventing bot detection,
which this project won't do). The code disagreed — `StooqProvider` was still imported
and registered at position 12 of 15 in the live chain, and every later mention of
"the keyless providers" (Bug 2b.7, Step 2b.10, `provider_usage.py`) continued to list
Stooq as one of the six always-on sources. Decision 2.1 was a real decision that
simply never got implemented in code, and nobody caught the drift since — it had zero
test coverage (mocked or live), so nothing would have failed either way.

**Checked what it's actually doing today, live, before touching anything**: the URL
`StooqProvider.fetch_daily` actually calls (`stooq.com/q/export.php`) now returns a
plain `404 Not Found` — the endpoint itself is gone, not just walled. The URL Decision
2.1 originally tested (`stooq.com/q/d/l/`) still serves the exact same JavaScript
proof-of-work challenge found back then, confirming the original call was correct and
nothing has changed for the better since. Cross-checked against the real database:
zero instruments have `verified_provider = 'stooq'` and zero `price_bars` rows have
`provider = 'stooq'` — consistent with it having contributed nothing, ever, in this
deployment. Safe to remove outright, no migration or backfill concern.

**Fix**: removed the import and chain entry from `registry.py` (renumbered the
trailing position comments), deleted `providers/stooq.py` entirely — following the
same precedent already set for IEX Cloud/World Trading Data/Quandl (Bug 2.5): a
confirmed-dead provider gets its file deleted, not left around disabled. Updated
every comment/docstring that listed Stooq among the active keyless providers
(`config.py`, `routers/settings.py`, `prices/provider_usage.py`,
`Settings.tsx`) to the real remaining five (Yahoo, Boursorama, Frankfurt, Eoddata,
Finviz). Also deleted the `provider.description.stooq` i18n key in all three
languages — it was already dead code before this change (the frontend renders
`provider.description` straight from the API response, never through an i18n
lookup keyed by provider name; the other `provider.description.*` keys have the
same problem but are out of scope here).

No new tests needed — there's no behavior left to test; removing a provider that
contributed nothing is a pure deletion. Full suite stays green (381 passed),
`tsc`/lint clean.

Verified live: `GET /api/settings/providers` on the real running app returns 14
providers with no `stooq` entry (down from 15); the Settings page's "Also active, no
setup needed" line now reads "yahoo, boursorama, frankfurt, eoddata, finviz" with no
stray Stooq row or broken rendering; no browser console errors.

## Decision 3r.1 — Phase 3: the scoring engine (Value / Growth / Quality / Technical) (2026-08-20)

DEVLOG's own roadmap flagged a blocker before writing `scoring.yaml`: decide whether
the score follows one investing philosophy or blends several, since named
methodologies (value, growth, quality/momentum, technical, sentiment) don't agree
with each other. Resolved with the user: **blended pillars** — Value, Growth,
Quality, Technical (sentiment/news stays Phase 6's Perplexity synthesis, kept
separate per Decision 0.3) — each pillar weighted, missing data dropped and
weights renormalised, extending Decision 1.2's rule ("a pillar without data is
dropped") down to the metric level too.

**Wiring up dormant infrastructure.** Phase 3a (2026-08-13) already built
`EdgarProvider` — fetching and normalising real SEC filings, three real bugs found
and fixed live (wrong tag per series, foreign-filer currency/taxonomy, ticker
collisions misattaching one company's financials to another) — but it was never
instantiated outside tests: nothing persisted its output, no endpoint served it.
This phase wires it up. New `Fundamental` table (mirrors `PriceBar`'s caching shape,
keyed on instrument+concept+fiscal_year) and `app/fundamentals/service.py`
(sequential, not thread-pooled like price refresh — ~23 US filers × EDGAR's 0.5s
throttle ≈ 12s, no concurrency machinery justified at this scale). Ticker/
expected_name calling convention follows `EdgarProvider.resolve()`'s documented
contract exactly (`broker_symbol` root, `expected_name` only for non-US instruments)
— the same discipline that avoided Bug 3a.3's ticker-collision class.

**Deliberately no `instruments` schema change.** The user had just chosen Phase 3
over introducing Alembic; adding fundamentals-bookkeeping columns to `Instrument`
right now would be exactly the kind of hand-written `ALTER TABLE` that choice was
meant to defer. "Already checked, and when" is answered by querying the new
`Fundamental` table's own `fetched_at` instead — no new column needed. Also no
`Score` table: a score is a cheap derivation over already-cached data, computed live
on every `GET` (same posture as `_resolve_current_price`), not itself persisted.

**Metrics** (`app/scoring/metrics.py`), named methodologies rather than invented
ratios, each with a hand-checkable linear or binary threshold in `scoring.yaml`
(first YAML consumer in the app, Pydantic-validated so a typo fails at load, not
mid-request): Value (Graham/Buffett — P/E, P/B, FCF yield, Debt/Equity), Growth
(revenue/net-income CAGR plus an O'Shaughnessy-style growth-consistency ratio),
Quality (a 5-of-9 Piotroski-adapted checklist — the concepts this app has don't
cover current assets/liabilities, so the working-capital signals are omitted),
Technical (Faber's 200-day trend filter, Jegadeesh & Titman 12-1 momentum, a
50/200 golden-cross signal — from cached `PriceBar` closes only, works for STOCK
and ETF alike, CFDs excluded entirely). Value's P/E, P/B and FCF-yield metrics are
the only ones needing currency conversion (price vs. filing currency can differ —
ASML trades and reports in EUR, but nothing guarantees that in general); Growth and
Quality are pure fundamentals-to-fundamentals ratios needing no FX at all, kept that
way deliberately to minimise FX-dependent surface area. A missing FX rate drops only
the metrics that needed it, not the whole pillar.

**API**: `POST /api/scoring/fundamentals/refresh` (same eligibility shape as prices'
refresh, every held instrument passed through — ETFs/CFDs report `not_applicable`
rather than being silently excluded, so the report reflects the whole portfolio) and
`GET /api/scoring/scores` (composite + full per-pillar/per-metric breakdown, raw
value and drop reason included for every metric — a surprising score must always be
traceable to what produced it, the same discipline `AnnualFigure.tag` and
`LastQuote.provider` already apply elsewhere).

**Frontend**: a `ScoreBadge` in the positions table, same visual pattern as the
existing `PriceStatusBadge`, click-to-expand into a `ScoreDetailRow` showing every
pillar/metric with its raw value, score and (when dropped) why. A
`FundamentalsRefreshButton` next to the existing price-refresh panel — no progress
polling, unlike prices, since a full run is seconds at this portfolio's scale.

**Bug caught during live verification, not by any test**: `formatNumber(value, 0)`
silently produced up-to-4-decimal output ("97.1083" instead of "97") — the shared
i18n helper only ever actually branched on `digits === 2` vs. anything else,
including `0`, falling through to the "up to 4 decimals" formatter meant for share
quantities. Not a scoring bug, a pre-existing footgun in `i18n/index.tsx` that this
feature was the first caller to actually hit (no prior caller had ever passed
`digits: 0`). Fixed by adding a real `upToZero` `Intl.NumberFormat` branch rather
than working around it in the new components — the two existing call sites
(`digits: 2` default, `digits: 4` for share quantities) keep their exact prior
behaviour.

56 new backend tests (metrics with hand-checked numbers — e.g. P/E of exactly 15 →
100, of 45 → 0; missing-concept/negative-earnings/missing-FX-rate each drop only
their one metric; full pillar/composite renormalisation; a fake-EDGAR-provider
fundamentals-service suite covering the ticker/expected_name convention and outcome
mapping; end-to-end API tests). Full suite green at 436 passed. `tsc -b`/lint clean
— worth noting `tsc --noEmit` alone silently checks **nothing** in this repo (the
root `tsconfig.json` has `files: []` and only project references); the real
typecheck is `tsc -b`, matching the `build` script. Verified live: real held
STOCK/ETF holdings show real composite scores (Technical-only for now —
`SEC_USER_AGENT` isn't set in this deployment's `.env` yet, flagged for the user to
add whenever they want the Value/Growth/Quality pillars to actually score — format
`"First Last email@example.com"`, `.env.example:27-29`); the expand row shows the
correct per-pillar breakdown, including honestly labelled dropped reasons for every
Value/Growth/Quality metric; clicking "Fetch fundamentals" against the real
portfolio correctly reports "0 updated, 0 already up to date, 5 not applicable, 32
not retrieved" (5 ETFs, 32 stocks all `noProvider` pending that env var); no CFD
ever appears with a score; no real console errors (a stale HMR error snapshot from
mid-edit persisted in the console buffer and was confirmed, via direct DOM/network
inspection, to not reflect the app's actual current state).

## Decision 3s.1 — SEC_USER_AGENT configurable from the Settings page (2026-08-20)

Direct follow-up to 3r.1: the user asked why clicking "Fetch fundamentals" did
nothing useful, and — more generally — asked that anything a fresh clone of this
repo needs configured to actually work be reachable from Settings, not left as a
hand-edit-`.env`-and-restart step. The immediate cause: `SEC_USER_AGENT` genuinely
has no UI at all, even though the backend has fully supported it since the original
phase-2 API-key batch — `ApiKeysStatus`, `UpdateApiKeysRequest` and the `.env`-write
mapping in `update_api_keys` already had a `sec_user_agent` field, unused because
nothing ever surfaced it as a card.

**Root cause: EDGAR was never part of the price-provider chain.** `GET /providers`
builds its list by iterating `get_provider_chain().providers` — and EDGAR
deliberately isn't in that chain (it's fundamentals, not daily/live prices; see
Decision 3r.1's `get_edgar_provider()`, a separate registry function). So the loop
that produces every other provider's Settings card never saw it, no matter how
complete the backend's write-side support already was.

**Fix**: `get_provider_status()` appends one manual `ProviderStatus` entry for
`"sec_user_agent"` after the chain loop, `enabled` read from
`get_edgar_provider().is_enabled()`. Named `sec_user_agent` (not `edgar`) on
purpose — `Settings.tsx` keys its save payload directly off `provider.name`, so it
has to match `UpdateApiKeysRequest`'s existing field name exactly, the same
constraint Bug 2b.7 already flagged for `provider.name`-vs-settings-field
mismatches.

**Verify-key needed its own path.** The existing `/verify-key` endpoint only knows
how to test `PriceProvider`-shaped classes (`fetch_daily`/`fetch_quote`) — EDGAR
isn't one. Added a `sec_user_agent`-specific branch that constructs a throwaway
`EdgarProvider` with the candidate string and calls `.resolve("AAPL")` — a real,
always-present ticker — so a rejected header (SEC 403 → `ProviderUnavailable`)
surfaces immediately instead of only being discovered days later via a failed
fundamentals refresh, the same "test now, not later" reasoning the other providers'
verify path already uses.

**Frontend UX correction, not just wiring.** A contact string isn't a secret the
way an API key is — it's sent openly in a header on every request — so masking it
behind `type="password"` bullets would only hide typos in the user's own email from
them. `Settings.tsx` special-cases `provider.name === 'sec_user_agent'`: plain
`type="text"`, a "Contact info" label instead of "API key", and "Learn more" instead
of "Get a free key" next to a link to the SEC's own explanation of the requirement
(not a signup page — there is no signup).

**Bug caught live, not by a test**: the success message doubled its full stop —
`f"...to {registrant}."` where `registrant` (e.g. "Apple Inc.") already ends in a
period as often as not, from SEC's own data. Fixed by dropping the appended one.

4 new tests (`test_settings_api.py`, the first for this router): the provider list
includes `sec_user_agent` with `has_api_key: true`; verify with no key configured or
supplied reports nothing to test; a mocked-accepted and mocked-rejected EDGAR
response both surface correctly. Deliberately does **not** exercise
`PUT /api/settings/api-keys` — that endpoint writes to the real project `.env` file,
and a test mutating a developer's real config file is exactly the side effect this
suite must never have. Full suite green at 440 passed, `tsc -b`/lint clean.

Verified live: the Settings page now shows a genuine `sec_user_agent` card
("Disabled" — nothing configured yet) with the corrected "Contact info" label and
"Learn more ↗" link; typing a real placeholder contact string and clicking "Test"
made a real network call to SEC EDGAR and correctly resolved AAPL → "Apple Inc." (no
double period); the field was cleared afterward without saving, confirmed `.env`
still has no `SEC_USER_AGENT` line — nothing was written by the Test round-trip,
only by the not-yet-touched Save button.

**Separately noticed, not fixed here**: `finnhub_api_key` exists in `Settings`,
`ApiKeysStatus` and `UpdateApiKeysRequest` — same shape as every real keyed
provider — but has zero actual consumer anywhere (no `FinnhubProvider` class, not
in `TESTABLE_PROVIDERS`, not in the price chain). Same class of bug Bug 2b.7 already
found and fixed for `stooq`/`eoddata`/`finviz`'s dead key fields, just missed that
round. Flagged for a follow-up cleanup rather than folded into this change.

## Bug 3s.2 — Finnhub: one more dead key field Bug 2b.7 missed (2026-08-20)

Follow-up cleanup for the gap Decision 3s.1 flagged and deliberately didn't fix
inline. Re-verified before touching anything: grepped the whole backend for
`finnhub` and confirmed there is still no `FinnhubProvider` class under
`providers/`, no entry in `registry.py`'s `get_provider_chain()`, and no entry in
`routers/settings.py`'s `TESTABLE_PROVIDERS`. `finnhub_api_key` was fully wired on
the write side only — `Settings`, `ApiKeysStatus`, `UpdateApiKeysRequest`, the
`.env`-write mapping, and `main.py`'s health check — exactly the
`stooq`/`eoddata`/`finviz` shape Bug 2b.7 fixed elsewhere, just missed that round
because Finnhub was never part of the same batch review.

One difference from Bug 2b.7's three: because `GET /api/settings/providers` only
ever lists price-chain providers (plus the one manual `sec_user_agent` entry from
Decision 3s.1), and Finnhub was in neither, it never actually reached
`has_api_key` filtering or got a Settings-page card at all — unlike Stooq/Eoddata/
Finviz, which did render dead inputs. Same underlying bug (a key nothing reads),
smaller blast radius (no live UI element pointed at it).

**Fix**, matching Bug 2b.7's pattern exactly: removed `finnhub_api_key` from
`config.py` (the field, the placeholder-validator's parameter list, and the
`finnhub_enabled` property); removed `finnhub` from `ApiKeysStatus`,
`UpdateApiKeysRequest`, and the `.env`-write `mapping` dict in
`routers/settings.py`; removed the `"finnhub": settings.finnhub_enabled` entry
from `main.py`'s health check; removed `FINNHUB_API_KEY` (and its comment block)
from `.env.example`. Also updated the two places that referenced it outside the
app code: `backend/tests/conftest.py`'s `CREDENTIAL_VARS` tuple and
`backend/tests/test_config.py`'s `test_the_rule_covers_every_credential` (swapped
to `POLYGON_API_KEY` to keep the "the placeholder rule covers every credential,
not just Twelve Data" assertion meaningful with 3 keys), and README.md's
configuration table and provider-coverage table, both of which listed Finnhub as
if it were a working integration.

Full suite still green at 440 passed — unchanged from Decision 3s.1, since this
removed a dead field rather than any tested behavior.

## Bug 3s.3 — `fx_rates.fetched_at`: the model never matched the real table

**Symptom.** The very first real `SEC_USER_AGENT` value, entered live through the
Settings page just added in Decision 3s.1, immediately broke `GET
/api/scoring/scores` with a 500: `sqlalchemy.exc.IntegrityError: NOT NULL
constraint failed: fx_rates.fetched_at` on an insert for `('USD', 'CNY', ...)`.

**Cause.** `sqlite3 data/stock_analyst.db ".schema fx_rates"` showed a real
`fetched_at DATETIME NOT NULL` column — but `models.py`'s `FxRate` class, and
every DEVLOG entry describing it since it was introduced, only ever listed
`currency`, `base_currency`, `rate_date`, `rate`. The column had existed on disk,
uninserted-into by name, this whole time — some earlier change added it to the
live table (directly, or via a step never written up) without ever updating the
model to match. It never surfaced because every currency pair this app had ever
actually requested (mostly `*→EUR` for the live value/history features) happened
to already have a cached row from whenever that column first appeared with a
value, or those specific pairs were never freshly inserted after the drift began.
The scoring engine's Value pillar was the first caller to ever request a **brand
new** pair — `USD→CNY`, for NTES (NetEase) and DOYU (DouYu), both USD-listed ADRs
of companies that file their SEC fundamentals in RMB — and a fresh `INSERT` is
exactly the code path that touches every column, including the one the model
didn't know about.

**Fix.** Added `fetched_at: Mapped[datetime] = mapped_column(DateTime,
default=_utcnow)` to `FxRate`, matching `PriceBar`/`LastQuote`/`Fundamental`'s
identical field. No migration needed — the column was already there; only the
model was missing it. Full suite green at 440 passed; live-reverified
`GET /api/scoring/scores` returns 200 with real Value-pillar figures for the
whole portfolio, including NTES/DOYU.

## Bug 3s.4 — `isolate_credentials` never actually isolated the real `.env` file

**Symptom.** Fixing 3s.3 immediately exposed a second failure: three tests that
assert "SEC EDGAR is disabled with no key configured" started failing the moment
the user saved a *real* `SEC_USER_AGENT` through the running app — in a completely
separate process, hitting the real project `.env`, not anything the test process
itself wrote.

**Cause.** `conftest.py`'s `isolate_credentials` (autouse, and its own docstring
already claimed to guard exactly this) only ever did
`monkeypatch.delenv(name, raising=False)` — clearing the **process environment
variable**. `Settings` (`config.py`) is built with `SettingsConfigDict(env_file=
(BACKEND_DIR / ".env", PROJECT_ROOT / ".env"), ...)`, and pydantic-settings reads
that file **as a separate source**, independent of `os.environ` — clearing the
env var never touched it. Confirmed directly: `os.environ.pop("SEC_USER_AGENT")`
followed by a fresh `get_settings()` still returned the real value straight off
disk. This gap has existed since `isolate_credentials` was written; it simply
never mattered before, because the real project `.env` had never held a value for
any of the credentials it lists — until this session's own live verification of
Decision 3s.1 legitimately put one there.

**Why this is worse than it looks.** Every credential-gated test in this suite —
not just the new SEC EDGAR ones — was implicitly relying on the developer's real
`.env` staying empty of these specific keys. Any of them could have started
silently reading real production configuration the day someone's real `.env`
happened to gain one of these fields for an unrelated reason.

**Fix.** `isolate_credentials` now also does `monkeypatch.setitem(Settings.
model_config, "env_file", ())` before clearing the environment variables — every
`Settings()` built during a test reads *only* explicitly-set environment
variables, never the developer's real `.env` file, regardless of what it holds.
Full suite green at 440 passed.

Both of these were found live, not by a test, while verifying the very feature
that only just made a real `SEC_USER_AGENT` possible to enter — a reminder that
"first real user input through a brand-new config path" is exactly when dormant
schema drift and test-isolation gaps like these tend to surface.

## Decision 3t.1 — ESEF: a second fundamentals source for Europe (2026-08-20)

Direct follow-up to 3s.1/3r.1: with `SEC_USER_AGENT` finally configured, a real
fundamentals refresh confirmed 4 real holdings SEC EDGAR genuinely cannot reach —
Air Liquide (AI.FR), LVMH (MC.FR), Dassault Systèmes (DSY.FR), Air France KLM
(AF.FR) — none are SEC filers under any discoverable ticker (consistent with Phase
3a's original finding). Asked directly whether a second source was worth it before
building anything: researched real alternatives, not just providers already in this
app. FMP, EODHD, Alpha Vantage and Twelve Data — all already keyed in this app for
prices — paywall non-US fundamentals on their free tier, confirmed live with real
402/403 responses. Found one genuine free, official source:
**[filings.xbrl.org](https://filings.xbrl.org)**, XBRL International's public
repository of ESEF filings — the EU's own mandatory XBRL annual-report format for
listed companies, in force since fiscal year 2020. Confirmed with the real user:
exactly two sources, additive — EDGAR (US) primary, ESEF (EU) fallback — a third
source was explicitly considered and rejected as premature for what a retail
portfolio like this one holds.

**Verified live, repeatedly, before writing any code** (this feature's design came
entirely from real API responses, not documentation): all 4 companies are in the
ESEF repository with genuine multi-year IFRS-tagged data (e.g. Dassault Systèmes'
real FY2024 `ifrs-full:ProfitLoss` = €1,198,100,000, six years back to 2020; Air
France KLM's real 2020 net loss of -€7.1bn and negative equity through 2022,
matching its real COVID-era history) — and that `edgar.IFRS_CONCEPT_TAGS` (built
originally for TotalEnergies' SEC 20-F) already lists the exact same tag names ESEF
filings use, so the concept-mapping work already existed.

**A real false positive caught before it shipped, not after.** `edgar.names_match`
alone — correct once a ticker has already narrowed the field to one candidate —
returns `True` for `names_match("Air Liquide", "Air Products & Chemicals, Inc.")`
purely on the shared word "air". Safe to use for *verifying* one already-narrowed
candidate (which is all EDGAR ever uses it for); not safe for *searching* a
~7,300-entity index from scratch, where a single generic token is nowhere near
enough. `EsefProvider.resolve()` (`app/providers/esef.py`) instead reimplements
`edgar.find_by_name`'s stricter rule (exact token-set match wins; else a single
candidate containing every significant word; else refuse as ambiguous) against
ESEF's own entity shape, reusing `edgar._name_tokens` directly. Verified against the
real, full entity list: all 4 companies resolve uniquely and correctly this way,
the Air Products decoy correctly excluded.

**A second real bug caught live, mid-implementation**: the first working version
used the JSON:API `id` field (filings.xbrl.org's own internal row number) as the
entity identifier passed to `/api/entities/{id}/filings` — every one of the 4 real
companies immediately 404'd. The real identifier every other endpoint expects is
`attributes.identifier` (usually an LEI, occasionally a national scheme code when no
LEI is registered) — confirmed and fixed by inspecting the real response shape
directly, not assumed from the (misleadingly named) `id` field.

**Design, `app/providers/esef.py`**: no key, `is_enabled()` always `True`. Fetches
and caches the full ~7,300-entity list once per instance (mirrors
`EdgarProvider._load_index()`'s discipline). Unlike SEC's single `companyfacts`
call, ESEF has no equivalent — each fiscal year is a separate filing, so `fetch()`
pulls the most recent 6 filings and merges them newest-first (a year already
supplied by a more recent filing is never overwritten by an older, less-authoritative
one). **A concept appears many times per filing and only one is real** — confirmed
live, 22 `ifrs-full:ProfitLoss` facts in one real filing, only 2 the genuine
consolidated total, the other 20 broken out by a dimensional axis (business
segment, equity component). Told apart by `dimensions` keys: the real total has
exactly `{concept, entity, period, unit}`; anything with an extra key is a
sub-total and is discarded. **XBRL period dates are the exclusive end, not the
reported date** — confirmed live, a FY2024 (calendar year) balance-sheet figure
carries period `"2025-01-01T00:00:00"`, not `"2024-12-31"`; one day is subtracted
from whichever end is reported (duration or instant) before computing
`fiscal_year`/`period_end`.

**Wiring (`app/fundamentals/service.py`)**: `fetch_one` tries EDGAR first, then ESEF
— for *any* reason EDGAR didn't produce a usable concept, not just
`SymbolNotFound`: a company found in EDGAR's own index but filing nothing usable
there (documented for real, Decision 3a.1 — Air Liquide and Sanofi are both in the
SEC index but file no usable XBRL) still falls through to ESEF; so does a
disabled EDGAR (no `SEC_USER_AGENT`) and even a transient EDGAR rate-limit, on the
principle that maximising this run's actual coverage beats leaving an instrument
empty over something the second source might still answer. Deliberately two
explicit steps, not a generalised N-provider chain — the user's own choice that two
sources are enough. `NO_PROVIDER` now means something narrower and more honest than
before: neither source was even *attempted* (EDGAR disabled and the instrument has
no name to search ESEF with either), distinct from `SYMBOL_NOT_FOUND` (at least one
source was actually asked and came back empty).

22 new tests: `test_esef_provider.py` (entity resolution including the Air
Products false-positive case and a genuine ambiguous-match refusal, dimension
filtering, both period shapes, currency parsing, no-JSON-url filings skipped
without crashing) and an extended `test_fundamentals_service.py` (EDGAR success
never touches ESEF; EDGAR `SymbolNotFound`/disabled/rate-limited all correctly fall
through; EDGAR "found but empty" still tries ESEF; both failing reports the more
informative of the two outcomes). Full suite green at 462 passed. `tsc -b`/lint
untouched and clean (no frontend changes — this only widens the data feeding the
already-built scoring endpoints).

Verified live against the real portfolio: a full forced refresh now reports
**32 updated, 0 failed** (previously 28 updated, 4 failed) — AI.FR/MC.FR/DSY.FR/AF.FR
all show `provider: "esef"` with real multi-year data (36–47 concepts each); the 28
US holdings plus 3 ADR-style European names (TotalEnergies, Sanofi, Orange) are
completely unaffected, still `provider: "edgar"`. `GET /api/scoring/scores` now
shows real Growth (e.g. Air Liquide 40/100) and Quality (100/100 — 3 of 5 Piotroski
checks scorable) for all 4, up from Technical-only. Value stays `None` for 3 of the
4 (only LVMH's ESEF filings happen to tag `shares_diluted`/enough debt detail) —
confirmed as an honest gap, not a bug: the concept simply isn't tagged under any of
the currently-tracked XBRL names for those filers, and the app correctly drops just
that pillar and renormalizes rather than guessing. Confirmed in the browser: the
expand-row breakdown for Air Liquide renders exactly this — "Value: No data" with
every metric labelled "Missing data", real numbers everywhere else — no console
errors.

**Follow-up, same day: two of the three missing Value tags were real gaps, not a
structural limit.** Asked directly whether the "Value: No data" case for 3 of the 4
companies was fixable. Checked live rather than assumed: all three do report
`ifrs-full:LongtermBorrowings` for debt — a real tag simply absent from
`IFRS_CONCEPT_TAGS["debt_long_term"]`'s candidate list (which only had
`NoncurrentPortionOfNoncurrentBorrowings`/`NoncurrentBorrowings`). Air France KLM
also reports `ifrs-full:NumberOfSharesOutstanding` — Air Liquide and Dassault
Systèmes genuinely do not tag any share count at all, confirmed by searching their
real filings' full concept list, not just assumed absent. Added both as additional,
lower-priority candidates (same "one concept, many tags" pattern `_extract`/
`_merge_filing` already handle — appending never changes behaviour for a filer
already matching on an earlier candidate). `NumberOfSharesOutstanding` is a
point-in-time count, not the diluted weighted average `WeightedAverageShares` is —
an honest approximation for filers that don't tag the latter, and never a silent
one: `AnnualFigure.tag` still records which of the two actually produced any given
value.

Re-verified live: Air Liquide and Dassault Systèmes now score `Value: 100/100`
(Debt/Equity alone, still missing shares for the price-based metrics); LVMH gained
a working P/E and P/B; Air France KLM gained P/E, P/B and Debt/Equity — the last
correctly scoring 0/100 (real, heavily leveraged, consistent with its known
post-COVID balance sheet). FCF yield stays missing for all four (`capex` isn't
tagged under a name currently tracked for any of them either — a further gap,
not investigated this round). Full suite still green at 462 passed.

**Same question asked of the US/EDGAR side — checked, not assumed.** Audited every
concept genuinely missing across the 32 real held stocks (correctly scoped to held
positions this time via the `Position` join — an unscoped first pass wrongly
flagged dozens of unrelated, never-fetched instruments left over in the database).
Two findings:

- `liabilities` and `gross_profit` are the most commonly missing concepts (AMD,
  ORCL, GOOGL, SOFI, TXRH, VICI, and several ESEF filers) — but neither is consumed
  by *any* scoring metric (`scoring/metrics.py` only ever reads `debt_long_term`
  for leverage, never a standalone `liabilities` total). Confirmed live for AMD:
  it doesn't tag a combined `Liabilities` total at all, only `LiabilitiesCurrent`
  separately — a real absence, and also a data point already known to be inert for
  scoring. Not worth chasing.
- `debt_long_term` missing for 5 US holdings turned out to be two different
  situations, told apart by checking each company's real filed tags rather than
  assuming one fix covers all five: Datadog and Okta genuinely have long-term debt
  but finance it through convertible notes, tagged `ConvertibleLongTermNotesPayable`
  / `ConvertibleDebtNoncurrent` — neither in `CONCEPT_TAGS`'s candidate list, added
  as fallbacks the same way the ESEF tags were. IonQ, DouYu and Honest Company
  carry no long-term debt tag under *any* name — confirmed by listing every debt-
  or borrowing-related tag in their real filings and finding none — a genuine
  absence (young, equity-financed, or simply debt-free companies), correctly left
  as `missing_concept` rather than forced. Ares Capital's separate `capex`/
  `gross_profit`/`revenue`/`operating_income` gaps are a business-development-
  company structural mismatch already documented (Phase 3a: "1 is a BDC reporting
  no conventional revenue line"), not a tag-naming problem.

Re-verified live: Datadog and Okta both gained a working Debt/Equity metric (100/100
for both — real, healthy relative leverage) and, since that was the only missing
piece, a fully-populated Value pillar where it had previously dropped entirely.
Full suite still green at 462 passed.

## Decision 3u.1 — Sort every positions-table column, not just four (2026-08-20)

Asked directly for the investments table to be sortable by any column, ascending or
descending. The existing control was a "Sort by" `<select>` covering only 4 of the
table's 13 columns (value, unrealised, performance, symbol) — replaced entirely
with clickable column headers, the conventional spreadsheet pattern: click a header
to sort by it (ascending first), click the same header again to reverse, click a
different header to switch (ascending first again, not remembering the previous
column's direction).

`PositionsTable.tsx`: a single `SortState { key, direction }` replaces the old
`sortKey` string state. A `sortValue(position, key, scores)` switch extracts the
right field per column — including `score` (reads the live `scores` prop, the same
composite already shown in the `ScoreBadge`) — so every data column sorts, not just
the four the old dropdown covered. `mapping` and `trend` stay unsorted deliberately:
one is a multi-state action cell, the other a sparkline array, neither has a single
scalar ordering that would mean anything. Missing values (`null`) always sort last
regardless of direction — the same "a blank isn't the lowest or highest value, it's
unknown" rule this app applies everywhere else, not just here.

A small `SortableHeader` component (label + a ▲/▼ indicator, shown only on the
active column) replaces every plain `<th>` that used to just print a label —
avoids repeating the same onClick/indicator logic 12 times inline. Removed the
"Sort by" `<select>` and its now-dead `filters.sortBy`/`sort.*` i18n keys (4 keys ×
3 languages) — nothing else referenced them.

No backend change — this is client-side sorting over data already fetched.
`tsc -b`/lint clean. Verified live: clicking "Score" sorted the real portfolio's
composite scores ascending (23, 36, 38, 43...); clicking it again reversed to
descending (99, 95, 95, 82...); clicking "Account" correctly grouped "My Trades"
before "PEA" alphabetically. A stale HMR error snapshot from mid-edit (`sortKey is
not defined`) persisted in the console buffer exactly as it has several times this
session — confirmed via `grep` that no such identifier remains in the file, `tsc
-b` passing, and the sorting itself working correctly live, all three agreeing the
running app has no real error.

## Bug 3u.2 — The positions table's right-hand columns were reachable, not visible (2026-08-20)

**Symptom.** User reported the table "isn't big enough" and the right-hand columns
weren't visible.

**Cause, found live rather than guessed.** Two compounding things. First,
`.content`'s `max-width: 1180px` left real unused space on any wider monitor while
the table (13 columns) still needed more room than that — confirmed by measuring
`table.scrollWidth` vs the wrapper's `clientWidth` directly in the browser (577px of
real overflow at a 1024px viewport). Second, and the more likely actual cause of "I
can't see them" specifically: the horizontal scrollbar that already existed
(`.table-wrap { overflow-x: auto }`) had no forced styling, so on macOS (scrollbars
hidden until actively scrolling, by default) there was **no visual cue that
anything existed to scroll to at all** — the columns were always reachable by
scrolling, just with nothing on screen suggesting to try.

**Fix.** `.content`'s `max-width` raised from 1180px to 1440px — most of the
overflow disappears outright on a typical desktop monitor (577px → 161px at
1024→1440px in direct measurement). For whatever scrolling is still needed,
`.table-wrap` now forces a visible scrollbar cross-browser (`scrollbar-width:
auto`/`scrollbar-color` for Firefox, `::-webkit-scrollbar` rules for Chrome/Safari)
instead of relying on the OS default, which had been silently hiding the only
existing affordance.

Verified live: measured real overflow before (1024px: 577px) and after (1440px:
161px) directly via `scrollWidth`/`clientWidth`; confirmed the forced scrollbar
styling is active (`getComputedStyle` reports the intended colors); scrolled the
wrapper programmatically and confirmed the "Account" and delete-action columns
land inside the visible client rect afterward. No console errors. CSS-only change,
`tsc -b`/lint unaffected (both still clean).

## Decision 3u.3 — Score breakdown: percentages as percentages, not raw decimals (2026-08-20)

Asked directly whether the scoring engine's metrics were clear enough. Real gap
found on review, confirmed by the user: `ScoreDetailRow` printed every metric's raw
value through the same generic `formatNumber(value, 3)`, so a 7.2% revenue CAGR
showed as "0.072" and a 1.91% FCF yield as "0.0184" — technically correct, but
demanding mental conversion on every read.

`ScoreDetailRow.tsx` now classifies each metric by what its raw value actually
means, not one formatter for all fifteen: `fcf_yield`, `revenue_cagr`,
`net_income_cagr`, and the three Technical metrics (`price_vs_sma200`,
`momentum_12_1`, `sma50_vs_sma200`) are genuine percentages that can go negative (a
decline, a price below its average) — rendered via the existing
`formatSignedPercent` (already used elsewhere for `current_unrealized_pl_pct`), so
"+7.2 %" / "-3.1 %". `revenue_growth_consistency` is also a percentage but
structurally never negative (a share of years with positive growth) — a plain
`{value}%` without the `+` `formatSignedPercent` would otherwise add, since that
sign would be redundant there. `pe_ratio`, `pb_ratio` and `debt_to_equity` are
deliberately left alone — these are conventionally read as plain ratios, not
percentages, and converting them would be the opposite mistake. The five binary
Quality metrics (pass/fail, shown as `1`/`0`) are untouched too — out of scope for
this round, flagged as a possible further polish but not something the user asked
for yet.

No backend change — purely a display-layer fix, the raw fractional values already
computed and sent by `scoring/metrics.py` were always correct; only how the
frontend printed them was wrong. `tsc -b`/lint clean. Verified live against a real
holding: FCF yield now shows "+1.91 %" (was "0.0184"), Revenue CAGR "+20.77 %" (was
"0.2077"), Growth consistency "93.75%" (was "0.9375", correctly unsigned), 12-month
momentum "+147.87 %" (was "1.3971") — while P/E (60.55), P/B (29.67) and
Debt/Equity (0.14) correctly stayed as plain numbers. No console errors.

**Separately flagged during this review, not yet acted on**: the default pillar
weights (30/25/25/20) are visible nowhere in the UI — only in `scoring.yaml` on
disk — and dividend yield isn't scored in the Value pillar despite the app already
tracking real dividend data via Transactions. Both noted for a possible future
pass, not requested yet.

## Decision 3u.4 — Pillar weights spelled out in the composite-score tooltip (2026-08-20)

First of the two items flagged above. `table.scoreTooltip` (en/fr/pl) only said
the composite score "blends Value, Growth, Quality and Technical" without the
actual default split — the weights existed only in `scoring.yaml` on disk. Rewrote
the tooltip in all three languages to state the real defaults explicitly (Value
30%, Growth 25%, Quality 25%, Technical 20%) plus a note that they renormalize per
holding when a pillar has no data — the same renormalization already visible in
each holding's own expanded breakdown, now explained up front instead of only
discoverable per-row. Pure i18n string change, no logic touched. `tsc -b`/lint
clean.

## Decision 3u.5 — Dividend yield in the Value pillar, via lot-replay (2026-08-20)

Second flagged item. The app already imports every dividend payment as a
`Transaction` (`type=DIVIDEND`), but nothing in the Value pillar used it — a real
coverage gap for a pillar named after exactly the investing style (Graham/Buffett)
that weighs shareholder yield.

Two designs were on the table; the user explicitly chose the more rigorous one.
The simple option (trailing-12mo dividends received ÷ current position value) was
rejected as a personalized "yield on cost" — it depends on the user's own entry
timing and position size, not a market-comparable yield, and risks misreading as a
value signal (the classic yield-on-cost trap). Instead: replay the `Lot` ledger
(the same mechanism `history_service.py::compute_value_history` already uses to
reconstruct historical holdings) to find how many shares were actually held on
each dividend's payment date, derive a real per-share amount, and compare that to
the current price.

Confirmed live before designing around it: dividend `Transaction` rows have
`quantity=None`/`price=None` — only `amount` (total cash) — and cross-checking
several real rows (MRVL.US, ASML.NL) confirmed `amount` is in the **instrument's
own trading currency**, matching its price currency, so no FX conversion is
needed here (unlike `fcf_yield`/`pe_ratio`, which do convert fundamentals currency
vs price currency).

`scoring/service.py` gained `_shares_held_on(lots, day)` (identical replay rule to
`history_service.py`'s per-day loop: a lot counts if opened on/before `day` and,
if ever closed, closed strictly after `day`) and
`_annual_dividend_per_share(dividends, lots)`, which sums `amount / shares_held`
over the trailing 12 months. Getting the "no data" case right took an extra pass:
initial version returned `0.0` whenever there were no dividend rows, but a live
test on an ETF with **no Lot history at all** exposed that this quietly scored a
completely-unheld instrument at a confident 0% — wrong, since with no lots there's
nothing to reconstruct a share count from at all. Fixed to a three-way rule: no
lot history at all → `None` (dropped, can't know anything); lot history but no
dividend payments in the window → `0.0` (a real, known fact about a non-payer);
dividends exist but every one falls on a day this replay reconstructs as zero
shares held → `None` (an unattributable data inconsistency, never guessed).

`scoring.yaml`'s Value pillar rebalanced from 4 to 5 metrics:
`pe_ratio 30→25, pb_ratio 25→20, fcf_yield 25→20, debt_to_equity 20→20,
dividend_yield (new) 15`, `full_at 0.04 / zero_at 0.0` — kept Graham/Buffett's
core value metrics dominant while giving income a real but secondary weight.
Both the split and the 0%/4% band are starting points, easily retuned — the file's
own header comment already says it's edited freely, not a one-shot decision.

Frontend: `dividend_yield` added to `ScoreDetailRow.tsx`'s `PLAIN_PERCENT_METRICS`
(never negative, no `+` prefix wanted) and a new `scores.metric.dividend_yield`
label in en/fr/pl.

39 new backend tests (metric-level: normal/zero/missing cases; service-level:
`_shares_held_on` across spanning/late-opened/closed-before/closed-on-day lots,
`_annual_dividend_per_share` across single/multiple payments and the
no-lots/no-dividends/unattributable three-way split, plus two end-to-end
`compute_scores` cases). Full suite: 479 passed (was 440). `tsc -b`/lint clean.

Verified live against the real portfolio: ARCC.US (a BDC) → 8.38% yield, scored
100/100 — matches its real-world reputation for an unusually high distribution
yield; VICI.US (REIT) 5.8%, TTE.FR (TotalEnergies) 4.3%, ORA.FR (Orange) 4.7% — all
plausible real yields. Non-payers (ADBE.US, AMD.US, DDOG.US, SOFI.US, and others)
correctly show a genuine `0%`/score 0 in the browser, not "Missing data" — confirmed
by expanding both ARCC.US's and ADBE.US's score rows directly. Renormalization
re-checked by hand against ORA.FR's real numbers (4 of 5 metrics scored, weights
25+20+20+15=80 renormalizing correctly to the pillar's 93.83 composite) — matches
exactly.

**Follow-up fix, same day**: user caught a real regression from the change above
before it shipped further — SPEA.FR and DCAM.FR (accumulating/swap ETFs, verified
live to have real lot history but **zero** dividend transactions ever) dropped from
a composite of ~95 to 38. Cause: these ETFs' Value pillar used to be entirely
excluded (no Fundamental data applies to a fund), so the composite came 100% from
Technical; `dividend_yield` now gave them a real, non-dropped `0%`, which kept
Value "alive" with a hard 0 and dragged the weighted composite down
(`(0×30 + 95×20)/50 = 38`). The 0% itself was computed correctly — the problem is
that a fund's distribute-vs-accumulate design is a structural choice, not a
valuation signal, so scoring it as "bad value" was a category error, not a bug in
the arithmetic.

Fixed by restricting `dividend_yield` to `category == "STOCK"` — `compute_scores`
in `scoring/service.py` now only queries `Lot`/`Transaction` for stock instrument
ids and passes `annual_dividend_per_share=None` for anything else, so it drops via
the same `DROP_MISSING_CONCEPT` path as the other three ETF-inapplicable Value
metrics; ETFs' Value pillar goes back to being fully excluded. New test
(`test_accumulating_etf_is_excluded_not_punished`) pins this down. Full suite: 480
passed. Verified live: SPEA.FR/DCAM.FR back to 95, PAEEM.FR to 99 — matching their
pre-feature scores exactly.

## Decision 3u.6 — Quality pass/fail metrics shown as Pass/Fail, not raw 1/0 (2026-08-20)

Last of the polish items flagged during Decision 3u.3's review. The Quality
pillar's five Piotroski-style checks (`roa_positive`, `cfo_positive`,
`accruals_quality`, `leverage_not_increasing`, `no_significant_dilution`) are
`kind: binary` in `scoring.yaml` — their raw value is 1.0/0.0, a pass/fail result,
not a quantity — but `ScoreDetailRow.tsx` printed them through the same
`formatNumber(value, 3)` as every other metric, so they showed as a bare `1` or
`0` with nothing marking that as a checklist result rather than a truncated real
number.

Added a `BINARY_METRICS` set (the same five names) to `ScoreDetailRow.tsx`;
`formatMetricValue` now renders them as `t('scores.binaryPass')`/
`t('scores.binaryFail')` ("Pass"/"Fail" in en, "Réussi"/"Échoué" in fr,
"Zaliczone"/"Niezaliczone" in pl) instead of falling through to the numeric
formatter. Purely a display change — the underlying `1.0`/`0.0` score computation
in `scoring/metrics.py` is untouched.

No backend change, no new tests needed (nothing computational changed). `tsc
-b`/lint clean. Verified live: ADBE.US's Quality breakdown now reads "Return on
assets > 0 — Pass", "Leverage not rising — Fail", etc., instead of `1`/`0`.

## Decision 3u.7 — Schema migrations via Alembic (2026-08-20)

Second finishing-touch item: the app had no versioned migration tool, relying
entirely on `Base.metadata.create_all` at startup — fine for adding a brand-new
table, but it can't apply an `ALTER` to a table that already exists, which is
exactly what most future schema changes will need (e.g. adding a column to
`Fundamental` the way `dividend_yield`-style features tend to).

Added Alembic (`backend/alembic/`), wired to the app's own config rather than a
separate hardcoded URL — `alembic/env.py` imports `app.models` (to register every
table on `Base.metadata`) and pulls the real database path from
`app.config.get_settings().database_url`, the same single source of truth
`app/db.py` already uses. `alembic.ini`'s `sqlalchemy.url` is left blank on
purpose, with a comment pointing at why.

Generated the baseline migration (`39575e46f410_baseline_schema.py`) by running
`alembic revision --autogenerate` against a throwaway blank database (not the real
one — autogenerating against a database that already has every table produces an
empty diff), then sanity-checked it by applying that migration to a second blank
database and diffing its resulting schema against one built with the existing
`create_all` — identical apart from Alembic's own `alembic_version` table and
cosmetic constraint-ordering differences in the generated SQL text. Only then
stamped the real on-disk database (`data/stock_analyst.db`, backed up first) at
that baseline via `alembic stamp head` — this records "already at this revision"
without re-running any DDL, since every table is already there. Verified row
counts identical before/after for all 12 tables (3175 fundamentals, 10676 price
bars, 1395 transactions, etc.) — the stamp touched no data.

`app/db.py::init_db()` now runs `alembic upgrade head` programmatically instead of
calling `Base.metadata.create_all` directly — a fresh install with no database
file gets every table from the baseline migration (same end result `create_all`
used to give it), and an existing install picks up whatever has landed since it
was last stamped, automatically on every startup — no manual step to remember
before running the app. Going forward, an actual schema change is: edit the model,
`alembic revision --autogenerate -m "..."`, review the generated file, done —
documented in the README's Backend section.

`alembic==1.19.1` added to `requirements.txt`. Full suite: 480 passed (init_db()
now going through Alembic on every `TestClient(app)` instantiation added no
measurable slowdown — 13.4s vs. 13.7s before). Test fixtures are unaffected: they
build their own in-memory database via `Base.metadata.create_all(engine)`
directly, deliberately bypassing migrations for a fast, fully-fresh schema per
test — Alembic only governs the one real on-disk database's lifecycle.

## Decision 3u.8 — Phase 4: Watchlist (2026-08-21)

Next roadmap phase after Phase 3's scoring engine: a list of instruments *not*
currently held, tracked for entry timing before buying.

Turned out to be half-built already. `WatchlistItem` has existed in
`app/models.py` since the project's very first migration — dormant, its only
live reference anywhere in the app was a guard in `delete_instrument` refusing
to remove an `Instrument` still on the watchlist. The frontend already had a
`/watchlist` nav link and route, pointed at a generic `<Placeholder>`. No
router, schema, service, or real page existed. Built directly on top of the
dormant model — no new migration needed, its baseline schema already matched
`app/models.py` field for field.

**The core invariant**: the model's own docstring says "a watched but
*unheld* instrument," but nothing enforced that. Two directions handled:
adding an already-held symbol is rejected (400, checked against `Position`);
a watchlisted symbol that later gets bought (manual entry or import) simply
disappears from every watchlist read via an anti-join against `Position` —
self-healing, since the `WatchlistItem` row itself is never touched, so
`target_entry_price`/`note` survive and the row reappears if it's ever fully
sold again.

New `app/routers/watchlist.py`: `POST /api/watchlist` resolves/creates the
`Instrument` via the existing `get_or_create_instrument` (the same primitive
`create_manual_position` already uses), rejects an already-held or
already-watchlisted symbol (400, this codebase's uniform conflict status —
no 409 exists anywhere in it), then best-effort fetches a real price
immediately via `refresh_instrument` so the new row isn't blank. `GET`/`PATCH`/
`DELETE` round out CRUD; `GET /scores` and `GET /sparklines` mirror the
existing held-instrument endpoints (`compute_scores`/`PriceBar` sparkline
query) against the anti-joined watchlist set instead — kept as separate
endpoints rather than a `?scope=` flag on the existing ones, since there was
no real precedent for one endpoint serving two disjoint instrument universes
and it would've meant retesting stable, already-tested endpoints for one new
caller. `POST /api/prices/refresh` now also appends watchlist instruments to
its instrument list, the same append-trick already used for the value-history
benchmark instrument — so the existing global "Refresh" button keeps
watchlist prices current too, no new bulk-refresh endpoint needed.

**A real bug caught by the test suite, not by inspection**: the first version
of `_annual_dividend_per_share`-style reasoning doesn't apply here, but an
analogous one did — `compute_scores` silently drops any instrument whose
`category` is `None`, and neither `get_or_create_instrument` nor
`create_manual_position` (an existing, pre-existing gap, not introduced here)
ever set one for a hand-typed symbol. Without a fix, every watchlist add would
score literally nothing, defeating the feature's entire point. Fixed narrowly,
scoped to this new endpoint only (not touching `create_manual_position`):
`looks_like_equity()` (`app/symbols/mapping.py`) — this codebase's own
existing heuristic, its docstring already says "for manual entries, where no
category exists" — decides a plausible default of `STOCK` before calling
`get_or_create_instrument`.

**A real regression caught before it shipped**: the first test run against
the real provider chain revealed `POST /api/watchlist`'s best-effort price
fetch was reaching the actual, no-key-required Boursorama provider over the
real network during every test that added an item — confirmed live (a
standalone script fetched a genuine LVMH price). Fixed with an autouse
fixture pinning `app.routers.watchlist.get_provider_chain` to an empty chain
by default in the new test file; tests that want a working fetch call
`use_provider` themselves. Suite runtime for the affected files dropped from
24s to 5s once fixed, confirming real network calls had been happening.

Frontend: `PriceStatusBadge`, `ScoreBadge` (+ its `scoreBand` helper), and
`SortableHeader` extracted out of `PositionsTable.tsx` into their own files
(the latter genericized to `SortableHeader<K extends string>`) so
`WatchlistTable.tsx` could reuse them without duplicating ~80 lines — a pure
refactor, verified unchanged behavior on the Portfolio page before building on
top of it. `sortValue`/`SortableKey` stayed private to `PositionsTable.tsx`
(genuinely `Position`-shaped, little overlap with what a watchlist row sorts
by); `WatchlistTable.tsx` has its own small 7-key union instead.
`ColumnPicker`/`useHiddenColumns`/`ScoreDetailRow`/`Sparkline` were already
generic and reused verbatim. New `AddToWatchlistForm.tsx` mirrors
`ManualPositionForm.tsx`'s collapsed-card/debounced-autocomplete pattern.
Distance-to-target coloring reuses `signClass` from `format.ts` but negates
the value first — below target is the *favorable* direction here, the
inverse of every other signed metric in this app, so a plain `signClass`
would color it backwards; verified live (a price above target renders with
the "negative" class, correctly reading as "not yet"). A row gets a CSS-only
"opportunity" highlight when price is at/below target **and**
`scoreBand(composite) === 'high'` — reusing the score badge's own cutoff so
the two can never drift apart, deliberately not a new blended metric (this
app's whole scoring design keeps independent signals visible rather than
averaging them into one number that hides which one is doing the work).

18 new backend tests (CRUD, both directions of the held/unheld invariant,
`distance_to_target_pct`'s three-way `None`-safety, the anti-join's
disappear-then-reappear-with-original-data behavior, refresh-inclusion/
exclusion). Full suite: 498 passed (was 480). `tsc -b`/lint clean.

Verified live against the real portfolio: added MSFT.US (genuinely unheld)
with a target of 400 — got a real fetched price (484.31), correct category
("Stocks"), a real Technical score (Value/Growth/Quality correctly "No data"
— no fundamentals fetched yet, a separate action), distance computed as
+21.08% and styled as the "not yet there" color, exactly as designed; the
score breakdown correctly showed "Dividend yield — Missing data" for this
unheld instrument, confirming Decision 3u.5's lot-history guard holds here
too. Confirmed the 400 rejection renders a clear message when trying to
watchlist AAPL.US (a real held position). Deleted the test entry afterward —
the real watchlist is empty again, as it should be until the user adds
something themselves.

## Decision 3u.9 — Fundamentals refresh gets a real progress bar (2026-08-21)

Asked directly: give the fundamentals refresh the same progress bar price
refresh already has. `FundamentalsRefreshButton.tsx`'s own docstring said a
full run is "seconds, not minutes" — true when written (Decision 3r.1), no
longer true since ESEF was added (Decision 3t.1): EDGAR alone is ~28
instruments at a 0.5s throttle (~15-20s), but ESEF's *first* hit in a fresh
process pays a one-time ~37-request entity-index load (~11s+) before its own
handful of instruments' filing fetches. Verified live against the real
portfolio with a forced refresh: **37 instruments, 41 seconds** — squarely in
"long enough that a fake spinner is worse than nothing," the same conclusion
this app already reached twice for prices (`prices/service.py`) and live
quotes (`prices/quote_service.py`).

This is that exact pattern a third time, not a new design.
`app/fundamentals/service.py` gained a `FundamentalsProgress` dataclass
(`running`/`total`/`done`/`current_symbol`/`started_at`/`finished_at`/`report`)
plus `_progress_lock`/`_set_progress`/`_advance_progress`/
`get_fundamentals_progress()` — copied structurally from
`prices/service.py::RefreshProgress`. `fetch_fundamentals` stays exactly as
sequential as it already was (no `ThreadPoolExecutor` — that decision is
independent and still correct at ~30 instruments); it just became a
non-blocking-lock-acquiring wrapper around a new `_fetch_fundamentals_locked`
that advances progress once per instrument in the same loop that already
existed. Also added, mirroring `_refresh_lock`: a `_fundamentals_lock`
guarding against two concurrent refreshes doubling the EDGAR/ESEF request
spend — a real, not hypothetical, concern this app already got burned by once
for prices (see that decision's own docstring).

New `GET /api/scoring/fundamentals/refresh/status` (copied from
`GET /api/prices/refresh/status`) and `FundamentalsRefreshStatusOut` schema
(copied from `RefreshStatusOut`). `POST /api/scoring/fundamentals/refresh`'s
docstring corrected — no longer claims no progress endpoint exists.

Frontend: extracted `ProgressBar` out of `RefreshPanel.tsx` (previously
private to that file) into its own `components/ProgressBar.tsx`, widened
from a `RefreshStatus | QuoteStatus` union to a minimal structural type
(`{total, done, current_symbol}`) so the new `FundamentalsRefreshStatus`
satisfies it too without a third union member — pure refactor, `RefreshPanel`
verified unchanged. `FundamentalsRefreshButton.tsx` rewritten to mirror
`RefreshPanel`'s single-phase polling (mount-resume effect + 800ms interval),
rendering the shared `ProgressBar` while `busy`. Reused the existing generic
`prices.progress` i18n key for the label (its wording was never
prices-specific) rather than adding a near-duplicate; added
`fundamentals.alreadyRunning` (en/fr/pl) for the new lock's rejection
message, and a small branch in the button so that message actually renders
distinctly instead of falling through to a confusing "0 updated, 0 already up
to date..." summary.

6 new backend tests: progress advances mid-run and settles correctly after
(captured via a fake provider's `fetch()` hook recording a snapshot from
*inside* the sequential loop — no real threading needed, since the loop
itself is sequential); a concurrent second call is refused and touches
nothing; the lock releases afterwards; the new status endpoint reflects a
completed run. Full suite: 504 passed (was 498). `tsc -b`/lint clean.

Verified live against the real portfolio with a forced refresh
(`force=true`, bypassing the daily-freshness cache to exercise the real slow
path): polled the new status endpoint directly mid-run and watched `done`
climb 8 → 22 → 27 → 37 while `current_symbol` advanced through real holdings
(GOOGL.US, ARCC.US, CAC.FR...), then settle to `running: false` with a
complete report — 32 updated (28 via EDGAR, 4 via ESEF: AI.FR, MC.FR, DSY.FR,
AF.FR, the same four ESEF-fallback names from Decision 3t.1), 5
not_applicable (the ETFs), 0 failed, total wall-clock 41 seconds.

## Decision 3u.10 — A reference map, not just a log (2026-08-21)

User asked directly why finalizing Phase 4 (Watchlist) took so much exploring,
and whether it was avoidable. Real answer: this app's own "reuse, don't
duplicate" culture only works if what already exists is actually findable —
and `WatchlistItem` had sat unused and completely undocumented since the
project's very first migration, which is exactly what made it a genuine
surprise mid-plan rather than a five-second lookup.

DEVLOG answers *why* something is shaped the way it is, but was never meant
to answer *what exists right now* — a chronological log of decisions isn't a
lookup table, and searching it to answer "does a progress-tracking pattern
already exist" or "what does WatchlistItem actually contain" is exactly the
exploration that's expensive to redo every time.

Added two new root-level files:
- **`ARCHITECTURE.md`** — a reference, not a narrative: every model (with
  table name and one-line purpose), every router's endpoints, and a
  "patterns" section naming the reusable idioms this codebase already has
  (the progress-tracking dataclass+lock pattern, built three times now for
  prices/quotes/fundamentals; `get_or_create_instrument`; the anti-join
  self-healing trick from the Watchlist; the shared frontend components).
  Built from a fresh scan of the actual code (routers, `models.py`), not from
  memory of this conversation — verified against a second independent scan
  immediately after writing it, confirming an exact match (the only two
  "misses" were a verification-script limitation with multi-line decorators,
  not real gaps).
- **A working-conventions file** — the standing rule that makes the reference
  actually stay a reference: update `ARCHITECTURE.md` in the same piece of
  work whenever an endpoint, model, or reusable pattern is added or changed,
  the same discipline this DEVLOG already gets. Loaded automatically at the
  start of every session, which is what made this durable across
  conversations rather than a one-off intention that only held within one.
  (Later removed from the repository — see the project's own housekeeping
  around going public.)

Real test of the rule, immediately: this very entry is the fix for the rule
almost being broken on its first day — the conventions/ARCHITECTURE.md work
itself had no DEVLOG entry until the user asked "is the DEVLOG up to date?"
and the honest answer was no.

## Decision 3u.11 — Phase 5: hidden gems screener, and a latent Watchlist gap fixed along the way (2026-08-22)

Phase 5 per the README roadmap: surface promising stocks the user doesn't
already hold or watch. Scope was decided upfront rather than guessed at: the
candidate universe is a list the user maintains by hand (tens to a couple
hundred symbols), not an index-constituent pull — every phase of this app has
been shaped by tight free-tier provider quotas, and scanning an arbitrary
market-wide universe simply isn't payable on them.

Architecturally this is Phase 4's Watchlist pattern, one layer further out —
not a new design. A new `ScreenerCandidate` model (own Alembic migration,
since unlike `WatchlistItem` it wasn't already dormant in the baseline) mirrors
`WatchlistItem` but drops `target_entry_price`/`note`: a screener candidate
isn't about a planned entry point, only "is this worth a look." The new
`routers/screener.py` composes the same building blocks Watchlist already
established — `get_or_create_instrument`, `looks_like_equity`,
`compute_scores`/`score_to_out` — behind the same anti-join self-healing
shape, extended one step further: a candidate is hidden from every read the
moment it's *either* bought *or* watchlisted (either means it's no longer
hidden), not just bought. `GET /api/screener/scores` is the one real
behavioral departure from Watchlist's `/scores`: results are sorted composite
descending (`None` last, so a candidate still needing a fundamentals refresh
stays visible instead of vanishing), since ranking is the whole point of a
screener.

While wiring screener candidates into both refresh loops (mirroring how
Watchlist instruments get pulled into `POST /api/prices/refresh`), a real gap
surfaced: `POST /api/scoring/fundamentals/refresh` had only ever gathered
*held* instruments — Phase 4 added Watchlist to the price refresh but never to
the fundamentals refresh, so a watchlisted instrument's `Fundamental` rows
have never actually been kept fresh by that button. Fixed now by extending
`refresh_fundamentals` to gather held ∪ watchlist ∪ screener (deduplicated by
id), the same three-source composition `prices.py` already used for two
sources. A test now pins this down directly (`test_refresh_also_covers_watchlisted_and_screener_instruments`).

Frontend mirrors the Watchlist trio closely (`AddToScreenerForm`,
`ScreenerTable`, a `Screener` page component), but slots into the `/gems` nav
route and `gems.*` i18n keys that were already reserved for this phase
(previously a `Placeholder` page, now deleted along with the
`placeholder.comingIn`/`phase.5` keys that were its only remaining
consumers — Phase 6 will need its own instance of that pattern when it
lands, same as every other phase has just built its real page directly
rather than keeping scaffolding around). The old placeholder copy claimed
"screening an index universe," which no longer matches the actual design —
corrected in the same pass.

Verification: 521 backend tests pass (14 new in `test_screener_api.py`,
covering both anti-join directions plus the composite-descending sort order),
`tsc -b`/`oxlint` clean on the frontend.

While autogenerating the screener migration, Alembic also flagged an
unrelated pending change: `ProviderUsage.period_key` is `String(16)` in
`app/models.py` but the live SQLite column was still `VARCHAR(10)` — the
model was widened at some point without a matching migration, so schema and
ORM had silently drifted apart. No live bug (SQLite doesn't enforce VARCHAR
length), but it meant `alembic check` would flag it on every future
migration. Split out into its own migration
(`0d3b4d0b7753_widen_provider_usage_period_key_to_16_.py`) rather than
bundling it into the screener change. Applying it surfaced a second, more
fundamental gap: `alembic/env.py` had no `render_as_batch=True`, so SQLite
rejected the plain `ALTER COLUMN ... TYPE ...` Alembic generated
(`near "TYPE": syntax error` — SQLite has no native column-type alter).
Fixed by enabling batch mode in both `run_migrations_offline` and
`run_migrations_online`, then regenerating the migration so it emits
`op.batch_alter_table(...)` (rebuild-and-swap), which SQLite does support.
This was the first migration in the project's history to alter an existing
column rather than just create tables, so the gap hadn't been hit before.
Verification: `alembic upgrade head` applies cleanly, `sqlite3 ... ".schema
provider_usage"` shows `VARCHAR(16)` with the unique constraint and index
intact, `alembic check` reports no further drift, full suite still at 521
passed.

## Decision 3u.12 — Phase 6: free news/sentiment alongside paid AI commentary (2026-08-22)

Phase 6 was scoped from the start (Decision 0.3) as Perplexity qualitative
commentary — one instrument at a time, on explicit request, 7-day cache,
never contributing to the score. That design still stands. What changed:
the user asked for it alongside a free complement, Alpha Vantage's
`NEWS_SENTIMENT` endpoint — real recent headlines plus a per-instrument
sentiment score, no LLM involved, at no cost.

Both are "fetch one thing about one instrument, cache it for N days, never
touch the score" — the same shape twice, with different costs and therefore
different UX weight. `analysis/news_service.py::get_news` and
`analysis/commentary_service.py::get_commentary` share one structure: a
`cached = db.get(Model, instrument.id)` lookup, a date-granularity freshness
check, fetch-and-persist on a miss. Neither table (`news_sentiments`,
`instrument_commentaries`) is ever read by `scoring/service.py` — the same
"comments on the score, never contributes to it" principle from Decision 0.3,
extended to the free source too.

`AlphaVantageProvider.fetch_news_sentiment` lives directly on the existing
price-provider class rather than a separate client, specifically so it
shares `self._throttle` with `fetch_daily` — Alpha Vantage's real 5-req/min
limit is per account, not per endpoint, so two independent throttles could
together exceed it during concurrent activity (a price refresh in flight
while a user expands a news panel). `registry.py::get_alpha_vantage_provider()`
pulls the exact chain instance by name rather than constructing a fresh one,
guaranteeing that shared state. `perplexity.py` is the opposite: a standalone
client with no throttle at all, since every call is one explicit user
action, never a batch.

A real, if minor, gap surfaced and got fixed along the way: the Perplexity
settings fields (`perplexity_api_key`, `perplexity_model`,
`perplexity_cache_ttl_days`) have existed in `config.py` since the project's
first day, and `GET/PUT /api/settings/api-keys` already round-tripped a
`perplexity` field — but `GET /api/settings/providers` (what the Settings
page actually renders from) never included it, so there was no way to enter
or test that key through the running app at all. Fixed with the identical
manual-append + special-cased `verify-key` branch `sec_user_agent` (EDGAR)
already established for exactly this situation — a configured integration
that isn't part of the price-provider chain.

A second bug, caught by a test rather than shipped: the N-day TTL check in
both new service modules initially compared `cached.fetched_at >=
datetime.now(UTC) - timedelta(days=N)` directly — a full-datetime
comparison. `DateTime` columns round-trip through SQLite as naive (tzinfo
isn't preserved), while `datetime.now(UTC)` is aware; comparing them raised
`TypeError` the moment a cache-hit test re-fetched a row across a session
boundary. Fixed by comparing at date granularity instead
(`cached.fetched_at.date() >= today - timedelta(days=N)`), the same idiom
`fundamentals/service.py::_already_fresh_today` and
`prices/service.py::_asked_today` already use for their own freshness checks
— this codebase already had the right answer twice over, just hadn't been
reached for a third time yet.

Frontend: a second, independent expandable row (`InsightsBadge` +
`InsightsDetailRow`) alongside the existing score row, wired into all three
instrument tables (Positions, Watchlist, Screener) the same way the score
row already is. Asymmetric by design: news fetches automatically the moment
the row expands (free, and expanding the row already is the one-instrument
explicit action), while AI commentary waits for its own separate button —
Decision 0.3's "on explicit request" language was written specifically about
the paid call.

Verification: 561 backend tests pass (40 new, spread across
`test_alpha_vantage_provider.py`, `test_perplexity_provider.py`,
`test_news_service.py`, `test_commentary_service.py`, `test_insights_api.py`,
and an extension to `test_settings_api.py`), `tsc -b`/`oxlint` clean. Live:
confirmed `perplexity` now appears in `GET /api/settings/providers` with a
real description and signup URL, disabled until a key is saved — the exact
gap this closed.

**Two more real bugs, caught live against the actual portfolio (real Alpha
Vantage key configured, not the disabled-in-tests default) rather than by
the test suite above — worth being honest that "tests pass" isn't the same
as "verified live":**

1. **A genuine concurrency race in the insert-or-update logic.** Expanding a
   row's insights fires the news fetch on mount; React 18 StrictMode
   (already on in this app — `main.tsx`) intentionally double-invokes every
   effect once in development specifically to catch exactly this class of
   bug. Two near-simultaneous requests for the same never-before-cached
   instrument both saw `cached = db.get(NewsSentiment, id)` return `None`,
   and both tried to `INSERT` a row with the same `instrument_id` primary
   key — the second commit raised `IntegrityError` and the endpoint 500'd.
   Reproduced first live (`curl` two concurrent `POST /api/insights/2/news`
   calls — one 200, one 500), then pinned down with a deterministic
   regression test in both `test_news_service.py` and
   `test_commentary_service.py` (a fake provider that inserts a "competing"
   row from inside its own call, simulating the other session's concurrent
   insert). Fixed by catching `IntegrityError` on the insert, rolling back,
   and re-fetching-then-updating instead of crashing — same "one instrument
   at a time" real-world exposure this app already handles for concurrent
   price refreshes (Decision 3n.1), just triggered here by a UI action
   rather than a batch loop.
2. **The frontend fix for bug 1's symptom introduced a second, worse bug.**
   A `useRef` guard was added to `InsightsDetailRow.tsx` so StrictMode's
   duplicate invocation wouldn't fire a second real fetch at all (not just
   survive the race server-side) — good instinct, wrong execution: the
   effect's own per-invocation `cancelled` cleanup flag got set to `true` by
   StrictMode's synchronous cleanup between the two invocations, and since
   the ref-guard skipped starting a *replacement* fetch, the one real
   in-flight request's eventual `.then(() => { if (!cancelled) setNews(...) })`
   silently discarded its own result — the row got stuck on "Loading…"
   forever despite the network tab showing a clean single 200. Caught by
   re-checking the live page after the first fix, not by any automated
   test. Fixed by checking `fetchedForRef.current === instrumentId` at
   resolution time instead of a separate `cancelled` boolean — the ref is
   exactly the right "is this response still wanted" signal, since nothing
   resets it except a real `instrumentId` change, unlike a per-closure flag
   that StrictMode's cleanup flips regardless.

## Decision 3u.13 — Watchlist target-price alerts, in-app only (2026-08-24)

Asked directly what the app was still missing after all six roadmap phases;
the answer picked as most impactful: the Watchlist already computes
`distance_to_target_pct` per item, but nothing surfaces "a target was
reached" anywhere except the row's own highlighting on the Watchlist page
itself — invisible unless that page happens to be open. Explicit choice
among in-app-only / in-app + browser desktop notification / email: in-app
only, since email would be this project's first outbound-send integration
(a new SMTP dependency) for a personal single-user local tool that has
never needed one, and a desktop notification only fires while the tab is
open anyway — no real benefit over just showing the count.

No backend change needed: `GET /api/watchlist` already returns
`distance_to_target_pct` per item (`routers/watchlist.py`), computed the
same way the table's own opportunity highlighting already reads it.
`components/AlertsBell.tsx` polls it every 60s while the app is open and
shows a small badge in the top nav (`🔔 N`) linking to `/watchlist` —
global, so it's visible from Portfolio/Transactions/any page, not just
Watchlist. Deliberately a looser condition than the table's existing
"opportunity" highlight (which also requires a high composite score):
this counts a target hit on price alone, since that's the literal thing a
"price alert" means — the two are different questions answered from the
same field, not a duplicate.

Verification: `tsc -b`/`oxlint` clean. Live: set a real watchlist item's
target above its current cached price (forcing `distance_to_target_pct`
negative), confirmed the badge appeared with the correct singular tooltip
and count, clicking it navigated to `/watchlist`, and it disappeared again
once the target was cleared — then cleared the test target back to `null`
so no test data was left in the real watchlist.

## Decision 3u.14 — Inline target-price editing for existing watchlist rows (2026-08-24)

A real gap surfaced while testing 3u.13's alert bell: `PATCH /api/watchlist/{id}`
(target price + note) has existed since Phase 4, and `api.updateWatchlistItem`
has sat in `client.ts` since the same phase — but nothing in the frontend
ever called it. The only way to set a target price was at creation time, in
`AddToWatchlistForm`; once a symbol was already on the watchlist, there was
no UI path to add or change one at all.

`WatchlistTable.tsx` gets a whole-row-becomes-editable mode for its target
and note cells, mirroring `Transactions.tsx`'s existing inline-edit
convention (`editingId`/`editDraft` state, an Edit button that swaps to
Save/Cancel) rather than inventing a new interaction pattern — kept local to
the table component itself, though, matching how it already owns
`expandedId`/`expandedInsightsId` locally rather than lifting state to the
page the way `Transactions.tsx` does. `Watchlist.tsx` gained one new
one-line `handleUpdate` wrapping `api.updateWatchlistItem` + reload, passed
down as a new `onUpdate` prop — no different in shape from the existing
`onDelete` prop.

Verification: `tsc -b`/`oxlint` clean. Live, on the real watchlist: opened
edit mode on a real row, set a target above the cached price, saved, and
confirmed both the table's own distance column and the 3u.13 alert bell
(after a reload) picked it up correctly; separately verified clearing the
target back to blank round-trips to `null` (not an error or a stray `0`);
left the row exactly as found afterward.

## Decision 3u.15 — Target allocation by asset class, descriptive only (2026-08-25)

Prompted by a broader "what's this app still missing" review that also
proposed per-position "Conserver/Renforcer/Réduire" verdicts — deliberately
not built: that crosses from descriptive indicators into personalized
buy/sell advice, conflicting with this app's own stated design (the
disclaimer: "this tool produces indicators... the decisions remain yours",
and Decision 0.3: commentary "comments on the score, does not give a second
opinion"). Target allocation stays on the descriptive side of that line — a
gap against a range the user configured themselves, never a suggestion to
trade a specific security. Scoped down deliberately to a single well-defined
slice: global portfolio (not per-account), asset class only (not yet
sector/country/currency, though `GET /api/portfolio/breakdown?by=` already
supports all four dimensions so extending later is cheap), min/max ranges
(not a single exact target), cash excluded (this app has no concept of a
cash balance at all — only `DEPOSIT`/`WITHDRAWAL`/`INTEREST` transaction
records, no running total — a separate future chunk of work), and a static
table with no interactive contribution simulator.

New `AllocationTarget` model (mirrors `SymbolOverride`'s shape: a small,
unique-string-keyed user override, not `WatchlistItem`'s FK-to-instrument
shape, since this keys off a category string). Three new endpoints added
directly to `routers/portfolio.py` rather than a new router, reusing the
same private `_compute_totals`/`_compute_figures` helpers `get_breakdown`
already uses — a new file would have meant exporting those or duplicating
the total computation. `GET /allocation` iterates the **union** of
categories actually held and categories with a configured target: a target
for a category currently at 0% must still appear (the most informative row:
"you want 10% bonds, you hold 0%"), not silently drop because no position
exists. Caught by a test before it shipped: the first draft mirrored
`get_breakdown`'s own `if not total_value: return []` early exit, which
correctly handles "nothing to show" for a breakdown but incorrectly
discarded a configured-but-unheld target whenever the *whole* portfolio
happened to be empty — removed once `_allocation_row`'s own zero-total guard
was confirmed to already handle that degenerate case without crashing.

The "amount to invest" figure is a deliberate, honestly-labeled
approximation: how much this one category alone would need, via new
contributions only, to reach `min_pct` *of the portfolio's current total* —
not solving for the larger total that adding money would itself create. A
"more exact" recursive number would read as more precise than a
single-category, no-selling constraint actually supports; never shown at all
for an over-target category, since nothing here is a sell suggestion.

Frontend: `AllocationTargets.tsx`, self-contained like `PortfolioBreakdown`
(own fetch, no props from `Portfolio.tsx`), inserted directly below it on
the Portfolio page. Config lives inline in the same table (an "Edit"/"Set
target" action per row swapping to min/max inputs) rather than a new
Settings section — confirmed by reading `Settings.tsx` in full that it's
purely API-key configuration with no natural home for this. Third user of
the inline-row-edit convention from Decision 3u.14 (`Transactions.tsx`,
`WatchlistTable.tsx`, now this).

Verification: 572 backend tests pass (11 new), `tsc -b`/`oxlint` clean.

## Decision 3u.16 — Reject-on-add guardrail for symbols no provider recognizes (2026-08-26)

Root cause of a real support question ("on n'arrive pas à récupérer les
fondamentaux et les prix"): the actual portfolio was fine (44/46 prices,
37/42 relevant fundamentals — the rest were legitimately not-applicable
indices/ETFs). The genuine failures were three watchlist rows added minutes
apart while hunting for the right ticker format for the same company
(`ESLOY.US`, `ESLOF.US`, `EI.SW.US`, alongside the one that actually worked,
`EL.PA.US`) — none of them held positions, all three kept failing on every
refresh, forever, for zero chance of ever succeeding.

`add_watchlist_item` and `add_screener_candidate` already best-effort-fetch
a price on add (so a new row shows a real price immediately), but discarded
the result — the row got created regardless of whether the fetch actually
found anything. Fixed by checking the outcome *before* persisting: a new
`is_permanently_unresolvable(message)` helper in `prices/service.py` flags
`SYMBOL_NOT_FOUND`, `NOT_MAPPED`, and `NOT_PRICEABLE` — outcomes
`refresh_instrument`'s own docstring already documents as unrecoverable
"before tomorrow" — and the add is rejected with 422 when one of those hits
and no price bar exists yet. Deliberately does *not* reject on
`NO_PROVIDER` or `RATE_LIMITED`: both are transient/config-shaped, not the
symbol's fault, and could still resolve on a later refresh — rejecting on
those would have broken most of the existing add-tests (the default test
fixture uses an empty provider chain, i.e. `NO_PROVIDER`, and still expects
201).

Does *not* solve the harder half of the underlying problem: true
same-company deduplication across ticker-format variants (`ESLOY` vs `EL`
are unrelated strings for the same issuer) would need identity resolution
via ISIN, which manually-typed symbols don't carry. Out of scope here —
the existing symbol-search autocomplete (`AddToWatchlistForm.tsx`) already
exists to steer users toward picking a canonical match by company name
instead of guessing ticker formats by hand; this guardrail only closes the
cheaper, unconditionally-safe half: a symbol nothing can ever resolve must
never be persisted.

Tests: `test_rejects_a_symbol_no_provider_recognizes` (422, no row created)
and `test_a_rate_limited_symbol_is_still_added` (201 — proves the guardrail
doesn't over-reject) in both `test_watchlist_api.py` and
`test_screener_api.py`. Full suite: 581 backend tests pass.

Cleanup: deleted the three dead Essilor watchlist duplicates from the real
database (`ESLOY.US`, `ESLOF.US`, `EI.SW.US`) — `EL.PA.US` is the one
correct entry and was left in place.

## Decision 3u.17 — ISIN-based duplicate detection for watchlist/screener adds (2026-08-26)

Pushback on 3u.16, and rightly so: the reject-on-add guardrail only catches a
symbol that resolves to *nothing*. It does not catch — and did not catch, in
the real incident — a symbol that resolves *fine* but is the same company as
something already tracked under a different ticker (`ESLOY.US`/`ESLOF.US`
both found real prices via Twelve Data; only `EI.SW.US` was a genuine dead
end). Initially answered "not cheaply buildable" — wrong, on closer look.

The missing piece wasn't a missing capability, it was missing *data*:
manually-typed watchlist/screener adds never get an ISIN from anywhere (only
a broker CSV import supplies one), so there was nothing to compare. Two
options existed to get one: FMP's company-name search (already wired into
the add forms) — ruled out, it's US-only on the free tier and would never
have found a Paris-listed company like this one anyway; or Wikidata, whose
entity-resolution SPARQL query (`providers/wikidata.py::resolve_sector`,
live-verified against real European holdings, Decision 3c.1) already proves
robust company-identity matching by name for exactly this case. Extended it
with `resolve_isin`, reading P946 (ISIN) off the same best-ranked,
confirmed-publicly-traded candidate `resolve_sector` already finds — one
shared SPARQL round trip (`_best_entity`), not a new one.

New optional `company_name` field on `WatchlistItemIn`/`ScreenerCandidateIn`
— auto-filled by the frontend when a symbol-search suggestion is picked,
free to type when entering a raw ticker by hand (exactly the path that
caused the incident). `symbols/duplicates.py::check_for_duplicate` resolves
it to an ISIN, stores it on the instrument (a keeper even without a
duplicate — nothing else will ever populate this for a manual add, and it
unlocks Frankfurt as an ISIN-only fallback provider later), then checks
`find_tracked_duplicate` for another instrument sharing that ISIN that's
actually held/watchlisted/screened elsewhere (not just any row that happens
to share it — an orphan from a rejected add doesn't count). A match becomes
`duplicate_warning` in the response: soft and non-blocking, since two ISINs
for one issuer (a different share class, a dual listing) can legitimately
coexist — the add still succeeds either way.

Real bug caught by the tests before this ever ran live: the response's
`instrument` was being snapshotted (`_watchlist_item_out`/`_screener_candidate_out`)
*before* `check_for_duplicate` mutated `instrument.isin`, so the freshly
stored ISIN never made it into the JSON response even though the DB write
was correct — `test_resolved_isin_is_stored_on_the_instrument_even_without_a_duplicate`
failed until the snapshot was moved after the ISIN resolution. A reminder
that "the DB is right" and "the response reflects it" are two different
claims.

Frontend: both add forms gained an optional "company name" field, filled in
automatically by `pickSuggestion`. A `duplicate_warning` on a successful add
keeps the form open (fields cleared) with a `.notice.warning` instead of
auto-closing — closing immediately would lose a warning nobody had time to
read.

Tests: `TestResolveIsin` (`test_wikidata.py`, mirrors `TestResolveSector`'s
structure) plus `TestDuplicateWarning` in both `test_watchlist_api.py` and
`test_screener_api.py` (no lookup without a `company_name`; warns and names
the existing symbol on a real ISIN match; no warning on no match; ISIN
stored even without a match). Full suite: 589 backend tests pass, `tsc -b`
clean.

## Decision 3u.18 — Closing the retroactive gap: PATCH support + bulk ISIN backfill (2026-08-27)

Immediate follow-up question after 3u.17 shipped: "so I just added `ESLOY.US`
again just now — why didn't it warn me?" Real, reproducible gap: 3u.17's
`check_for_duplicate` only runs at *add* time, so a row that already existed
before the feature shipped — `EL.PA.US`, the one *correct* Essilor entry —
had never gone through it and had no ISIN on file to compare against.
Nothing to catch a duplicate of something that itself was never checked.

Two distinct fixes, both needed:

1. **`PATCH /api/watchlist/{id}` and the brand-new `PATCH /api/screener/{id}`**
   now accept the same optional `company_name` the create endpoints do,
   running `check_for_duplicate` retroactively. `ScreenerCandidate` had no
   PATCH endpoint at all before this — nothing else about a candidate is
   ever user-edited, so this one exists purely for company-name entry.
2. **`symbols/duplicates.py::backfill_isins`** (`POST /api/portfolio/backfill-isins`)
   — a name doesn't always need to be *typed*: a broker-imported instrument
   already carries one (`instrument.name`), and that name survives even
   after the position is fully closed and the same instrument gets
   re-tracked on the watchlist (real example found live: `NKE.US` → "Nike",
   `CELH.US` → "Celsius Holdings", both pre-dating this feature entirely).
   For those, resolving the ISIN needs zero user input — the backfill
   sweeps every held/watchlisted/screened instrument with a `name` but no
   `isin` and resolves it automatically.

Real bug caught by `test_resolved_isin_is_stored_on_the_instrument_even_without_a_duplicate`-
style testing during this pass: the response's `instrument` snapshot was
being built *before* `check_for_duplicate`'s side effect (setting
`instrument.isin`) ran — same class of ordering bug as 3u.17's own fix,
just recurring at the new PATCH call site. Fixed the same way: resolve the
duplicate check first, build the response snapshot after.

Live-verified against the real portfolio, unmocked: `POST /backfill-isins`
resolved 20 of 29 candidate instruments over a few runs. The remaining 9
are a mix of two honest limits, not bugs — four are index/ETF products
(`CAC 40`, two PEA trackers) that Wikidata's entity search finds but that
correctly fail the "must list a stock exchange" (P414) filter, since an
index isn't itself traded; the other five (`Celsius Holdings`, `Okta`,
`Oracle`, `Applied Digital`, `DouYu`, `Honest Company`) are real companies
where Wikidata's ISIN property (P946) is simply sparser than P414/P452 —
confirmed some of these (`Oracle`) resolved fine on a *later* re-run,
meaning the first miss was a transient Wikidata hiccup, not a permanent
gap — same "click again to continue" pattern the price/fundamentals
refresh buttons already established, not something worth adding retry
logic for.

Then closed the actual originating incident for real: used the new PATCH
path to type "EssilorLuxottica" onto the pre-existing `EL.PA.US` watchlist
row. It correctly resolved the real ISIN (`FR0000121667`) and flagged the
leftover `ESLOY.US` test entry as a duplicate — the exact warning that
should have fired the first time, now firing, live, against the real
database.

Frontend: `WatchlistTable.tsx`'s existing inline-edit row gained a company-
name input (defaulting to `instrument.name` when present); `ScreenerTable.tsx`
gained inline editing for the first time (it had none — Delete only — since
company name is now its one editable field). A shared `BackfillIsinsButton.tsx`
sits in both pages' headers.

Tests: `test_api.py::TestBackfillIsins` (backfills a named instrument;
skips nameless, already-ISIN'd, and untracked instruments; a name that
resolves to nothing is checked but not counted as updated) plus a PATCH-
retroactive test in both `test_watchlist_api.py` and `test_screener_api.py`.
Full suite: 598 backend tests pass, `tsc -b`/`oxlint` clean.

**Addendum, found minutes after shipping the above**: a user added `NFLX.US`
with `company_name: "Netflix"` — the ISIN resolved correctly, but the row
displayed no name at all, unlike a broker-imported instrument. Root cause:
`check_for_duplicate` used `company_name` purely as a Wikidata query
parameter and never persisted it anywhere — the typed name was silently
discarded once the ISIN lookup was done with it. Fixed by also setting
`instrument.name = company_name` (when not already set) as its own
unconditional side effect, independent of whether an ISIN or duplicate is
found. Both `EL.PA.US` and `NFLX.US` in the real database had been touched
by the pre-fix code and were missing their name; re-issued the same PATCH
call against each (idempotent) to backfill it now that the fix is live.
Tests: `test_company_name_is_stored_as_the_instrument_name` in both
`test_watchlist_api.py` and `test_screener_api.py`. Full suite: 600
backend tests pass.

## Decision 3u.19 — Position/watchlist signals: a transparent score+allocation combination, not a verdict (2026-08-27)

User asked directly for an "Acheter/Vendre/Conserver" (Buy/Sell/Hold)
recommendation "to help decide" — refused the first two times it came up,
for the same reason a per-position verdict was already rejected once before
this session even reached allocation targets: it crosses from descriptive
indicator into personalized investment advice, contradicting the app's own
disclaimer and Decision 0.3. The user's final framing — "it's our own app,
we can do what we want with it" — is a legitimate point about their own
private tool, and not something I have standing to keep refusing on their
behalf. Built it, but designed to stay on the honest side of the line that
prompted the refusal in the first place: the label is a **fixed, fully
transparent combination of two indicators the app already computes and
displays separately** — the composite score and the allocation gap (or
target-price distance) — never a new analysis, never phrased as a trade
order.

Design, confirmed with the user via two scoped questions (which instruments,
which exact rule): `scoring/service.py::score_band` buckets a composite
score into "high"/"mid"/"low"/"none" using the same 66/33 thresholds the
frontend's own `scoreBand` (`ScoreBadge.tsx`) already uses — duplicated
deliberately rather than shared across the Python/TypeScript boundary, same
call already made for other one-off threshold checks in this codebase.
`routers/portfolio.py::_position_signal(band, allocation_state)`: "high" +
"under" → reinforce, "low" + "over" → reduce, either input missing
("no_target", or "none" score) → "not_applicable" — deliberately never
defaulted to "hold" in that case, since "hold" reads as a confident verdict
and the honest answer when data is missing is "can't say", not "do
nothing". `GET /api/portfolio/position-signals` computes this for every
held instrument, reusing `compute_scores` and the exact same
`_current_allocation_values`/`_allocation_row` helpers `GET /allocation`
already uses — no new computation, only a label for the combination.
`GET /api/watchlist/signals` mirrors this for unheld instruments, combining
score with distance to the target entry price instead of an allocation gap;
it can only ever return "reinforce"/"hold"/"not_applicable" — never
"reduce", since there is nothing held to reduce. This also formalizes and
replaces `WatchlistTable.tsx`'s pre-existing, purely-frontend
`isOpportunity` row-highlight logic (same underlying condition, now
computed once server-side and exposed explicitly instead of silently
duplicated in a component).

Wording was chosen carefully even after agreeing to build it:
"Renforcer"/"Réduire" (position-sizing language) rather than
"Acheter"/"Vendre" (trade-order language) — same softer vocabulary already
used for the allocation feature's own rejected verdict proposal earlier
this session. Every `SignalBadge` tooltip spells out the exact score and
allocation-state (or distance) values that produced the label, so the
result is never a black box — a user can always see it's "just" those two
numbers combined by a fixed rule, not some opaque model output.

Frontend: new shared `SignalBadge.tsx` (reused by both tables), a `signal`
column added to `PositionsTable.tsx` (right after the score column) and
`WatchlistTable.tsx` (right after its score column, replacing the old
CSS-only highlight computation with one driven by the real signal).

Tests: `test_position_signals.py` (new) — all four position-signal
outcomes with a controlled, monkeypatched `compute_scores` (constructing
real fundamentals to hit an exact composite would obscure what's actually
under test: the combination rule, not the scoring pipeline), plus the
watchlist-signal equivalents including an explicit "never reduce" check.
Full suite: 610 backend tests pass, `tsc -b`/`oxlint` clean.

**Addendum, same day**: a review of the shipped feature pointed out that
"Renforcer"/"Réduire" — chosen specifically to *not* read as "Acheter"/
"Vendre" — still failed the actual test that mattered: a verb, any verb,
reads as an instruction. "Renforcer" is a softer instruction than "Acheter",
not a non-instruction. The distinction that should have driven the wording
from the start: a fact ("high score, under-allocated") describes a state;
a verb ("reinforce") tells you what to do about it. The rule itself was
never the problem — only the presentation layer translating its output
into imperative language.

The review also caught a second, more substantive gap: `DOYU.US` scoring
17/100 while its `STOCK` category sits 40 points over its allocation target
does not, on its own, show that *this specific holding* is the one to trim
— the score is about this instrument, but the allocation gap is about the
entire category, which might hold several very different positions. The
combination is still a legitimate "worth a second look" flag; it just
isn't a statement about this one position specifically, and the original
tooltip didn't say so.

Fixed with a **frontend-only** change — the backend rule, the `signal` enum
values (`reinforce`/`reduce`/`hold`/`not_applicable`), and every existing
pytest assertion on those values are untouched, since none of them ever
asserted on display text:
- `SignalBadge` now takes a pre-composed `label` string instead of
  translating the signal code into a verb internally. Both convergence
  cases ("reinforce" and "reduce") render as a fact — "High score ·
  under-allocated" / "Low score · over-allocated" — never a direction
  word. "hold" renders as "—" (deliberately not a reassuring word like
  "fine", which would itself be a verdict). "not_applicable" renders as
  "Insufficient data".
- Both convergence cases now share one `.tag.unresolved` (amber) styling
  instead of a green/red pair, matching `AllocationTargets.tsx`'s own
  under/over convention exactly — flagging that two signals line up, not
  implying which direction is "good".
- `PositionSignalOut` gained `gap_pct` (the same value `AllocationRowOut`
  already computes, just not previously exposed here), so the tooltip can
  state the precise magnitude ("over-allocated by 40.0 pts") instead of
  just the word.
- The position tooltip gained an explicit sentence: this compares the
  holding's own score with its *entire asset class's* allocation gap, not
  a full evaluation of this specific position.

Live-verified in French against the real portfolio: `DOYU.US` now shows
"Score faible · surpondéré" in amber, tooltip reading "Score 17/100
(faible) · Allocation Actions : Surpondéré (40,01 pts). Compare le score
propre à ce titre avec l'écart global de toute sa classe d'actifs — pas
une évaluation complète de cette position précise." All other positions
show a plain "—". Re-ran the same temporary-target-price check on
`NFLX.US` as before (reverted after): "hold" now reads "—" with the real
-18,54% distance still in the tooltip.

Tests: extended `test_position_signals.py` with a `gap_pct` assertion.
Full suite: 610 backend tests pass, `tsc -b`/`oxlint` clean.

## Decision 3u.20 — Discovery: automated candidate search, two independent sources (2026-08-28)

Requested for the Pépites (hidden gems) page: a system that actively
searches for and surfaces high-potential/undervalued stocks, rather than
only screening symbols the user types in by hand. The obvious approach —
FMP's real stock-screener endpoint — is not available: `GET
/stable/company-screener` returns HTTP 402 "Restricted Endpoint... upgrade
your plan" on this app's actual configured free-tier key, confirmed live
via a direct request before writing any code against it.

Asked the user how to source candidates given that; answer: scrape
Finviz's free screener page, reusing the existing Value/Growth pillars for
"undervalued"/"high potential" rather than inventing a new definition.
Before building a scraper, checked `https://finviz.com/robots.txt` — it
disallows `/screener?*` for any custom-filtered query, whitelisting only a
fixed list of specific preset scans (`Allow: /screener?v=...&s=<preset>`),
none of which map to a P/E or growth-rate filter. Refused to build a
custom-filtered scraper against an explicitly disallowed path. Asked the
user again with the finding in hand: static S&P 500 list + the existing
scoring engine, or Finviz's whitelisted presets as a narrower, separate
signal? Answer: **both** — which is what shipped.

**Source 1 — static S&P 500 universe.** Fetched once, live, from Wikipedia
(`List_of_S%26P_500_companies`) and committed as a bundled JSON file,
`backend/app/data/sp500_constituents.json` — not a live API call on every
use, since the constituent list changes rarely and re-scraping Wikipedia on
every import would be pointless load for no freshness gain. `POST
/api/discovery/import-sp500` bulk-inserts these 503 symbols as
`DiscoveryCandidate` rows (`source="sp500"`), reusing
`get_or_create_instrument` so mapping/category resolution happens exactly
as it would for a manual entry. `POST /api/discovery/refresh` then
evaluates a **fixed batch size** (`BATCH_SIZE = 20`, not a time budget) of
not-yet-verified candidates per click — `fetch_fundamentals` has no
internal time-budget cutoff the way `refresh_many` does, so bounding the
batch size is what keeps one HTTP request finite; "click again to
continue" for the rest, the same pattern already used elsewhere for
long-running operations.

**Source 2 — Finviz whitelisted presets.** `providers/finviz_screener.py`
requests only the two preset scan codes `robots.txt` actually allows that
carry any signal value: `it_latestbuys` (insider buys) and `ta_oversold`
(technical oversold). Parses Finviz's own HTML snapshot-table markup with
`BeautifulSoup` (already an installed transitive dependency of `yfinance`,
now a direct one). `POST /api/discovery/finviz?preset=` fetches, scores,
and returns these live — small result sets, not persisted as a batch.
Deliberately kept a **separate, honestly-labeled signal** in the UI, never
blended into the Value/Growth ranking: insider conviction and technical
oversold are different claims than "cheap relative to fundamentals" or
"growing fast", and folding them into one score would misrepresent what
produced it.

**`DiscoveryCandidate`** (new model, `discovery_candidates` table,
`instrument_id` UNIQUE) is deliberately a separate, much larger and more
uncurated pool than `ScreenerCandidate` — never shown to the user directly.
`GET /api/discovery/candidates?rank_by=value|growth` ranks only the
evaluated, not-yet-tracked candidates (anti-joined against
`Position`/`WatchlistItem`/`ScreenerCandidate`, the same anti-join pattern
used for watchlist/screener) by one existing pillar score from
`compute_scores` — no new scoring logic. A candidate only becomes a real,
tracked "hidden gem" once explicitly added through the existing `POST
/api/screener` flow, same as a hand-typed symbol.

Frontend: `DiscoveryPanel.tsx` on the Pépites page — an S&P 500 sub-panel
(import / evaluate-next-batch / rank-by Value or Growth toggle / ranked
table with an "Add" action) and a Finviz sub-panel (two preset buttons,
each with its own small results table), explicitly separate sections so
the two source's different nature stays visible rather than merged into
one undifferentiated list.

Tests: `test_finviz_screener_provider.py` (new, 6 tests) — including a
compliance-pinning regression test asserting only the two whitelisted scan
codes are ever requested, and that an unknown preset returns empty
*without making a request at all*. `test_discovery_api.py` (new, 13 tests)
— idempotent import, ranking by each pillar with pillar-missing exclusion,
all three anti-join branches, batch-size cutoff with correct `remaining`
count, and Finviz-preset add flow. Two test-infrastructure issues
surfaced and were fixed along the way: constructing a bare `Instrument(...)`
instead of going through `get_or_create_instrument()` leaves
`mapping_status` at `UNRESOLVED`, so `refresh_instrument()` returns
`NOT_MAPPED` without ever calling a provider — any test needing a real
successful refresh must seed instruments the same way manual/watchlist
adds do; and `refresh_many`'s threaded per-instrument refresh
(`ThreadPoolExecutor`, one session per thread) is unsafe against a
`StaticPool`-backed in-memory SQLite engine, so `test_discovery_api.py`
uses a real file-based engine via `tmp_path`, the same fix already
documented in `test_prices_api.py` (Decision 3n.1).

Full suite: 629 backend tests pass. `tsc -b`/`oxlint` clean.

**Addendum, same day**: an external review of the shipped feature raised
three points, evaluated on their own merits rather than applied wholesale.

The one that held up as a real gap: the Finviz scan (`finviz_scan` in
`routers/discovery.py`) is the first place in this codebase where several
live per-instrument fetches — refresh, fundamentals, scoring — run back to
back inside a single request. Every other call site doing this kind of
work (`add_watchlist_item`, `add_screener_candidate`) only ever touches one
instrument, so an unhandled exception there costs at most that one add.
Here, one bad candidate mid-loop would have thrown the whole request away,
discarding every candidate already successfully resolved before it —
worse than the batch operations elsewhere in the app (`refresh_many`,
`fetch_fundamentals`), which already isolate one instrument's failure from
the rest. Fixed by wrapping each candidate's block in its own
try/except: a failure rolls back that candidate's partial writes and
increments a new `failed` count on `DiscoveryFinvizOut`, instead of either
crashing the request or silently shrinking the result set with no trace of
what went missing. Frontend surfaces this count under the relevant
preset's results when it's nonzero. Test: `test_discovery_api.py` gained
`test_one_failing_candidate_is_skipped_and_counted_not_discarding_the_others`,
monkeypatching `compute_scores` to raise for one of two candidates and
asserting the other still comes back with `failed == 1`.

The second point — that "Pépites"/Discovery could read as a predictive
recommendation rather than a research starting point — was already
partly addressed by the existing copy ("pas une nouvelle notion de
sous-évalué"), but the review was right that it never said the word
"recommandation" or "prédiction" outright. Extended `discovery.description`
(en/fr/pl) with one explicit sentence to that effect, rather than adding
three separate warning boxes as proposed — the app already carries a
sitewide disclaimer in the footer, and stacking redundant caveats reads as
noise, not care.

The third point — the Finviz scan's lack of a real progress indicator
during its genuinely slow (live-verified: several minutes for ~10
candidates) sequential run — was acknowledged by the review itself as
optional at this volume, and building a full `RefreshProgress`-style
background job + polling endpoint for a ~10-item, on-demand, not-persisted
scan would be disproportionate to what it's for. Addressed cheaply instead:
a `discovery.finviz.slowNotice` caveat under the preset buttons sets the
right expectation up front, and the pre-existing shared-disable behavior
(`finvizBusy !== null` already disabled both preset buttons while either
ran) was left as is.

**Second addendum, same day**: a follow-up review of the fix accepted the
decision not to build a real per-candidate progress bar, but flagged a
narrower, cheaper gap — with only a static caveat sentence and a button
reading "Saving…", a user watching a 10-minute request could still
reasonably wonder if the click registered at all. Fixed by adding a small
*indeterminate* progress indicator (a new `.refresh-progress-fill.indeterminate`
CSS variant — a sliding segment via `@keyframes`, reusing the existing
`.refresh-progress-track` container rather than a new visual language) plus
an explicit `discovery.finviz.scanningNotice` line ("Scan in progress —
free-tier providers can take several minutes. Don't close this page."),
shown under the Finviz buttons for the whole `finvizBusy !== null` window.
This is deliberately *not* real progress (no count, no per-candidate
ticks) — just a visible sign that the request is alive, which is the gap
that mattered: the button already disabled correctly, an error already
surfaced through the existing `catch`, and re-running after completion
already worked, so nothing else needed changing.

Live-verified end to end: clicked "Oversold", watched the indeterminate
bar and notice appear immediately, waited for the real ~10-minute
sequential scan (fresh S&P/Finviz tickers not yet checked today force a
real network round trip per instrument — same reason the very first
Discovery live-verify took several minutes), and confirmed the bar
disappeared and the 10-row result table rendered in its place with
`failed: 0` correctly hidden.

Full suite: 630 backend tests pass. `tsc -b`/`oxlint` clean.

**Third addendum, same day**: the user reported seeing no candidates at
all on the Pépites page — not a data problem (the backend already had
scored S&P 500 candidates from earlier verification) but a real bug:
`DiscoveryPanel.tsx` never fetched `GET /api/discovery/candidates` on
mount, only in response to "Evaluate next batch" or a "Rank by" click.
Every other self-fetching panel in this app (`Screener.tsx`,
`Watchlist.tsx`, `AllocationTargets.tsx`, `PortfolioBreakdown.tsx`) loads
on mount via its own `useEffect` — this one simply lacked it. Fixed by
adding `useEffect(() => { void loadCandidates(rankBy) }, [rankBy])`, which
both loads on first render and reloads automatically when the Value/Growth
toggle changes — letting `handleRankByChange` drop its now-redundant
explicit `loadCandidates` call (`setRankBy` alone is enough; the effect
picks up the change). Live-verified: reloading `/gems` cold now shows the
20-row ranked table immediately, no click required.

Full suite still 630 backend tests pass (no backend change this time).
`tsc -b`/`oxlint` clean.

## Decision 3u.21 — Discovery gets an explicit Buy/Hold/Sell verdict, by deliberate user request (2026-09-02)

The user asked to change the objective for Discovery specifically: "on veut
des recommendations et predictions pour les pepites" — a direct request for
literal recommendations and predictions, overriding this app's own
established descriptive-only convention (DEVLOG "Decision 0.3", and the
verb-vs-fact lesson from Decision 3u.19's addendum). Given the size and
ambiguity of "recommendation" and "prediction" as asked, clarified via
`AskUserQuestion` before writing any code:

- **Recommendation**: chose "Verdict Acheter/Vendre/Conserver" over a
  softer "top picks" framing — the literal buy/sell/hold verdict this app
  had refused twice before (Decision 3u.19's own opening paragraphs).
- **Prediction**: chose "a real predictive model" over reformulating the
  existing scores. Flagged, and left unstarted this session: a genuine
  forecasting model needs historical price data, feature engineering,
  backtesting, and statistical validation — none of which exist in this
  codebase today. Dressing the existing Value/Growth/Quality/Technical
  scores up as a "prediction" without any of that would be dishonest; a
  real one is a multi-week project, not an extension of the Discovery
  feature just built. Scoped out of this decision — a separate design
  conversation before any code gets written.

**What shipped**: `DiscoveryCandidateOut.recommendation` — "buy" | "hold" |
"sell" | `None`, computed via a new `discovery/service.py::
recommendation_from_composite()` that maps `scoring/service.py::score_band`
(already used by the position-signal feature) directly to a verdict:
high→buy, mid→hold, low→sell, none→`None` (never guessed when there's no
composite score to derive it from). Wired into both `GET
/api/discovery/candidates` (via `ranked_candidates`) and `POST
/api/discovery/finviz` (per-candidate, alongside the existing
try/except-per-candidate isolation from the 3u.20 addendum — a failure
there still can't produce a bogus recommendation for a half-processed
candidate).

This is a **narrow, explicit exception** — Position/watchlist signals
elsewhere in the app (`_position_signal` in `routers/portfolio.py`,
`routers/watchlist.py`'s signals endpoint) are untouched and still render
as fact-based labels ("Score élevé · sous-pondéré", not "Renforcer").
Updated the persistent memory
(`stock-analyst-descriptive-not-verdict-labels.md`) to record this
override explicitly, rather than let it read as a still-universal rule the
next session might "helpfully" revert.

Frontend: new `RecommendationBadge.tsx` — green/gray/red (`tag resolved` /
`tag neutral` / `tag negative`, reusing existing tag color tokens; added
`.tag.negative` since no red tag variant existed yet) for buy/hold/sell,
neutral for `None` ("No data" — never a reassuring default). Added as a
new column to both the S&P 500 ranked table and the Finviz preset tables
in `DiscoveryPanel.tsx`. Rewrote `discovery.description` (en/fr/pl), which
previously said "never a recommendation or a performance prediction" —
now flatly false given the new column — to describe what the feature
actually does instead of what it deliberately avoids.

Tests: `test_discovery_api.py` gained
`test_recommendation_derives_from_composite_score_band` (all three bands
via the ranked-candidates path) and
`test_finviz_recommendation_derives_from_composite_score_band` (same via
the Finviz path), plus an explicit `recommendation is None` assertion on
the existing no-fundamentals Finviz test. Full suite: 632 backend tests
pass. `tsc -b`/`oxlint` clean.

## Decision 3u.22 — Prediction, phase 1: a price-only history backfill (2026-09-03)

Following 3u.21's Buy/Hold/Sell verdict, asked to "on fonce" (proceed) on
the second half of the earlier request: a real predictive model. Before
writing any model code, checked the actual data available in the real
database — this is what determined everything that follows:

```
price_bars:  23,934 rows, 87 instruments, 2025-07-08 → 2026-09-02 (~14 months)
fundamentals: 9,942 rows, 83 instruments, fiscal years 2009 → 2026 (annual, latest-only)
```

Two hard constraints fell out of this:

1. **~14 months of daily bars is not enough for a walk-forward backtest.**
   `prices/service.py::INITIAL_HISTORY_DAYS = 400` is a deliberate choice
   (enough for a 200-day moving average plus margin), not an API limit —
   Twelve Data's `fetch_daily(ref, start, end)` already accepts an
   arbitrary range in one call. A genuine backtest needs several distinct
   market periods to validate across, which 14 months of one period can't
   provide.

2. **Fundamentals cannot be used in a real backtest at all, yet.**
   `Fundamental` rows only ever hold each concept's *latest* known value —
   `fetch_fundamentals` overwrites in place, there is no history keyed by
   filing date. Using *today's* Value/Growth/Quality score to "predict" a
   return from years ago would be lookahead bias: the model would be using
   information that did not exist yet at the date under test. This isn't a
   minor caveat — it rules out fundamentals as a feature source entirely
   until a point-in-time fundamentals history is built (a separate,
   substantial project, not started). `PriceBar`, by contrast, is naturally
   point-in-time safe: a bar dated 2024-03-01 is exactly what was known
   that day. So any real predictive model here can only use price-based
   (technical/momentum) features for the foreseeable future.

Given both constraints, proposed a 3-phase plan and asked the user to
choose the backfill's scope before running anything (real quota/time cost:
Twelve Data's free tier is 800 requests/day at 8s between calls, so the
universe size and window directly set the run's wall-clock time). Chose
**5 years, the same ~87-instrument universe already priced** (not the full
~523-row Discovery pool) — enough distinct market periods for phase 2's
eventual walk-forward validation, ~12 minutes to run, well inside quota.

**What shipped (phase 1 only — no model yet):** `app/prediction/service.py::
backfill_history()` — for every instrument with at least one existing
`PriceBar` row, fetches `BACKFILL_YEARS = 5` years in one call and upserts
via the same `_store_bars()` `prices/service.py::refresh_instrument`
already uses (imported cross-module, same precedent as `routers/
discovery.py` reusing `routers/portfolio.py::_resolve_current_price`).
Deliberately a separate, occasional pull rather than changing
`INITIAL_HISTORY_DAYS` globally: the live app itself only ever needs
~14 months (a 200-day moving average, a 1-year chart), and bumping that
constant would over-fetch for every instrument going forward for a need
only the eventual model has. Same `RefreshProgress`/`FundamentalsProgress`
shape a fourth time: a lock (`_backfill_lock`) serializing runs, a
`BackfillProgress` dataclass polled from a separate request while the
`POST` itself blocks for the run's duration, `GET /api/prediction/
backfill-history/status` for a real (never simulated) progress bar. One
instrument's fetch raising doesn't stop the run — same per-item isolation
already established for the Finviz scan (Decision 3u.20 addendum).

Frontend: `PredictionBackfillButton.tsx`, structurally identical to
`FundamentalsRefreshButton.tsx` (same polling/resume-on-mount shape),
added as a third subsection under `DiscoveryPanel.tsx`'s existing S&P 500
and Finviz sections. Copy is explicit that this step shows no prediction
yet — data collection only — to avoid the button reading as "click here
for the model."

Tests: `test_prediction_api.py` (new, 8 tests) — universe selection
(only already-priced instruments, not the full Discovery pool), bar
upsert counts (existing bars updated in place, only genuinely new ones
counted), per-instrument failure isolation, lock contention (`None`
returned when a run is already in progress, both at the service level and
via the `already_running` flag through the API), and progress-state
correctness after a completed run.

Full suite: 640 backend tests pass. `tsc -b`/`oxlint` clean.

**Explicitly not done, and not started this session:** any actual
prediction model, feature engineering, or backtest. This decision is the
data-collection step only — phase 2 (a technical/momentum model, trained
and validated via walk-forward split over the now-deeper price history)
and phase 3 (wiring a result into the Discovery UI) remain future work.

**Mid-run incident**: `pip install scikit-learn` (for phase 2, started
right after this decision) wrote thousands of files into `.venv/`, which
`uvicorn --reload`'s default file watcher treated as backend source
changes — killing the in-flight backfill mid-run and triggering an
uncontrolled reload storm as WatchFiles kept re-triggering on the
continuing package-file writes. Fixed by restarting the dev server with
`--reload-dir app`, scoping the watcher to the actual source tree. Some
bars were already committed per-instrument before the kill (`price_bars`
grew from 23,934 to 72,973 rows), so nothing was corrupted — just
re-running the backfill cleanly against the now-correctly-scoped server
finished it properly (see 3u.23).

## Decision 3u.23 — Prediction, phase 2: a walk-forward-validated technical model (2026-09-03)

Following up on 3u.22 immediately (user: "on fonce" — proceed) once the
5-year backfill was clean: 87/87 instruments updated, 0 failed, 12,358 new
bars (`price_bars` reached 89,774 rows, 25–1,273 bars per instrument,
avg ~1,032 — roughly 4 years for most, confirming the deeper window
actually landed).

**Features** (`app/prediction/features.py`) — all computed strictly from
bars at-or-before the evaluation date, never looking forward: momentum
over 20/60/120 trading-day windows, price vs SMA50/SMA200, and realized
volatility over a trailing 20-day window. **Label**: the actual realized
forward return 60 trading days out (~3 months) — the only thing allowed to
look forward, and only that far. Samples are taken every 20 bars per
instrument (`SAMPLE_STRIDE_DAYS`), not daily: adjacent daily rows would
share almost their entire lookback window and label horizon, inflating the
apparent sample count without adding independent information.

**Model** (`app/prediction/model.py`): scikit-learn `LogisticRegression`
(added as a new dependency — pinned in `requirements.txt`), trained live on
every call rather than persisted — the dataset is a few thousand rows, well
under a second to fit, matching the same recompute-don't-cache convention
`compute_scores` already uses everywhere else in this app. **Walk-forward
split, never random**: every row is sorted by date, the earlier 70% trains,
the strictly later 30% tests — a random split would let the model see both
sides of the same market period, which a real trade never could.

Real edge case found and fixed while testing: a training period whose
labels are all one class (e.g. a pure, unbroken uptrend has no "down"
examples at all) crashes `sklearn`'s solver outright (`ValueError: ...
only one class`). Rather than let that surface as a 500, `run_backtest`
now checks for this before fitting and returns the split's real shape
(sample counts, date ranges) with `test_accuracy`/`avg_return_*` all
`None` and an explicit `single_class_warning: true` — the honest answer,
not a crash or a fabricated 100%.

**Report is deliberately more than a bare accuracy number**: `low_sample_
warning` (test set under 100 samples — a threshold, not a guess) and the
mean *realized* forward return of the "predicted up" vs "predicted down"
buckets, since a return-magnitude comparison says more about whether a
signal has any real value than accuracy alone does on a roughly-balanced
label.

`POST /api/prediction/backtest` — not yet wired into the Discovery UI on
purpose: presenting a number like this responsibly needs its own framing
decision (accuracy alone reads as more confident than it should), a
separate conversation from building the number itself.

**Real result, run against the actual backfilled database:**
```
84 instruments, 2,395 train samples (2022-06-17 → 2025-05-07),
1,027 test samples (2025-05-07 → 2026-06-18)
test_accuracy: 0.542   (barely above coin-flip)
avg_return_predicted_up:   +6.09%
avg_return_predicted_down: -8.89%
low_sample_warning: false, single_class_warning: false
```
Read honestly: raw directional accuracy is not meaningfully better than
chance, but the two predicted buckets' *average realized returns* are
genuinely separated (~15 points apart) — a real, if modest, signal, over
exactly one test period. Not nothing; nowhere near proof a live trading
signal would hold up.

Tests: `test_prediction_features.py` (new, 8 tests) — lookback-insufficiency
returns `None` rather than a wrong number, momentum/SMA-ratio/volatility
values checked against hand-computed cases, forward-return horizon
boundary. `test_prediction_model.py` (new, 7 tests) — dataset pooling
across instruments, the single-class edge case (added after the crash was
found live), and an explicit assertion that every train row's date
precedes every test row's date (the walk-forward property that actually
matters). Full suite: 655 backend tests pass.

## Decision 3u.24 — Carhart four-factor exposure for held positions (2026-09-03)

Requested alongside a recommendation on how to present 3u.23's backtest
result: "on voudrait aussi inclure dans notre outil [le] Carhart 4 factor
model." A better philosophical fit than the Discovery prediction work —
this is explanatory (what has driven a holding's past returns), not
predictive, squarely inside this app's existing fact-based design without
needing 3u.21's explicit exception.

Two design forks resolved with the user before writing code: **scope**
(held positions only, not Watchlist/Screener/Discovery) and **return
frequency** (daily, reusing the 5-year price history 3u.22 already built,
over the traditional monthly academic convention — daily gives ~1,000+
observations per holding instead of ~60).

**Data source**: Kenneth French's Data Library
(mba.tuck.dartmouth.edu/pages/faculty/ken.french) — free, no API key,
updated monthly at the source. Verified live (`WebFetch` + direct
downloads) before committing to the design: confirmed daily-frequency
files exist for both a US series (`F-F_Research_Data_Factors_daily` +
`F-F_Momentum_Factor_daily`) and a Europe series
(`Europe_3_Factors_Daily` + `Europe_Mom_Factor_Daily`) — the two regions
that matter given the real portfolio's actual holdings (23 US, 12 France,
2 Netherlands, confirmed by querying the real database before assuming
region coverage would be adequate).

**Region-matched, always** (`factors/service.py::region_for_instrument`) —
a US instrument's returns are regressed against US factors, a European
one against Europe's, never mixed. Applying one region's risk-factor
premia to another region's returns would misattribute the loadings to
something that was never actually driving them. An instrument outside
both covered regions reports `not_applicable_reason: "no_region_match"`,
never a guessed region.

**Parser** (`providers/kenneth_french.py::_parse_csv_rows`) handles the
one shared shape across all four source files: a few lines of prose, a
header row whose own first cell is empty, YYYYMMDD-keyed daily rows, then
a copyright footer — plus real-world mess found while writing it against
the actual downloaded files: Windows CRLF line endings and trailing
column whitespace in the Europe files, and Kenneth French's own documented
`-99.99` missing-data sentinel (dropped entirely, never coerced to 0 —
"never guess a number").

**Regression** (`factors/service.py::compute_factor_loadings`): daily
excess return (instrument return minus the region's risk-free rate)
regressed via `statsmodels` OLS against Mkt-RF/SMB/HML/Mom, reporting
alpha, the four betas, R², and alpha's p-value. Recomputed live on every
call (no persisted model), matching `compute_scores`'s own
always-recompute convention — same reasoning as 3u.23's backtest.
`MIN_OBSERVATIONS = 60` below which a four-parameter regression is closer
to noise than signal — reported as `not_applicable_reason:
"insufficient_history"`, never fit anyway.

Real edge case found while writing the test for a synthetic all-zero
SMB/HML/Mom fixture: a design matrix with constant zero factor columns is
rank-deficient (`statsmodels` raises `SingularMatrixWarning`) — fixed by
giving the test fixture real (if uncorrelated) variation in those columns,
matching what real factor data always has; not a production code change,
since real Kenneth French data is never actually constant.

**New dependencies**: `scikit-learn` was already added for 3u.23;
`statsmodels` added here specifically for its inferential statistics
(t-stats, p-values, R²) that `sklearn.LinearRegression` doesn't provide —
standard practice for factor-model reporting is to show whether a loading
is significantly different from zero, not just its point estimate.

Frontend: new `FactorExposures.tsx`, self-contained (own fetch, no props
from the page — same pattern as `AllocationTargets`/`PortfolioBreakdown`),
added to `Portfolio.tsx` after `AllocationTargets`. An "Importer les
données de facteurs" button triggers the one-off fetch; the table shows
region, alpha, the four betas, R², and observation count per held
position, with an explicit muted note (not blank cells) for
`not_applicable_reason` rows.

Tests: `test_kenneth_french_provider.py` (new, 5 tests) — the shared CSV
shape parsed correctly, CRLF/whitespace handled, the `-99.99` sentinel
dropped. `test_factors_api.py` (new, 11 tests) — region mapping including
the "no country at all" case, a synthetic series with a known true beta
(regression must recover it within tolerance), the "never mixes regions"
guarantee (a France instrument with only US factor data cached must
report `insufficient_history`, never silently regress against the wrong
region), and both API endpoints. Full suite: 671 backend tests pass.
`tsc -b`/`oxlint` clean.

**Live-verified against the real portfolio**: `POST /api/factors/import`
pulled 35,500 real factor rows (both regions, full published history).
`GET /api/factors` resolved all 37 real held positions (23 US, 14
Europe) — zero `not_applicable`. Individual-stock R² values (~0.02–0.33)
and betas (e.g. `APLD.US`: β-mkt 2.10, β-smb 1.90, β-hml −0.67, β-mom
0.88; `ASML.NL`: β-mkt 1.01, r²=0.28) look statistically sane for
single-name regressions — low-to-moderate R² is expected and normal here,
since idiosyncratic risk dominates a single stock far more than it does a
diversified portfolio.

**Addendum, same day — a real N+1 found live, not in tests.** The
synthetic-fixture tests above use one instrument at a time, so they never
exercised the actual 37-position batch path. Browser live-verification did,
and `GET /api/factors` hung — first for 30+ seconds, then for over 15
minutes of runaway CPU on the underlying worker process before it was
force-killed. Root cause: `compute_factor_loadings` reloaded its entire
region's `FactorReturn` table from the database from scratch on every call
— fine for one instrument, but `compute_held_position_loadings` calls it
once per held position, so the real portfolio (23 US, 14 Europe) was
re-hydrating ~17,500 SQLAlchemy `FactorReturn` objects from the database
23 times over for US alone (roughly 400,000 ORM object instantiations
total) before a single regression could run.

Fixed by loading each region's factor series exactly once
(`_load_region_factors`) and threading it through every instrument that
region covers, rather than each instrument independently reloading it.
`compute_factor_loadings` keeps its original one-instrument signature and
behavior (an optional `region_factors` parameter, defaulting to loading
fresh if not given — the unit tests, which never exercised the batch path,
needed no changes), while `compute_held_position_loadings` now pre-loads
both regions once. Verified against the real 37-position portfolio:
`GET /api/factors` dropped from hanging indefinitely to 1.5 seconds,
producing byte-for-byte identical loadings to what the hung run had
already partially computed before it was killed (confirms the fix changed
performance, not correctness).

This also surfaced a separate operational fact worth recording: `uvicorn
--reload --reload-dir app` still occasionally picked up changes to files
outside `app/` (observed reacting to `tests/*.py` edits) during this
session, contrary to the fix applied in 3u.22's mid-run incident note.
Not chased further this session — each such reload was fast and harmless
(unlike 3u.22's `.venv/`-triggered storm) since no long-running request
was in flight at the time, but it means `--reload-dir` alone isn't a
complete guarantee against interrupting a genuinely long operation
(the 5-year backfill, a Finviz scan) if a stray edit lands mid-request.
Worth revisiting if it recurs during a specifically long-running call.

Full suite: 671 backend tests pass (unchanged — the fix is
performance-only, no behavioral test needed new coverage beyond what
already existed).

## Decision 3u.25 — Attention card: "à regarder aujourd'hui" (2026-09-05)

Prompted by a beginner-user UX review: the app has plenty of indicators
(price status, allocation gaps, unresolved symbols) but each lives on its
own table, so a new user has no single place answering "what should I
check first?" before diving into 37 rows of positions. Highest-leverage,
lowest-cost item from that review's priority list — chosen deliberately
over the larger "split the Portfolio page in two views" restructuring,
which stays a candidate for later.

**No new computation.** `GET /api/portfolio/attention`
(`routers/portfolio.py::get_attention`) re-reads three indicators the app
already computes elsewhere and turns them into a short, ranked list:
- price status (`_price_status`, the same function driving `PriceStatusBadge`)
  — counts held positions that are `stale` or `error`;
- unresolved instruments — the exact same query `_build_portfolio_out` used
  inline for its own unresolved-symbols panel, now factored into
  `_unresolved_instruments(db)` so both call sites share one definition of
  "needs fixing" instead of drifting apart over time;
- allocation targets (`_current_allocation_values` + `_allocation_row`,
  identical to `GET /allocation`'s own computation) — one item per
  `under`/`over` category, with `category` and `gap_pct` attached so the
  frontend's message can be specific ("Your ETF target is under-weighted by
  10.3 points") rather than a generic count.

Deliberately excluded: `not_priceable` instruments (CFDs and anything else
permanently outside pricing by design — flagging them would just be noise,
not a fixable problem) and `no_target` allocation rows (nothing configured
means nothing to flag). Two severities only — `missing` (data absent or
unreliable: unresolved symbols, price errors) and `warning` (a configured
gap or a stale figure, worth a look but not broken) — sorted `missing`
first. No `info` tier for v1: everything surfaced here is something the
user asked for or something actionable, not ambient trivia.

Purely descriptive, same posture as every other indicator in this app:
`AttentionItemOut` names a fact and where it applies, never phrases it as
"you should sell X" or "buy more Y" — consistent with 3u.19's "fact, not a
verb" lesson.

**Frontend**: `AttentionCard.tsx`, self-contained (own `useEffect`/fetch,
`AllocationTargets.tsx`'s pattern), placed first on the Portfolio page —
directly under the KPI stat grid, above `ValueHistoryChart`/
`PortfolioBreakdown`/`AllocationTargets`/`FactorExposures` — so it is the
first thing a user sees after the headline numbers. Renders as a plain
list, one line per item, a small colored dot (amber for `warning`, red for
`missing`) instead of an icon — deliberately not reusing `.notice` (which
is one banner per severity; this needs mixed severities in one list). An
empty list renders a plain reassuring sentence ("Nothing to report right
now") rather than nothing at all, so the card's absence never reads as "the
page is still loading."

**Bug found writing the tests**: the test helper's `verified_at=None`
override was silently discarded by a `param if param is not None else
default` pattern — indistinguishable from "not passed" once the caller's
explicit value *is* `None`. Fixed with a private sentinel (`_UNSET`)
instead of `None` as the "not overridden" marker in
`test_attention_api.py::held_instrument`. Test-only; no production code
was affected, since production code never needed that all-defaults-to-now
convenience.

**Bug found in live-verify**: the first version interpolated `gap_pct`
straight into the i18n template (`40.04`) instead of through `formatNumber`
— correct in English, but wrong in French, where the same figure already
shows as "40,04 pts" two cards below in `AllocationTargets`. A user
switching between the two would see the same number spelled two different
ways on the same page. Fixed by threading `formatNumber` through
`itemText`, matching `AllocationTargets.tsx`'s own `formatNumber(row.gap_pct, 1)`
call. Caught only by actually switching the page to French and reading the
rendered text — `tsc -b`/`oxlint` had nothing to say about it, since the
bug was in wording, not types.

Verified: 13 new backend tests (`test_attention_api.py`) plus the full
684-test suite green; `tsc -b`/`oxlint` clean; live-checked in both English
and French against the real portfolio (real result: Stocks over-weighted
by 40.04/40,04 points, correctly formatted per locale after the fix).

## Decision 3u.26 — Getting-started checklist (2026-09-05)

Second item from the same beginner-user UX review that produced 3u.25's
attention card: a brand-new user has no guidance on what to do right after
opening the app for the first time, or right after their first import.
Priority #2 on that review's list, chosen next over the larger "split the
Portfolio page in two views" restructuring for the same reason 3u.25 was —
smaller, self-contained, and doesn't require deciding the bigger page
layout question first.

**Six steps, each a plain existence check.** `GET /api/portfolio/onboarding`
(`OnboardingStatusOut`) reports `imported`, `prices_refreshed`,
`unresolved_resolved`, `fundamentals_fetched`, `allocation_target_set`,
`watchlist_started` — each a one-line query against a table the app
already maintains (an `ImportBatch` row exists, `AppMetadata.last_price_
refresh_time` is set, `_unresolved_instruments` — the same helper 3u.25
factored out — returns nothing, a `Fundamental`/`AllocationTarget`/
`WatchlistItem` row exists). No new tracking table, no "step completed at"
timestamp: today's answer is always "is this true right now," which also
means a step can flip back to false later (a fresh import introduces a new
unresolved symbol) without any migration or backfill concern.

**Import specifically means the XTB statement import, not a manual
position.** `imported` checks for an `ImportBatch` row, not "any position
exists" — a user who only ever adds hand-entered positions has genuinely
skipped the guided import step this checklist is pointing at, and showing
it as done would be misleading about what "Import" on this page actually
offers (auto-reconstructed buy/sell history, which a manual entry doesn't
give you).

**Dismissal is local-only, matching this app's single-user local design.**
`OnboardingChecklist.tsx` stores a plain `localStorage` flag
(`stock-analyst.onboardingDismissed`, same convention as `i18n`'s locale
key and `useHiddenColumns`) — once dismissed, the card never reappears,
even across steps regressing later. Absent a dismissal, the card
auto-hides once all six steps are true (recomputed fresh on every load,
not baked into a single persisted boolean) and reappears on its own if a
step later regresses — a newly unresolved symbol after a second import,
for instance — without the user needing to un-dismiss anything, since
regressing was never a dismissal in the first place.

Rendered first on the Portfolio page, above 3u.25's `AttentionCard` and
outside its `market_value !== null` gate: a brand-new user with zero
positions still needs to see "Import a statement" as their first
un-checked step, which an allocation-gated placement would hide from
exactly the person who needs it most.

Verified: 8 new backend tests (`test_onboarding_api.py`, one per step
flipping independently plus the empty-database baseline) plus the full
692-test suite green; `tsc -b`/`oxlint` clean; live-checked against the
real portfolio (all six steps already done, so the card correctly renders
nothing — confirmed by temporarily clearing `localStorage` and checking
the auto-hide-when-complete path, not just the dismiss button).

## Decision 3u.27 — Score made more approachable, with an explicit wording exception (2026-09-05)

Third item from the same beginner-user UX review (3u.25, 3u.26): a
composite score of 77 means nothing to a first-time user, and nothing on
the page hints that clicking the badge reveals a full breakdown — the
review's own words, "je ne comprends pas immédiatement ce que signifie un
score de 77."

**Two independent fixes, asked and confirmed separately before building.**

1. *Discoverability* — `ScoreBadge.tsx` gets a small chevron (▾ collapsed,
   ▴ expanded) after the number, and the tooltip gains a closing line
   ("Cliquez pour voir les critères, les données utilisées et les éléments
   écartés."). Purely additive, no design question here: the badge was
   always clickable, nothing before this said so.

2. *Plain-language summary* — this one needed a real decision, since this
   app's whole design premise (DEVLOG "Decision 0.3") is fact-not-verdict,
   and the review's proposed wording ("indicateurs globalement
   favorables") is a mild interpretation, not a bare fact. Asked the user
   directly: purely factual counts ("3 indicateurs favorables, 1 à
   surveiller, 2 non calculés") vs. the review's interpretive sentence.
   **User chose the interpretive wording explicitly**, aware of the
   trade-off. Built as asked: `ScoreDetailRow.tsx` now opens with "Score
   {N}/100 : {band adjective} selon les données disponibles" — the band
   adjective from `scoreBand(composite)`, the same 66/33 thresholds
   already used everywhere in this app (`favorable` / `mitigé` /
   `défavorable`). Below it, "Points forts" / "Points à contrôler" lists
   stay purely factual: a metric's own translated name, included only when
   *that metric's own score* (not the composite) crosses the same 66/33
   threshold — the second AskUserQuestion round confirmed this rule over
   an always-show-top/bottom-N alternative, since a fixed threshold can
   legitimately produce an empty list (rendered as "Aucun pour l'instant"),
   which an always-N-items rule would have forced into false signal.

**Scope of the exception, recorded in memory so a future session doesn't
silently "fix" it back.** This is a second, narrow carve-out from
fact-not-verdict — distinct from Discovery's literal buy/hold/sell verdict
(3u.21): no action is suggested, only an adjective describing the
indicators. It applies to exactly one sentence, reused unchanged wherever
`ScoreDetailRow` appears (positions, watchlist, screener) — nowhere else.
Updated `stock-analyst-descriptive-not-verdict-labels` (persistent memory)
with this second override and its date, and added a new project memory,
`stock-analyst-ux-review-2026-09`, tracking which of the review's 5
priority items are done (this is #3) and which remain (#4: split Portfolio
into "my portfolio" vs "manage my data" views; #5: a per-position detail
page).

Verified: no backend changes, so the existing 692-test backend suite is
unaffected (confirmed still green); `tsc -b`/`oxlint` clean; live-checked
in French against a real scored position (ASML, score 77) — chevron
visible, tooltip shows the new closing line, and the expanded detail opens
with the summary sentence and both lists populated correctly from real
metric scores.

## Decision 3u.28 — Dividends by year and account (2026-09-05)

Fourth item from the same beginner-user UX review (3u.25–3u.27), and the
one the user picked by naming a concrete recurring pain point directly:
"le moment où tu dois encore aller chercher l'info ailleurs" (the moment
you still have to go look the information up elsewhere) → dividends and
French tax. `GET /api/transactions` already summed dividends/withholding
globally, but not split by account (PEA and a brokerage account have
completely different French tax treatment) or by calendar year (what a
declaration needs).

**Scope, confirmed explicitly before building — a real product design
back-and-forth this time, not a rubber-stamped default.** Offered a
purely-factual counting alternative for the score-summary-style wording
question this feature also raised; the user chose the review's proposed
richer output. A whole build order was proposed (contract → endpoints →
reconciliation tests → UI → filters → CSV → disclaimer → live-verify) and
followed close to as specified.

**Two real gaps found by reading the code before writing any, not assumed
from the spec.** The proposal assumed grouping dividends "par compte" was
just a query away. It wasn't:

1. `Transaction` had no `account` column at all — only `Position` and
   `Lot` did. The account *was* parsed from every XTB row (`item.get
   ("account")`), but silently dropped before reaching the database, for
   both the closed-trade and cash-operation ingest paths.
2. `Transaction.currency` was never populated for cash operations
   (`DIVIDEND`/`TAX`/`FEE`) either — confirmed on real rows (ASML, Marvell,
   Oracle dividends all had `currency=None`).

Fix for (2) needed no schema change: the instrument is already linked via
`instrument_id`, and its `currency` is already known — read via join
instead of stored redundantly.

Fix for (1) meant reopening a previous decision. `routers/transactions.py`
already had `_account_from_raw`, whose own docstring explained why: "adding
a column would mean an ALTER TABLE on a table already holding real rows —
exactly what this project avoids without a migration tool in place"
(Decision 3d.1). That constraint is stale — Alembic has existed since
Decision 3u.7 — so the fix was to actually add the column (routine
`add_column` + index migration), thread `account=item.get("account")`
through both ingest call sites that had been dropping it, and replace
every read site (`_out`, the list filter, manual create/update) with the
real column instead of the raw-recovery helper. The helper itself survives,
renamed `_recover_account_from_raw`, now used only by a new one-off
endpoint: `POST /api/transactions/backfill-accounts`. Run against the real
database: 1395/1395 existing rows recovered their account from `raw` —
100%, since every cash-operation row already carried it in the source
file, just never promoted.

**Reconciliation, not aggregation, turned out to be the actual hard part.**
A dividend and its withholding tax are two independent `Transaction` rows
(`DIVIDEND`/`TAX`), linked by nothing formal. Checked against real data
before writing the matching rule (the review's own proposed hierarchy —
account, instrument, currency, date, ±3 days, else unmatched — was sound,
but "same instant" needed verifying): paired rows share the exact same
`executed_at` down to the microsecond in the overwhelming majority of real
cases, but not always — one real VICI pair was 1ms apart. So matching is
nearest-timestamp-within-3-days per (account, instrument) group, greedily
claimed in chronological dividend order — verified this handles a real
same-day-multiple-pairs case (two separate VICI dividend/tax pairs a few
seconds apart on 2025-07-10) correctly rather than cross-pairing them.

**Absence of a withholding is not an anomaly — this took a naming
decision, not just a matching rule.** Most dividends legitimately carry no
tax row (0% treaty, PEA wrapper): reported `no_withholding`, never flagged.
Only a `TAX` row that can't be attributed to any dividend is a genuine
anomaly (`unmatched_tax`) — the review's own language, "retenue non
attribuée."

**A second, more consequential data-quality bug found live, after the
reconciliation logic already looked "done."** The first real run showed 25
"unattributed withholding" rows and a nonsensical phantom year (2023, one
row, zero gross, a trivial withholding, no dividend in sight). Checking a
sample's `raw` directly: one label was "Tax IFTT" — French
financial-transaction tax on a *trade* — and another was "Stamp duty" — UK
stamp duty, also on a trade. Neither has anything to do with a dividend.
Root cause: `xtb_import.py`'s
`classify_cash_type` buckets both into `TxType.TAX` alongside genuine
"Withholding tax" rows, since all three match its generic "tax" keyword
family. Fixed with `_is_dividend_withholding`, which re-reads each row's
own `raw["Type"]` and excludes only the two trade-tax labels — defaulting
to *include* when `raw` is missing entirely (a manually-entered `TAX` row
has no label to check, and no manual-entry path exists for a trade tax
specifically, only for a withholding correction). After the fix: orphan
count dropped from 25 to 1 (a genuine "US Dividends Reclassification"
adjustment, correctly still shown), and PEA's apparent withholding dropped
sharply per year — the FTT on French trades had been masquerading as
dividend withholding.

**The same bug already existed, silently, in a page shipped months ago.**
`routers/transactions.py::_compute_summary` (backing the Transactions
page's own "Retenue à la source" figure) summed the same unfiltered
`TxType.TAX` bucket — it would have kept disagreeing with the new
Dividends page's more accurate number forever if left alone. Fixed by
reusing `_is_dividend_withholding` there too: the real total shrank
accordingly, and the two pages now agree exactly.

**What the view deliberately does not do**, per the user's own explicit
list: no PFU/barème calculation, no French-vs-foreign tax-credit logic, no
inferred account tax regime (a target `AllocationTarget`-style "this
account is a PEA" setting was explicitly rejected — the account name
itself is shown as-is, verbatim from the broker export), no declaration-
ready totals — a plain-language `.notice.info` disclaimer says so on the
page itself.

**Built**: `Transaction.account` column + migration; ingest fix (both call
sites); `POST /transactions/backfill-accounts`; `app/dividends/service.py`
(`dividend_detail`, `dividend_summary`, `_is_dividend_withholding`,
`_reconcile_instrument_account_group`); `GET /api/dividends/summary`,
`/detail`, `/summary.csv`, `/detail.csv`; `Dividends.tsx` (year/account
filters, CSV export links, disclaimer), reachable via a link from
Transactions, not the main nav — matching the confirmed scope (a sub-view,
not a new top-level section).

Verified: 24 new backend tests (`test_dividends.py` + additions to
`test_transactions_api.py`) plus the full 715-test suite green; `tsc -b`/
`oxlint` clean; live-checked in French against the real portfolio — hero
totals, the year×account table, and the detail table (including the
ARCC "unattributed withholding" row and a genuine dividend-reversal row,
CP.US, negative gross paired correctly with a positive withholding) all
matched hand-computed figures; year/account filters and both CSV export
links confirmed working.

**Addendum, same day — an unrelated uvicorn hang, not a code bug.**
Mid-verification, the whole backend briefly stopped responding to every
endpoint, not just the new ones — diagnosed as the `--reload` process
getting confused by the flurry of file edits (new `dividends/` module,
migration, router registration) rather than a bug in the new code: CPU
usage was low and flat, not the runaway-loop signature from 3u.24's N+1
incident. Killed and restarted cleanly; both old and new endpoints
answered correctly afterward with identical figures. Consistent with the
`--reload-dir app` quirk already noted in 3u.24's addendum — still not
worth chasing further, but now recurred a third time.

## Decision 3u.29 — Manual backup and restore for the local database (2026-09-05)

Second item off the roadmap established the same day as 3u.28 (a separate
planning conversation from the UX-review thread), and the one the user
picked next explicitly. Rationale, stated plainly: this app has no
server-side redundancy at all — the one `.db` file is the entire portfolio
history, and by this point holds transactions, manual corrections, account
data, allocation targets, and dividend reconciliation state, with no way
to recover it beyond whatever the OS itself might have backed up.

**Two design questions asked before writing any code, since restore is
inherently destructive and irreversible.** (1) Where do backups live: a
fixed local folder next to `data/`, or a per-backup file-picker location?
Chose the fixed folder — this app has no native file-picker to offer
anyway, and a fixed, predictable location is simpler to reason about for
a personal tool. (2) How does restore get triggered, given it overwrites
the live database: a UI button behind a stronger confirmation, or backup-
only in the UI with restore left as a documented manual step? Chose the
UI button — but gated on typing the exact filename before the button even
enables, not a bare "are you sure?" click, since that's the one
confirmation mechanism that can't be fat-fingered through by habit.

**What a backup actually is**: `shutil.copy2` of the live SQLite file into
a new `backups/` directory (gitignored — same sensitivity as `data/`),
named `stock_analyst_<UTC timestamp>.db`. Nothing else is ever read or
written — `.env`/API keys are safe by construction, not by an exclusion
rule that could rot. The 10 most recent backups are kept; older ones are
pruned automatically on each new backup (not asked for explicitly, but a
sensible default stated plainly rather than silently assumed).

**A real bug found by a flaky-looking test failure, not by inspection.**
The first timestamp format (`%Y%m%dT%H%M%SZ`, second precision) meant two
backups requested within the same second — plausible for a double-click,
or a script calling the endpoint in a loop — would get the *same*
filename, and the second `shutil.copy2` would silently overwrite the
first rather than erroring or disambiguating. Caught because a retention
test (`create 5 backups, expect 3 after pruning`) returned 1 instead:
several of the "5 backups" had collapsed onto the same file the whole
time. Fixed with microsecond precision (`%f`) in the timestamp — a
one-line fix, but one that would have meant a user's *previous* backup
silently vanishing the moment they clicked twice.

**Restore refuses a schema mismatch rather than trying to reconcile one.**
`alembic_version` is read directly via `sqlite3` (not through the app's
own SQLAlchemy engine — must work against an arbitrary backup file that
was never that engine's target) and compared byte-for-byte between the
backup and the live database. Anything but an exact match is rejected
(`409`), never "upgrade the backup's schema first" — that would mean
running migrations against a file the user hasn't committed to actually
using, on the way to maybe discarding it. `engine.dispose()` runs before
the file copy: a stale pooled SQLite connection would otherwise keep
holding a lock on content that's about to be replaced. The restore
filename is resolved strictly inside `BACKUP_DIR` before anything else —
rejects `../` traversal, an absolute path, or anything that would resolve
outside the directory, since this string arrives from an API request.

**Built**: `BACKUP_DIR` config constant; `app/backup/service.py`
(`create_backup`, `list_backups`, `restore_backup`, `BackupNotFoundError`,
`SchemaMismatchError`); `GET/POST /api/backup`, `POST /api/backup/
{filename}/restore`; `BackupPanel.tsx` in Settings (create button, backup
list with size/date, per-row restore gated on typing the exact filename).

Verified: 14 new backend tests (`test_backup.py`, entirely against temp
files via monkeypatched `BACKUP_DIR`/`get_settings`/`engine` — never
touching this developer's real database or the test suite's own) plus the
full 729-test suite green; `tsc -b`/`oxlint` clean. Live-verified create
and list against the real database and confirmed the resulting file is a
byte-valid SQLite copy — restore was deliberately **not** exercised
against the real production database during this verification pass (that
would mean overwriting real portfolio data to test a destructive path);
its correctness rests on the backend test suite's synthetic-database
coverage instead, consistent with this session's safety posture around
irreversible operations.

## Decision 3u.30 — Stock splits and reverse splits (2026-09-06)

Third item off the same-day roadmap (Decision 3u.28's dividends, Decision
3u.29's backup), picked next by explicit user choice over the per-position
detail panel: a
detail panel would surface numbers a split could make wrong (quantity,
cost basis, chart, return), so getting splits right came first.

**Audited before writing any code**, per the user's own four questions.
(1) XTB never reports a split in any raw transaction row — every `Type`
value in the real portfolio (`BUY, SELL, Close trade, Correction, Deposit,
Dividend, ...`, `ingest/xtb_import.py::_CASH_TYPE_RULES`) has nothing
split-related; the closest thing, a `"Fractional shares"` bonus-issue
cash-in-lieu row, falls into `TxType.OTHER`. (2) No price provider can be
trusted to deliver split-adjusted history uniformly — checked all 13, none
requests an explicit adjusted-close field, all store plain `close`. Real
evidence: the same provider (twelvedata) served already-adjusted history
for two real splits on currently-held instruments (NVDA 10:1, June 2024;
GOOGL 20:1, July 2022 — no discontinuity either way) but **raw, unadjusted
history for a third** — APLD.US's real 1-for-6 reverse split, confirmed
externally (SEC/Investing.com, effective 2022-04-12): stored `price_bars`
show a genuine, unadjusted jump (close 1.75 → 4.85). Same provider,
opposite behavior depending on the instrument — proves the app cannot
assume either way and must detect this itself. (A second candidate anomaly,
DOYU.US, turned out to be two real special cash dividends, not a split —
ruled out before it wasted any design effort.) (3) No live bug today:
`Position` (the "what do I hold now" table) is a broker-reported snapshot
replaced wholesale on every import, so live quantity/avg-price self-
corrects the next time XTB is re-imported after a real split — checked, no
currently open lot on APLD/NVDA/GOOGL predates its split. The real
exposure is entirely in historical replays and price-history-derived
analytics, which use raw `Lot`/`PriceBar` rows a re-import never touches:
the value-history chart, the dividend-yield lot-replay, Carhart factor
exposure, the price-prediction features, and the price chart/sparklines
themselves.

**Design settled through discussion after the audit, not assumed.**
Proposed the standard "lecture seule" choice (raw prices immutable,
correct at read time); user's response added the load-bearing refinement:
don't apply the ratio ad hoc wherever needed, centralize a derived
adjusted-price view, and — critically — don't trust any provider's
"adjusted" claim without per-instrument verification, since the audit had
just proven that assumption false for real data. This directly shaped the
final design: `detect_price_history_status` empirically compares the
actual close-to-close ratio around a split's `effective_date` to the
split's own ratio, classifying `RAW` (needs local correction),
`ALREADY_ADJUSTED` (provider already fixed it — never correct again, this
is what prevents double-adjusting series like NVDA/GOOGL), or
`NOT_APPLICABLE` (no bars span the date yet).

**Built**, mirroring the `dividends`/`backup` self-contained-package
pattern: `CorporateAction` model + Alembic migration (`corporate_actions`
table: instrument, type, effective_date, ratio_numerator/denominator,
source, price_history_status, detected_price_ratio); `app/corporate_
actions/service.py` — `quantity_factor_from`/`price_factor_from` (pure
functions over a preloaded action list, restating a lot's quantity or a
raw close to today's post-split basis), `load_actions_by_instrument` (one
query for a whole batch replay, not one per lookup — matches
`history_service.py`'s own batch-first convention), `detect_price_history_
status`, `create_corporate_action`, `detect_from_yahoo`; `providers/
yahoo.py::fetch_splits` (adds `events=split` to the exact same chart call
`fetch_daily` already makes — free, no extra quota); `GET/POST/DELETE
/api/corporate-actions`, `POST /api/corporate-actions/detect`.

**Threaded into every consumer that replays `Lot`/`PriceBar` history** —
the actual hard part, since each one needed the *quantity* factor, the
*price* factor, or both, without breaking its own existing batch-query
discipline: `prices/history_service.py` (`compute_value_history`'s day
loop and its benchmark shadow-quantity precompute — tracked each cached
close's own bar_date separately from the display day it's forward-filled
onto, so a stale weekend price spanning a split keeps its own pre-split
factor rather than the display day's post-split one), `scoring/service.py`
(`_shares_held_on`'s dividend-yield replay, `_load_closes`'s technical
metrics), `factors/service.py` (`_daily_returns`), `prediction/
features.py` (`_closes_by_date`, feeding every momentum/SMA/volatility
feature and the forward-return label), and `routers/prices.py`'s main
chart plus all three sparkline endpoints (prices/screener/watchlist) — so
the chart the user actually looks at never shows a fake cliff.
`Position`-based live totals were deliberately left untouched, per the
audit's finding in point (3) above.

**Frontend deliberately minimal**: `CorporateActionsPanel.tsx` in
Settings, mirroring `BackupPanel.tsx`'s shape — list, manual add form
(instrument dropdown built from the union of held/watchlisted/screened
instruments, no new lookup endpoint needed), delete, and a "check for new
splits" button. No chart annotation or per-position surfacing yet — that
belongs to the detail-panel chantier, next on the roadmap.

**Scope, per the user's own list**: split and reverse split only —
mergers, acquisitions, spin-offs, rights issues, stock dividends, ticker
changes, and any tax treatment of a split are explicitly out, to join a
broader "corporate actions" chantier later if ever needed.

Verified: 43 new backend tests (`test_corporate_actions.py` — factor math,
non-mutation, detection status against synthetic APLD/NVDA-shaped series,
double-adjustment prevention, dedup, API; `fetch_splits` parsing in
`test_providers.py`; one regression test per touched consumer proving a
synthetic split no longer distorts it) plus the full 772-test suite green;
`tsc -b`/`oxlint` clean.

**Addendum, same day — a real rate-limit crash, then a real ambiguous
result, both found live against the actual portfolio (~44 tracked
instruments).** First: `detect_from_yahoo`'s original `except (SymbolNotFound,
ProviderUnavailable)` didn't catch `RateLimited`, so Yahoo throttling
partway through a real batch turned the whole `/detect` call into an
uncaught 500 — fixed by catching it too. But the fix's naive form (skip and
`continue` to the next instrument) created a second, subtler problem:
`detect_from_yahoo` returned a bare `list[CorporateAction]`, so a real run
that came back `created: 0` was indistinguishable between "checked all 44,
genuinely found nothing" and "Yahoo blocked us after the 3rd instrument,
the other 41 were never checked" — confirmed live: a direct raw call to
Yahoo's endpoint still returned `429` minutes after the batch run finished,
meaning the block was real and the "0" result could not be trusted at all.
For a mechanism whose entire job is correcting historical data, those two
outcomes must never look identical.

Replaced the return type with `DetectionSummary` — `candidates`, `checked`,
`found`, `created`, `already_known`, `no_events`, `rate_limited`,
`not_checked`, `failed`, `skipped`, and, most importantly, `complete: bool`
(true only when every eligible instrument was checked or explicitly,
displayably excluded — never when a rate limit cut the scan short). Also
changed the loop's own behavior on a rate limit: stop the scan immediately
rather than continuing to hammer an already-blocked provider instrument by
instrument (per the module's own docstring, Yahoo's block persists well
past the triggering request, so continuing produces no real data, only a
slower, still-incomplete result). `POST /api/corporate-actions/detect` and
`CorporateActionsPanel.tsx` both surface this: the panel shows how many
instruments were actually checked, an explicit warning line (amber, not
green) when the scan is incomplete, and never claims "no splits found"
unless `complete` is true.

Verified: 6 new/rewritten test cases against the exact scenarios above
(complete zero-result scan, a rate limit stopping the scan with the
remainder correctly counted as `not_checked`, an isolated non-rate-limit
failure *not* stopping the rest, a symbol-less instrument counted as
`skipped` without ever calling the provider, counting invariants, and the
API response shape) plus the full 778-test suite green; `tsc -b`/`oxlint`
clean. Still pending: one real, controlled `/detect` run once Yahoo's
block clears, to confirm APLD/NVDA/GOOGL classify as expected against
live data — deliberately not retried immediately, to avoid extending the
block further.

## Decision 3u.31 — Per-position detail panel, replacing two independent expand rows (2026-09-06)

Chosen as the next chantier specifically because it doesn't depend on
Yahoo (still rate-limited, see 3u.30's addendum — left untouched here).
Before this, understanding one held position meant reading across the
dense table row, then separately expanding its Score sub-row and its
Insights sub-row, then manually filtering the Transactions and Dividends
pages by hand — no single place answered "what does this app actually
know about ASML".

**Full consolidation on `PositionsTable` only, not additive.**
`ScoreBadge`/`InsightsBadge` there now open one unified "Détails" panel
per position (Résumé, Allocation, Analyse, Revenus, Historique, Qualité
des données as vertical sections, not tabs — nothing hidden behind
secondary navigation) instead of two independent sub-rows. `WatchlistTable`
and `ScreenerTable` are explicitly untouched: both keep their own
`expandedId`/`expandedInsightsId` pair and can show Score and Insights
open at once, exactly as before — confirmed live on Watchlist (ASML/CRWD
row: both sections open simultaneously, `Points forts`/`Value` and the
news list rendering correctly) and by code inspection on `ScreenerTable`
(byte-identical wiring to Watchlist's, unreachable live today since the
real screener candidate list happens to be empty).

**Extract-then-reuse, not duplicate.** `ScoreDetailRow.tsx` and
`InsightsDetailRow.tsx` are shared by all three tables. Each was split
into a pure content component with no `<tr>` of its own —
`ScoreBreakdown({ score })` and `InsightsSection({ instrumentId })` — plus
an unchanged thin `<tr>` wrapper of the same original name, so Watchlist
and Screener needed zero code changes. The new `PositionDetailRow.tsx`
embeds `ScoreBreakdown`/`InsightsSection` directly inside its own
"Analyse" section instead of duplicating their logic.

**Two small backend additions, everything else already existed.**
`GET /api/portfolio/lots?instrument_id=` (new — no endpoint returned
individual `Lot` rows before; returns open and closed lots for one
instrument via a new `LotOut` schema) and an `instrument_id` filter added
to `GET /api/transactions` (mirroring its existing `account` filter).
`GET /api/dividends/detail` and `GET /api/corporate-actions` already
accepted `instrument_id` but the frontend client never used it. Allocation
contribution ("cette position pèse X% de la classe Actions") is computed
client-side from the already-fetched `GET /api/portfolio/allocation`
response — no new endpoint. Data-quality fields (`mapping_status`,
`verified_at`/`verified_provider`, `not_priceable_reason`) already existed
on `Instrument`/`InstrumentOut`, previously only surfaced in
`PriceStatusBadge`'s tooltip — now rendered as text in the panel's own
section.

**No price chart in v1**, by deliberate user decision — a chart raises
raw-vs-adjusted, default-period, and benchmark questions that deserve
their own scoping conversation (and can reuse `GET /api/prices/{id}/
history` plus the 3u.30 adjustment factors when that chantier happens).
The existing 90-day row sparkline is enough for now.

**Lazy-fetch-on-expand**, same `fetchedForRef`-guarded pattern
`InsightsDetailRow` already used to survive React 18 StrictMode's
double-invoke without double-spending a request: on first expand,
`PositionDetailRow` fetches lots, dividend detail, corporate actions, and
instrument-scoped transactions in one `Promise.all`, then caches per
instrument id.

Verified: 8 new backend tests (`test_lots_api.py` — open+closed lots
returned, empty for an instrument with none; `test_transactions_api.py`'s
new `instrument_id` filter test) plus the full 786-test suite green;
`tsc -b`/`oxlint` clean. Live, against the real portfolio: ASML's panel
— all 6 sections populated correctly (résumé figures matching the row,
allocation gap and category-share line, embedded score breakdown and live
news/sentiment list, 7 real dividend rows, 1 open lot plus its linked
buy/dividend/withholding transactions, verified-price-provider line); then
DCAM.FR (an ETF with no dividend history) — "Aucun versement pour ces
filtres" renders instead of an empty table, and the corporate-actions
subsection is omitted entirely rather than shown empty. Confirmed only
one position's panel can be open at a time (opening DCAM.FR's closed
ASML's automatically) and that Watchlist's two independent toggles are
unaffected, as described above.

## Decision 3u.32 — Separating "tracking" from "administration" (2026-09-06)

Next roadmap item after the per-position detail panel, chosen because it's
independent of the paused Yahoo corporate-actions work. Before this,
`Portfolio.tsx` mixed two concerns: reading the portfolio (KPIs, allocation,
positions) and maintaining its underlying data (XTB import, fundamentals
fetch, manual position entry, unresolved-symbol correction) — for a new
user, an import button next to unrealized P&L reads like an investment
action when it's really data maintenance.

**Pure reorganization, deliberately scoped down twice by the user during
planning.** First: two aggregate "data health" views ("éléments non
valorisables", "qualité des données") were explicitly ruled out — they
don't exist today (the underlying fields — `not_priceable_reason`,
`mapping_status`, `verified_at` — are only ever shown per-instrument, in
`PriceStatusBadge`'s tooltip or the per-position detail panel) and building
one would mean inventing new severity/aggregation rules, not moving
existing code. Left as a separately-scoped future chantier ("Santé des
données"). Second: `RefreshPanel` ("Actualiser les cours") was kept on
`Portfolio.tsx` as a deliberate exception, after tracing why moving it
would silently break something. Its live-quote phase returns the
recomputed `Portfolio` only in the direct HTTP response —
`prices/quote_service.py`'s own module docstring: *"a live quote is a
snapshot, not a daily close, and writing it into `PriceBar` would corrupt
the daily-bar semantics... kept in memory only... never persisted."*
Today `Portfolio.tsx` receives that result and replaces its state in
place; moving the trigger to Settings would mean a live refresh there
leaves Portfolio showing stale cached numbers when visited afterward,
since a plain `GET` can't recover data that was never saved anywhere. No
cross-page state handoff was built to work around this — the panel simply
stays where its one-shot result is actually usable, reframed as "refresh
what I'm looking at" rather than a maintenance action.

**What actually moved**, all self-contained components whose `on*`
callbacks existed only so `Portfolio.tsx` could refresh its own state
(now no-ops in their new home, since Settings doesn't hold that state):
`ImportPanel`, `FundamentalsRefreshButton`, and `ManualPositionForm` into
a new "Données du portefeuille" group; `UnresolvedPanel` into "Intégrité
et corrections" alongside the already-there `CorporateActionsPanel` — the
one exception, since `onUpdated` there does need Settings to refetch the
`instruments` list it now owns independently (one extra `GET
/api/portfolio` call on the Settings page, accepted as-is: cache-only,
negligible cost, simpler than sharing state across pages for one field).
`BackupPanel` and the providers/API-keys block were already in Settings,
just visually regrouped into "Sauvegarde" and "Sources de données".

**Hash-anchor navigation**, new to this codebase (no prior precedent —
confirmed by search): `Settings.tsx` reads `useLocation().hash` and
scrolls the matching group into view once its data has loaded (depends on
`loading` in the effect, since the four groups don't exist in the DOM yet
during the initial spinner). Two links use it: `Portfolio.tsx`'s new
"Gérer les données" line (next to the existing "Dernier import"/"Prix mis
à jour" text — no new aggregate figure was added, since a more detailed
version of "what needs attention" already exists in `AttentionCard`
directly below) points to `/settings#donnees-portefeuille`; `AttentionCard`'s
`unresolved_instruments` item becomes a link to `/settings#integrite-corrections`
(the one item type whose fix now actually lives in Settings — `price_stale`/
`price_error` items stay plain text, since their fix, `RefreshPanel`, is
still on the same page).

Verified: backend untouched, full 783-test suite still green (sanity
check only, no new tests needed); `tsc -b`/`oxlint` clean. Live, against
the real portfolio: Portfolio now shows only tracking content plus the
manage-data link and unchanged `RefreshPanel`; the link navigates to and
scrolls to "Données du portefeuille"; a full-page load of
`/settings#sauvegarde` correctly scrolls the fourth group to the top of
the viewport (confirming the loading-gated effect works after a hard
reload, not just client-side navigation); all four groups render their
components with the exact same behavior as before the move; `UnresolvedPanel`
correctly stays hidden on both pages today (no unresolved symbols in the
real portfolio) — its empty-state `return null` and the new `loadUnresolved`
wiring were confirmed by code inspection rather than a live correction,
since none exist to correct right now.

## Decision 3u.33 — Santé des données: a positions-only data-quality console (2026-09-06)

Next roadmap item after the tracking/administration split, proposed by the
user as the natural extension of "Intégrité et corrections": diagnosing a
data problem across the whole portfolio previously meant noticing a single
instrument's status badge in the positions table, or reading
`AttentionCard`'s compact counts on Portfolio — neither listed *which*
instruments were affected or where to fix each one.

**Deliberately narrow v1, locked down through several rounds of
clarification, all converging on one discipline: aggregate only what the
backend already computes and already means something.**

- **Two categories excluded on purpose**: "fondamentaux incomplets" and
  "corporate actions à vérifier" don't exist as backend-computed facts —
  fundamentals completeness has no definition (which pillars are
  required, what counts as an acceptable gap), and corporate-action
  "checked" status is never persisted per instrument, only returned
  transiently by `/detect`'s `DetectionSummary`. Both need their own
  future chantier once that business logic is actually decided — building
  them now would mean inventing new severity/aggregation rules mid-refactor,
  not moving code.
- **The freshness threshold is untouched** — `FRESH_WINDOW_DAYS = 4`
  (`routers/portfolio.py:86`), reused via the existing `_price_status()`
  with zero modifications. No per-market/per-instrument-type variation:
  nothing in the codebase or any known complaint justifies that
  complexity, and introducing it would raise its own unscoped questions
  (market calendars, holidays, 24/7 crypto, suspended/delisted instruments).
- **Held (open) positions only** — no Watchlist, no Screener. The view
  answers "can I trust the numbers valuing what I actually own", not "is
  every ticker the app knows about fully documented".
- **`AttentionCard` stays untouched.** The two views serve different
  purposes — a compact at-a-glance alert on Portfolio vs. a detailed
  diagnosis-and-fix console in Settings — and duplicated *counts* (not
  detail) between them was accepted rather than risk regressing a
  component that already works, or redefining its role mid-chantier.
- **Lives inside the existing "Intégrité et corrections" group**, placed
  directly above `UnresolvedPanel` — no new top-level Settings group for
  four existing, already-understood states.

**New `GET /api/portfolio/data-health` endpoint** (`routers/portfolio.py`)
reuses `_price_status()` and `_unresolved_instruments()` completely
unmodified, over the same position query `get_attention()` already uses.
Every position is bucketed into exactly one of `unresolved_instruments` /
`price_stale` / `price_error` / `not_priceable`, checked in that order —
unresolved-mapping is deliberately checked via `_unresolved_instruments()`
first, not `_price_status()`'s own broader `"unmapped"` value, so the
count here always matches exactly what `UnresolvedPanel` sitting right
below it can actually correct (an instrument that's unmapped but excluded
from correction — e.g. a CFD, or one that already carries an ISIN — isn't
flagged as "needs fixing" here either). A position landing on "fresh" or
the rare residual "unmapped" not caught by that check contributes only to
`total_positions`, not to any category.

**Frontend**: `DataHealthPanel.tsx`, self-contained fetch-on-mount like
`AttentionCard`, listing each non-empty category's affected instruments
(symbol, name, and a plain-language `detail` — last-checked date for
stale, the reason text for not-priceable) — no accordion, matching
`UnresolvedPanel`'s own convention of always showing its full list. No
per-item links in v1: each fix already lives one page/click away
(`RefreshPanel` for stale/error, the per-position detail panel's own
"Qualité des données" section for not-priceable reasons, `UnresolvedPanel`
immediately below for unresolved symbols).

Verified: 10 new backend tests (`test_data_health_api.py` — each category,
bucket exclusivity, the positions-only scope via a Watchlist-only
unresolved instrument correctly excluded, empty/all-fresh cases,
`total_positions` accuracy) plus the full 793-test suite green; `tsc -b`/
`oxlint` clean. Live, against the real portfolio (currently all-fresh,
all-resolved): the panel renders its all-clear state correctly above
`UnresolvedPanel` in Settings; `AttentionCard` on Portfolio confirmed
pixel-identical to before — the one component this chantier was explicit
about never touching.

## Decision 3u.34 — Corporate actions: FMP replaces Yahoo as the detection source (2026-09-06)

Closes task from Decision 3u.30/3u.31's addendum, pending since Yahoo's
undocumented chart endpoint proved impossible to validate against: a raw
single-symbol check could return `200` while the real `/detect` scan still
hit `429` on the very first of 47 instruments, repeatedly, over several
days of the user's own single-check-then-retry protocol. Rather than keep
retrying an unofficial, inconsistently-behaving provider, the source was
swapped outright.

**Audited live before writing any code** (3 FMP calls, 1 EODHD call, zero
DB writes): FMP's `/stable/splits` answered `200` with correct data for
NVDA (10:1, 2024) and GOOGL (20:1, 2022), but `402 PlanLimited` for APLD —
confirming the free plan gates *individual smaller-cap symbols*, not just
non-US markets (already known from `fmp.py`'s existing `can_serve`
docstring). EODHD's `/api/splits` correctly answered APLD's reverse split
(1:6, 2022-04-13) via a different endpoint, but this pass deliberately
does not wire that up — see below.

**Decided scope, after two rounds of clarification, kept deliberately
minimal**: FMP becomes the *sole* bulk-detection source, replacing Yahoo
outright — no multi-source orchestration, no automatic fallback to EODHD
or Yahoo when FMP can't cover a symbol (that instrument is simply
`failed` for the run, exactly like any other non-retryable provider
error; manual entry remains the answer). No cross-source conflict
detection either, since there's only one automatic source to conflict
with. Both were explicitly deferred as separately-scoped future chantiers,
not built pre-emptively on a hypothetical need.

**Implementation, `DetectionSummary`'s contract entirely unchanged**: new
`FmpProvider.fetch_splits()` (`providers/fmp.py`), same error-mapping
convention `fetch_daily` already uses in that file (`429`→`RateLimited`,
`402`→`PlanLimited`, other `4xx`/`5xx`→`ProviderUnavailable`) — unlike
`fetch_daily`'s parsing, an *empty* splits list is a valid "never split"
answer, not a sign of an unknown symbol. New `get_fmp_provider()` registry
accessor mirrors `get_yahoo_provider()` exactly (shared instance, shared
`Throttle`/quota with regular price refreshes). `detect_from_yahoo` →
renamed `detect_splits`; the only two behavioral changes are the provider
swap and `PlanLimited` joining the existing non-blocking `except
(SymbolNotFound, ProviderUnavailable): failed += 1; continue` — every
other branch (stop-on-`RateLimited`, dedup, skip-when-no-symbol,
`not_checked`/`complete` computation) is untouched, since the loop's
structure never needed to change for a single-source swap.

**Known, disclosed gap**: neither live-verified case is a reverse split,
so FMP's numerator/denominator convention for one (expected
`numerator < denominator`, matching `_classify_ratio` and EODHD's
confirmed `1/6` for APLD) is asserted in tests against the
documented/assumed shape, not a live FMP response — APLD, the one
reverse-split case in hand, is exactly the symbol FMP's free plan won't
serve.

**Live-verified against the real ~47-instrument portfolio, and that live
run exposed a real bug in `complete`'s own definition — caught before
shipping, not after.** First pass returned
`{"candidates": 47, "checked": 9, "found": 35, "created": 35,
"already_known": 0, "no_events": 2, "rate_limited": 0, "not_checked": 0,
"failed": 38, "skipped": 0, "complete": true}`. FMP's *real* coverage of
this portfolio is far narrower than the 3-symbol audit suggested — only 9
of 47 tracked instruments got a definitive answer (2 confirmed no-events,
7 with real split history), the other 38 (mostly European holdings FMP's
free tier has never covered, plus other US small-caps hitting the same
per-symbol gate APLD did) landed in `failed`. Under the original rule
(`complete = not_checked == 0`), that read as `complete: true` — correct
by the letter of the original design (Yahoo's only real failure mode was
an all-or-nothing rate limit, so "nothing left unattempted" used to mean
"the whole portfolio was checked"), but wrong by its spirit once a
provider's failure mode became *structural per-symbol coverage gaps*
instead: `complete: true` here would read as "portfolio fully checked",
when 38 of 47 instruments never got a real answer. Fixed immediately —
`complete = not_checked == 0 and failed == 0` — rather than shipped and
left for a future bug report. `CorporateActionsPanel.tsx` gained one new
line (`detectionFailedCaveat`) shown whenever `failed > 0`: "not checked
doesn't mean no split" — the exact false conclusion `complete: true`
could otherwise have implied. Also fixed in passing: `detectionIncomplete`
and `detectionSkippedSummary` both still named Yahoo specifically, factually
wrong now that FMP is the detector.

Verified: 10 new tests for the FMP provider/service swap
(`test_providers.py::TestFmpFetchSplits` — real NVDA/GOOGL-shaped payloads,
the assumed reverse-split shape, empty-list-is-not-an-error, chronological
sort, date-range filtering, `429`/`402`/unparseable-body/no-key error
mapping; `test_corporate_actions.py`'s new
`test_a_plan_limited_symbol_does_not_stop_the_rest`) plus one more for the
`complete` fix itself (`test_any_failed_instrument_means_the_scan_is_not_complete`
— the exact regression shape found live, `failed > 0` with `not_checked ==
0`) and three existing tests updated to the corrected semantics
(`test_case_5`, `test_case_7`, the `PlanLimited` case — each has `failed
>= 1` and now correctly expects `complete is False`). Full 804-test suite
green; `tsc -b`/`oxlint` clean. Re-running `/detect` against the real
portfolio after the fix: same counts, now correctly reported as
`complete: false` — a second run still confirmed idempotency
(`created: 0, already_known: 35`, no duplicates). `PriceBar`/`Lot`/
`Transaction` untouched throughout (verified by code review —
`create_corporate_action` only ever writes to `CorporateAction`).

Not built now, left as real future chantiers if FMP's ~19%-of-portfolio
coverage turns out to matter enough in practice: a targeted, single-
instrument EODHD fallback (confirmed working live for APLD specifically)
for the cases FMP's free tier won't answer, and eventually the same for
whichever European holdings matter most.

## Decision 3u.35 — Corporate actions: targeted single-instrument EODHD fallback (2026-09-06)

Follow-up to Decision 3u.34, closing the APLD case that decision left open:
FMP's free plan gates APLD specifically (`402 PlanLimited`, confirmed
live) even though it's a plain US listing, but EODHD's `/api/splits`
correctly answers with the real 1:6 reverse split via a different
endpoint. Rather than build automatic multi-source orchestration —
explicitly rejected as disproportionate for this app (roughly doubles
quota cost per instrument on every bulk scan, and needs a conflict-
resolution UX that doesn't exist) — this adds one narrow, explicit,
user-triggered escape hatch: check *one* chosen instrument against EODHD.

**Locked-down scope, confirmed after two rounds of clarification:**
manual, one instrument at a time, triggered only from
`CorporateActionsPanel`; instrument picked from the same tracked-
instrument dropdown the manual-add form already uses — deliberately not
gated on "must have failed FMP's last scan", since `/detect` doesn't
expose which instruments failed (and building that list was judged
disproportionate too: it would need a persisted-run/per-instrument-status
model, not a `DetectionSummary` field). No automatic fallback, no cascade
over all `failed` instruments, no scan of the whole portfolio via EODHD —
its 20/day quota would evaporate in one click otherwise. Writes a
`CorporateAction` only on a real, not-already-known event; never touches
`PriceBar`/`Lot`/`Transaction`; never re-triggers the FMP scan or Yahoo.

**Implementation**: `EodhidProvider.fetch_splits()` (`providers/eodhd.py`)
— verified live against `/api/splits/APLD.US` (`{"date": "2022-04-13",
"split": "1.000000/6.000000"}`), parsing the `"numerator/denominator"`
convention this app already uses everywhere. Needed the explicit `.US`
suffix EODHD's splits endpoint requires (confirmed live) — built via
`is_us_listing(ref)`, since `provider_symbol` is bare for US listings
(Yahoo's own convention `fmp.py` already had to work around the same
way). Non-US symbols use `provider_symbol` as-is, on the same disclosed
assumption `fmp.py`'s reverse-split direction carried: not independently
verified live. New `get_eodhd_provider()` registry accessor mirrors
`get_fmp_provider()` — shares EODHD's `Throttle`/quota with regular price
refreshes. New `detect_one()` service function reuses `_classify_ratio`
and `create_corporate_action` exactly as `detect_splits` does — no second
creation path — returning a `DetectOneResult` whose `status` is always
one of `created | already_known | no_events | not_supported |
plan_limited | rate_limited | failed`. New `POST
/api/corporate-actions/detect-one`, body-validated via `DetectOneIn`
(`provider: Literal["eodhd"]` — FastAPI/Pydantic reject anything else
with a `422` automatically, no manual branch needed), `404` if the
instrument doesn't exist.

`CorporateActionsPanel.tsx` gained its own section — "Vérifier un
instrument avec une autre source" — reusing the already-fetched
`instruments` list (no new fetch), rendering its result distinctly from
the bulk-scan notice above it so the two flows are never visually
confused. `no_events` gets its own honest copy (never the bulk scan's
"no splits found" text); every failure status shares the same
`detectionFailedCaveat` line already shipped for the bulk scan — a
failure must never read as a confirmed absence of split, here either.

**Two small gaps found and fixed in passing, while touching this file**:
`corporateActions.source.fmp` was missing from all three locales entirely
— every one of the real portfolio's 35 FMP-sourced actions was rendering
the bare i18n key string in the actions table since Decision 3u.34
shipped. The frontend's `CorporateAction.source` type was also still
typed `'yahoo' | 'manual'`, not reflecting the FMP swap. Both fixed here.

Verified: 14 new backend tests (`test_providers.py::TestEodhdFetchSplits`
— real APLD-shaped payload, `.US` suffix construction, empty-list-is-not-
an-error, `429`, unparseable body, date-range filtering;
`test_corporate_actions.py::TestDetectOne` — created, already_known, a
genuine `no_events`, `rate_limited`/`not_supported`/`failed` each kept
distinct from `no_events`, unknown instrument → `None`,
`PriceBar`/`Lot` unchanged) plus the full 818-test suite green; `tsc -b`/
`oxlint` clean. **Live, against the real APLD position (instrument id 7)**:
first call → `{"status": "created", "found": 1, "created": 1}`, the
real reverse split (1:6, 2022-04-13) recorded with `source: "eodhd"`;
second call → `{"status": "already_known", "created": 0}`, no duplicate.
Invalid `provider` value → `422` (Pydantic, no custom code); unknown
`instrument_id` → `404`. In the browser: the new section renders with the
full tracked-instrument dropdown, and the actions table now correctly
shows "FMP (automatique)"/"EODHD (à la demande)" for every row instead of
a raw key.

## Decision 3u.36 — Corporate actions: readability rework of the detection summary (2026-09-07)

Frontend-only, no backend change. The single colored notice block that
Decision 3u.30–35 had accumulated (checked/candidates, found splits,
failed count, skipped count, and the not-checked caveat all stacked in
one `notice success/warning` box) mixed three different kinds of numbers
— provider coverage, historical event count, and verification failures —
into one paragraph. Real numbers from this portfolio made the confusion
concrete: `9/48 instruments vérifiés`, `35 split(s) détecté(s)`,
`Vérification impossible pour 39 instrument(s)` reads like "35 problems
and 39 broken positions" to a first-time reader, when the actual meaning
is "FMP's free-tier coverage of this portfolio is narrow; the 36 splits
already on file are unaffected."

Following a detailed UX critique, `CorporateActionsPanel.tsx` now
separates the block into two neutral (non-colored) sections plus one
scoped warning:

- **"Couverture automatique"** (only rendered after a `/detect` run):
  `{checked} instrument(s) vérifié(s) sur {candidates} avec FMP.` —
  naming FMP explicitly so a coverage gap reads as a provider limit, not
  an app or portfolio problem. `failed`/`not_checked`/`skipped` render as
  muted sub-lines (`"{count} instrument(s) n'ont pas pu être vérifiés
  automatiquement avec FMP."` — the word "automatiquement" now explicit,
  per the critique's point that "vérification impossible" read like a
  portfolio error). A coverage bar (reusing the existing
  `.refresh-progress-track`/`-fill` CSS from `ProgressBar.tsx`, not a new
  component) plus a `{percent} % de couverture` line give an immediate
  visual read. Only when `failed > 0 || not_checked > 0` does a single
  `notice warning` (amber, not the whole section) show the shortened
  caveat: "Une vérification indisponible ne signifie pas qu'aucun split
  n'existe. Vérifiez un instrument avec une autre source ou ajoutez une
  opération manuellement si nécessaire."
- **"Historique enregistré"** (always rendered): the persisted count —
  `{count} événements de division connus.`, sourced from `actions.length`
  (the already-loaded `GET /api/corporate-actions` list), deliberately
  *not* `detection.found` — the old `detectionFoundSummary` conflated "35
  events exist in the database" with "this scan found 35," which isn't
  the same claim and doesn't need FMP to have just run to be true. Right
  after a detection run, one muted line distinguishes "0 nouveau(x)"
  from "N nouveaux" (`historyNoNewEvents`/`historyNewEvents`) without
  repeating the total. "Ajouter manuellement" (button + form) moved into
  this section, since a manual entry is itself a form of recorded
  history — grouped with what it affects, not with the FMP scan trigger.

The EODHD single-instrument section (Decision 3u.35) sits between the two,
unchanged in behavior — user journey is now: bulk FMP coverage → gap
surfaced factually → targeted EODHD check for one instrument → persisted
history, always visible regardless of whether a scan just ran.

**Real bug found while live-verifying this rework, unrelated to the copy
changes themselves**: `api.createCorporateAction` and
`api.detectCorporateActionOne` in `client.ts` both sent a JSON string
body without `Content-Type: application/json`. `fetch()` defaults to
`text/plain;charset=UTF-8` for a string body when no header is set, and
FastAPI/Pydantic — confirmed directly via curl, with and without the
header — needs a JSON content type to parse the body as a dict; without
it, the raw string is handed to the Pydantic model and rejected with
`"Input should be a valid dictionary or object"`. This meant both "Ajouter
manuellement" and "Vérifier avec EODHD" were silently broken for any real
browser click, despite passing every prior curl-based verification (curl
explicitly sets the header) — the earlier browser checks for Decision
3u.30/3u.35 evidently never actually exercised a *fresh* click through
either button. Fixed by adding the header to both calls; confirmed live
in the browser this time — "Vérifier avec EODHD" on APLD correctly
returned `already_known`, and a throwaway manual entry
(APLD, 3:1, 2099-01-01) was created (`201`, history count went 36 → 37)
then deleted (`204`, back to 36) to leave the real database unchanged.

Verified: `tsc -b`/`oxlint` clean, full 818-test backend suite green
(unaffected — no backend files touched), live browser check of both new
sections plus the header-fix confirmation above.

## Decision 3u.37 — Beginner-comprehension pilot: Portfolio P0 (score color) + P1 (tooltips) (2026-09-07)

First implementation pass of the beginner-comprehension initiative (see
ARCHITECTURE.md-adjacent memory, not yet a doc section of its own): the
user proposed a product-wide rule — every technical term/status/metric
should answer "what is it / why is it shown / what does it change for
me" — and picked the Portfolio screen as the pilot. A Phase-1 audit
(inventory of ~19 displayed elements, a short glossary, a disclosure-level
decision per concept, and a P0–P3 priority list) surfaced one structural
finding and several P1 wording gaps. This entry covers implementing the
P0 fix and the P1 tooltips; the audit itself produced no code changes.

**P0 — the `ScoreBadge` color contradicted its own text.** `score-band-high`
used `var(--positive)` (the same green as a real gain) and `score-band-low`
used `var(--negative)` (the same red as a real loss) — exactly the
"green/red as financial verdict" anti-pattern this app has otherwise
avoided (see `SignalBadge`'s own comment about deliberately sharing one
color for both `reinforce`/`reduce`). The score's *text* was already
careful ("indicateurs globalement favorables," never "bon score" — see
Decision 3r.1/3u.27) but a beginner reads color before text. Fixed in
`index.css`: score bands now use a dedicated blue/gray scale, never
`--positive`/`--negative`/`--warning` — `high` reuses `--accent`/
`--accent-soft` (already the app's neutral-information color, used
elsewhere for e.g. `.tag.manual`), `low` reuses `--text-muted`/
`--surface-alt` (already neutral gray, used for `.tag.neutral`), and a
new `mid` tier needed one dedicated pair of tokens, `--score-mid`/
`--score-mid-soft`, defined for both light and dark mode. `scoreBand()`
itself (`ScoreBadge.tsx`) is untouched — only the CSS these class names
resolve to changed — so the fix automatically propagates to every
consumer of the shared component (Watchlist, Screener, `ScoreDetailRow`'s
strengths/watch-points split, which already rendered as plain text lists
with no color of its own, confirmed by inspection — no separate fix
needed there). Live-verified against the real portfolio: `ADBE.US`/
`NVO.US`/`ARCC.US`/`VICI.US` all show a high (blue) score next to a
negative (red) performance figure with no visual contradiction; several
mid-band (blue-gray) scores sit next to positive (green) performance the
same way — the two color systems no longer collide because they're no
longer the same palette.

**P1 — seven tooltips added, targeted at "could a beginner draw a wrong
financial conclusion from this," not an exhaustive icon-by-icon pass**:
`scores.notAdvice` appended to the existing composite-score tooltip
("Résume les indicateurs disponibles. Ce n'est pas une recommandation
d'investissement."); `totals.unrealizedTooltip`/`totals.performanceTooltip`
on the two Totals stat labels; `table.avgPriceTooltip` on the PRU column
header; `table.valueNotComputableTooltip` shown on a position's value
cell specifically when `current_value === null` (rather than only at the
aggregate level, where `totals.incomplete` already covered it);
`table.weightTooltip` reworded to say the percentage is of the
*currently computable* portfolio value, not silently "the total";
`priceStatus.stale` reworded to state the consequence ("la valeur
affichée peut ne pas refléter le marché actuel") instead of only the
cause; `allocation.gapTooltip` on the État column header reinforcing
`allocation.description`'s existing "never a buy/sell suggestion" framing
at the column level, not just the paragraph above the table. All seven
keys added to fr/en/pl.

**Explicitly deferred, per the user's own sequencing**: the audit of the
per-position detail screen — the user wants the Portfolio's now-stabilized
color/tooltip conventions to be the reference the next audit reuses,
rather than re-discovering the same score-color issue a second time.

Verified: `tsc -b`/`oxlint` clean (only the two pre-existing
`only-export-components` warnings, unrelated). Live browser check against
the real portfolio confirmed: no `score-badge` anywhere resolves to
`--positive`/`--negative` computed colors (checked via
`getComputedStyle`), all seven new tooltips render their exact text, and
the six requested real-data scenarios (high score + negative performance,
mid score + positive performance, over-allocated category, etc.) coexist
on one screen without the score and performance colors reading as the
same signal. No backend changes; no `pytest` re-run needed.

## Decision 3u.38 — Beginner-comprehension pilot: Position-detail P0 (raw enum + sentiment color) + P1 (disclaimers) (2026-09-07)

Second screen of the beginner-comprehension initiative, following the
sequencing rule the user set after Decision 3u.37: audit only after the
previous screen's conventions were implemented and verified, never
before. The Phase-1 audit of `PositionDetailRow.tsx` (the consolidated
per-position "Détails" panel) found two genuine implementation bugs
rather than pure wording gaps, both fixed here.

**P0-1 — raw internal enum leaking to the UI.** `not_priceable_reason`
was rendered directly — `<dd>{position.instrument.not_priceable_reason}</dd>`
— with no `t()` call, unlike every other value in this panel. The
backend (`ingest/service.py::detect_not_priceable`) only ever produces
`None` or the literal string `"corporate_action"` (confirmed by grepping
every assignment site), so a user could see the bare word
`corporate_action` with zero explanation. Fixed with a
`notPriceableReasonLabel()` helper in `PositionDetailRow.tsx`, following
the exact same "translate or fall back" pattern this file already used
for `categoryLabel()`: look up `positionDetail.notPriceableReasonValue.
{reason}`, and if that key doesn't exist (any future reason code this
function doesn't yet know), fall back to a translated
`positionDetail.notPriceableReasonValue.unknown` sentence — never the
raw string, even for values that don't exist yet.

**P0-2 — the news-sentiment tag reused the green/red verdict palette on
untranslated English.** `InsightsDetailRow.tsx` rendered Alpha Vantage's
raw label (`Bullish`, `Somewhat-Bullish`, `Neutral`, `Somewhat-Bearish`,
`Bearish`) verbatim, with `.sentiment-bullish`/`.sentiment-bearish` CSS
classes mapped to `var(--positive)`/`var(--negative)` — the exact same
reflex just fixed on the score in Decision 3u.37, but here applied to a
third-party classification of an article's tone rather than to the app's
own computed value. Fixed two ways: (1) a `sentimentLabel()` helper maps
all five raw values to translated `insights.sentiment.*` keys, falling
back to `insights.sentiment.unknown` ("Ton non disponible") for anything
unrecognized — same defensive pattern as P0-1; (2) `.sentiment-tag` in
`index.css` is now one flat neutral style (`--surface-alt`/`--text-muted`)
for every tone, with no per-category color at all — the *label text
itself* ("Ton nettement favorable" vs "Ton nettement défavorable")
already carries the direction, so no color scale was reintroduced to
encode it, deliberately avoiding building a second "positive/negative"
system under a different name. A `title` tooltip
(`insights.sentimentTooltip`) makes the provenance explicit: "Ton de cet
article selon son fournisseur (Alpha Vantage) — pas un avis de
l'application sur ce titre."

**P1, three items**: an `insights.commentaryDisclaimer` line ("Synthèse
générée à partir des données disponibles, potentiellement incomplète —
ne constitue pas un conseil en investissement") now renders directly
above any real AI commentary content in `InsightsDetailRow.tsx`. The
existing `dividends.disclaimer` notice (already shown on the standalone
Dividends page — "ne calcule pas votre impôt final...") is now reused
verbatim in this panel's Revenus section whenever it has rows to show,
rather than inventing a second, position-scoped disclaimer. The
`allocation.gapTooltip` added to the main Portfolio table in Decision
3u.37 is now also attached to this panel's own "État" `<dt>`, so the
same concept carries the same explanation wherever it appears rather
than being explained once and silently dropped the second time.

Verified live against the real portfolio. For the raw-enum fix
specifically, no held position currently has `not_priceable_reason` set,
so the fix was verified by temporarily setting
`instruments.not_priceable_reason = 'corporate_action'` directly on
APLD's row (id 7) via a single `UPDATE`, confirming the panel now shows
the full translated sentence instead of the raw string, then reverting
the same row back to `NULL` with a second `UPDATE` — read-verify-revert,
no lingering change to the real database. For sentiment: every one of
APLD's real news articles (~48 of them) rendered a translated label with
identical neutral gray styling and the provenance tooltip — confirmed via
`getComputedStyle`, zero `--positive`/`--negative` colors anywhere. For
the dividends disclaimer and allocation tooltip: confirmed on AAPL's real
position (real dividend history + an active allocation target). The
AI-commentary disclaimer's *conditional* rendering was confirmed correct
by inspection and `tsc`, but the "real content present" branch itself
wasn't exercised live — Perplexity is disabled in this environment (no
API key configured, per Settings), and clicking "Obtenir un commentaire
IA" correctly hit the existing graceful `commentary.outcome.code` fallback
path ("Perplexity n'est pas configuré") rather than incurring a real
paid request just to screenshot the disclaimer.

`tsc -b`/`oxlint` clean (same two pre-existing warnings). No backend
changes; no `pytest` re-run needed.

## Decision 3u.39 — Importing Amundi ESR and Mintos, with an honest P2P aggregate (2026-09-07)

The user asked to import two more real holdings into the tracked
portfolio: an Amundi ESR employee-savings account (PEG/PERCO, via
ArcelorMittal Méditerranée) and a Mintos P2P-lending account. Both
brokers' real exports were inspected before writing any code, and both
turned out structurally unlike XTB's per-transaction ledger:

- **Amundi** only publishes an annual PDF "Relevé annuel de situation" —
  a *snapshot* (unit price, quantity, gross value, Amundi's own estimated
  gain/loss per fund) plus coarse, undated annual contribution totals.
  There is no transaction-level export at all today.
- **Mintos** publishes a genuinely transactional quarterly PDF, but it
  covers two portfolios of very different nature: "Core ETF 90" is real
  ETFs with real ISINs (fits the existing model directly), while "Mintos
  Core" is dozens of auto-invested loan-note fragments (€1–50 each),
  valued by Mintos only as one portfolio-level quarterly balance — never
  per-fragment.

The user was explicit, after seeing the real numbers, that the Mintos
Core P2P aggregate must never be given a PRU or a computed gain/loss.
Both obvious choices are misleading: "PRU = last declared value" implies
a real cost that was never disclosed, and "PRU = cumulative
`Investments`" double-counts principal that gets automatically
reinvested every quarter (worked example the user supplied: if [montant]
is invested once and Mintos auto-reinvests every repayment, `Investments`
sums to far more than that amount even though only [montant] was ever
actually deposited). Decision: **value shown, PRU and gain/loss deliberately not
computed** — a real, distinct UI state ("non applicable" / "non
calculable"), not a fabricated zero.

**Data model.** Two new `Instrument.category` values, `"P2P"` and
`"FUND"`, both permanently `not_priceable_reason`-gated
(`"p2p_aggregate"` / `"employee_savings_fund"`) so they fall out of every
existing not-priceable code path for free — price refresh, fundamentals,
scoring already gate on category or on `not_priceable_reason`. Five new
`TxType` values for the P2P side (`P2P_INVESTMENT`,
`P2P_PRINCIPAL_REPAYMENT`, `P2P_INTEREST`, `P2P_FEE`, `P2P_SNAPSHOT`) —
deliberately distinct from `DEPOSIT`/`WITHDRAWAL`/`INTEREST` so these
internal-to-the-P2P-pool flows never get conflated with real,
bank-verified cash movements elsewhere in the app. New parsers
`app/ingest/mintos_import.py` and `app/ingest/amundi_import.py` (using
`pdfplumber`, newly added — no PDF library existed before this), each a
pure `parse_X(content, filename) -> ParsedXExport` feeding
`import_X_file()` in `ingest/service.py`, reusing the existing
preview/confirm/commit-or-rollback/dedup machinery XTB already
established rather than inventing a parallel path.

**Mintos ETF holdings are computed, not broker-reported.** Unlike XTB,
Mintos's PDF gives only the fill ledger and one portfolio-total balance —
no pre-aggregated per-ISIN position. A new pure function
`compute_average_cost_positions()` replays every buy/sell across *all*
statements imported so far (weighted-average cost for the Position's
`avg_price`, FIFO purely to decide which specific `Lot` closes, for the
historical-value chart) and the resulting Positions/Lots for the "Mintos
ETF" account are wholesale deleted and recreated on every import — the
one deliberate exception to "Lots are an append-only broker ledger,
never bulk-deleted," because for this account they are a *derived*
artefact of replaying the ledger, not a broker-sourced fact. Verified
against the real 6 statements: fully liquidated by Q3 2025 (0 open
positions), matching Mintos's own "Closing balance: 0.00"; net
bought/sold across 109 real transactions diffed to within a cent of
Mintos's own reported "Realized Return."

**The "no PRU" guarantee is enforced at read time, not just at write
time.** The schema still requires `Position.avg_price` NOT NULL, so it
holds a placeholder (`= broker_market_value`, comment explains why) —
but a new branch at the very top of
`routers/portfolio.py::_current_position_figures()`, checked *before*
the generic broker-value fallback that would otherwise happily compute a
P&L from those same two fields, short-circuits for
`category == "P2P"`: value is returned, `pl`/`pl_pct`/`price` are always
`None`, regardless of what the placeholder holds. A regression test
seeds `avg_price`/`broker_net_pl` with values that would imply a large
fabricated gain and confirms the API still returns `None`.

**Amundi's derived numbers are algebra on Amundi's own disclosure, not
invented.** `avg_price = (gross_value − estimated_gain_loss) / quantity`,
and — since `_current_position_figures`'s existing broker-value fallback
specifically reads `broker_net_pl`, not `broker_gross_pl` — both are set
to the same `estimated_gain_loss` (Amundi discloses only one P&L figure;
first attempt only set `broker_gross_pl` and silently produced no value
at all, since the fallback's guard requires both fields). A chronology
guard reuses `Position.opened_at` as an "as-of" date: an older statement
imported after a newer one is still fully persisted (browsable in import
history) but never regresses the current positions, so all statements
are safe to import in any order. The "Relevé d'information fiscale"
document (money paid straight to the user's bank account, never touching
a tracked position) is detected by title text and skipped with a clear
warning rather than mis-parsed or silently dropped.

**Frontend**: `ImportPanel.tsx` generalized from XTB-only to a `kind:
'xtb' | 'mintos' | 'amundi'` prop (three instances rendered in Settings →
"Données du portefeuille"), each pointed at its own preview/confirm
endpoint pair but sharing the same history/undo UI. `PositionsTable.tsx`
and `PositionDetailRow.tsx` render "non applicable" instead of a number
for a P2P position's average cost, with a tooltip naming Mintos's
declared-as-of date; Latent/Perf. already fall through to the existing
`common.notComputable`/em-dash rendering once the backend returns `null`
— no new mechanism needed there.

**Two real UI bugs found and fixed during live verification against the
production database** (not found by the test suite, which seeds
synthetic data that never exercised this combination):

1. `_unresolved_instruments()` (`routers/portfolio.py`) excluded CFDs by
   category and ISIN-holders by identifier, but had no exclusion for
   "structurally never priceable regardless of category" — so importing
   the real Amundi/Mintos files made all four new instruments appear as
   "needs a symbol correction" in Data Health, the onboarding checklist,
   and the Attention card, even though none of them will ever have a
   ticker to supply. Fixed by adding
   `Instrument.not_priceable_reason.is_(None)` to the exclusion — a
   strict narrowing of an already-AND'ed filter, so it can only exclude
   more instruments, never fewer, and it subsumes the CFD case rather
   than duplicating it. A regression test
   (`test_not_priceable_non_cfd_category_does_not_fall_into_unresolved`)
   seeds a P2P instrument the same way and asserts it lands in
   `not_priceable`, not `unresolved_instruments`.
2. `MappingCell.tsx` — the per-row "Mapping" column in the positions
   table — showed a "🚫 needs fixing" badge and a live "fix" button
   purely from `mapping_status === 'UNRESOLVED'`, independent of the
   backend fix above (a separate, parallel code path). Same bug, same
   root cause, one more place it leaked: fixed by short-circuiting to
   `t('common.notApplicable')` whenever `not_priceable_reason` is set,
   before the mapping-status branches run — this incidentally also fixes
   the same pre-existing false alarm for every already-held CFD position,
   not just the new categories.
3. While fixing (2), noticed `priceStatus.not_priceable`'s tooltip text
   was hardcoded to "no market price by nature (corporate action
   artefact)" in all three locales — accurate for CFDs/corporate-action
   residuals, actively wrong for the new P2P/FUND categories. Reworded to
   a reason-agnostic sentence pointing at the position detail panel
   (which already names the specific reason via
   `notPriceableReasonLabel()`, Decision 3u.38) rather than duplicating a
   per-reason branch in a third place.

New `positionDetail.notPriceableReasonValue.p2p_aggregate` /
`.employee_savings_fund` and `breakdown.category.P2P` / `.FUND` i18n
entries (fr/en/pl) so neither leaks as a raw code or an unmapped
category label anywhere in the app.

**Live-verified against the real production database** (backed up via
the existing Backup panel first): all 6 real Mintos quarterly PDFs and
all 5 real Amundi PDFs (3 distinct annual statements, one literal
duplicate re-download, one fiscal document) imported through the actual
HTTP endpoints. The duplicate was correctly deduplicated
(`transactions_inserted: 0`); the fiscal document was correctly detected
and skipped with `import.amundiFiscalDocumentSkipped`. Resulting real
positions matched hand-checked figures exactly: Amundi PEG/PERCO gains
matched Amundi's own 2025 statement exactly, Mintos
Core P2P showing a value with `unrealized_pl`,
`unrealized_pl_pct`, and `current_price` all `null` and a "non
applicable" PRU in both the table and the detail panel. Portfolio
breakdown by asset class now shows "Employee savings funds" and "P2P
loans" as first-class categories alongside Stocks/ETFs. Confirmed via
`/api/portfolio/data-health` and `/api/portfolio/onboarding` that none
of the four new instruments appear as unresolved after the fix.

Full backend suite: 850 passed (849 + 1 new regression test), `tsc -b`
and `oxlint` clean (same two pre-existing warnings, no new ones).

## Decision 3u.40 — Lost `.env`: fsync on save, so a confirmed key save is actually durable (2026-09-07)

Discovered live, same day: every keyed provider (FMP, EODHD, Twelve
Data, Alpha Vantage, Perplexity, etc.) showed `enabled: false` in
Settings. `/api/health`'s `env_files` diagnostic (added earlier for
exactly this kind of question) confirmed the actual cause: neither
`.env` location (project root, `backend/.env`) existed on disk at all —
not a code bug, the secrets file itself was gone.

Root-caused, not just patched: `uptime -s` showed the machine had
rebooted that same morning, mid-session (matching an earlier moment
this session where the backend process was found not running and had
to be restarted manually). The mount is a normal `ext4` partition, not
a live/overlay filesystem, which rules out "non-persistent environment"
— on a normal persistent disk, a *clean* shutdown always flushes
pending writes. The remaining explanation:
`routers/settings.py::update_api_keys` (`PUT /api/settings/api-keys`,
which writes `.env`) did a plain `open(path, "w") as f: f.write(...)` —
closing a file only flushes Python's buffer into the OS page cache, not
onto the physical disk. If the reboot was unclean (crash, forced power
cycle) within the window before the kernel's own writeback timer ran, a
very recently saved `.env` can be lost even though the API call
reported success. This file is a uniquely fragile one in this project:
deliberately `.gitignore`d (it holds real secrets) and never covered by
the SQLite backup feature (Decision 3u.29), so it has no safety net of
any kind today.

Fixed the part actually within the app's control:
`f.flush(); os.fsync(f.fileno())` added right before the file closes —
a successful response from this endpoint now means the bytes are
confirmed on disk, not just handed to the kernel. Does not protect
against a lost/reformatted disk or a `.env` deleted by something outside
the app (fsync only closes the "recent write lost to an unclean
reboot" gap) — the user was told plainly that keeping an external copy
of the actual key values (password manager, secure note) is the only
real protection against that, since this project will never back the
file up anywhere by design.

Recovery for this specific incident: `.env` recreated at the project
root from `.env.example` (comments and variable names only, no values —
safe to copy verbatim since the template never held secrets), `chmod
0600`. The user re-enters their real keys through the existing Settings
→ clés API UI, which now uses the fsync'd write path.

Full backend suite: 850 passed, unchanged. No test added for the fsync
call itself — a real disk-durability guarantee isn't observable through
`pytest`'s in-memory/temp-file fixtures; the fix was verified by
inspection and by confirming `/api/health`'s `env_files` flips to
`true` once the file exists again.

## Decision 3u.42 — A P2P position's whole value, not just its P&L, was silently excluded from every total (2026-09-07)

Found live: the user reported the portfolio total looked wrong — XTB's
own total matched the broker's site, but Mintos Core P2P
(declared value on the real Mintos site) wasn't reflected anywhere in
the app's totals at all, and Amundi's total (on the real site)
looked too low as well.

Two independent problems, confirmed separately rather than assumed to be
one:

**A real bug in `_aggregate()` (`app/routers/portfolio.py`).** Since
Decision 3u.39, a P2P position (Mintos Core) deliberately gets a real,
broker-declared `value` but a permanently `None` `pl` from
`_current_position_figures` — the user explicitly rejected ever
fabricating a cost basis for it. `_aggregate()`'s exclusion check was
`if value is None or pl is None: excluded += 1; continue` — treating
"P&L unknown" exactly like "value unknown" and dropping the position from
the sum *entirely*, even though its value was perfectly known and had
been surfaced by `_current_position_figures` for exactly this purpose.
Live-confirmed before the fix: Mintos's real position showed a real,
non-null `current_value` in the positions list, but the "Mintos Core P2P"
account row in `totals.accounts` showed `market_value: null`, and the
global `totals.market_value` excluded it too — the
account-level bug was the same root cause as the whole-portfolio one, not
a second one. No existing test caught this: `TestP2PAggregate`'s two
tests both asserted only the per-position `current_value`/
`current_unrealized_pl` fields, never the aggregate totals a P2P position
should still contribute to.

Fixed by separating the two exclusion conditions: a position is excluded
from the total only when `value is None`; when `value` is known but `pl`
isn't, the value is added to `market_value` and simply skipped for the
`unrealized` sum (never coerced to zero P&L, never fabricated) — the
account/global `invested_value` (`market_value − unrealized`) then
correctly reads as "this position's whole value, since no gain/loss is
known for it," which matches the never-fabricate-a-PRU principle exactly.
Two new tests added to `TestP2PAggregate` (`tests/test_api.py`):
Mintos's value now counts toward both `totals.market_value` and its own
account row, with `excluded_positions == 0`; a P2P position alongside a
normally-valued one sums correctly (doesn't exclude or double-count
either). Live-verified against the real DB after the fix: global
`market_value` rose to include Mintos's own value now
included, `excluded_positions` from 1 to 0, `has_incomplete_data` from
`true` to `false`.

**A separate, non-code problem: both imports are stale.** Even after the
fix, Mintos's imported value still doesn't match the user's stated
current total — traced to the imported source file itself: a quarterly
statement covering 2025-07-01 to 2025-09-30, a full year
before this session's date (2026-09-08). Nothing in the code can recover
a balance the source document itself doesn't contain; re-importing a
current Mintos statement is the only fix. Amundi's total (well under
what the user reported) is very likely the same root cause — Amundi
only publishes periodic/annual snapshot PDFs (Decision 3u.39), and the
imported filename (`DOCINT_RAC (copy 1).pdf`) carries no date to confirm
directly, but a code-side explanation was ruled out (its `broker_net_pl`
is populated and correctly summed, unlike Mintos's `_aggregate()` gap
above) — told to the user as "probably the same staleness issue, needs a
fresh statement" rather than asserted as fact.

Full backend suite: 901 passed (899 + 2 new).

## Decision 3u.43 — A live "Investments" .xlsx import for Mintos Core, alongside the stale quarterly PDF (2026-09-08)

Direct follow-up to Decision 3u.42: the user tried three different Mintos
exports to fix Mintos's stale value, in order — each inspected before
building anything, rather than assumed usable:

1. **`20260908-account-statement.csv`** (a single day, 00:01-11:02): a raw
   cash-ledger export (interest/principal/tax-withholding micro-transactions
   per loan fragment) with a running `Solde` column. Rejected: `Solde` never
   rose above a small fraction of the real invested total across that day —
   it tracks free cash cycling through auto-invest reinvestment, not the
   portfolio's invested value.
2. **The same export, full history** (`(copy 1).csv`, 2025-01-01 to
   2026-09-08, a large number of rows): same rejection, confirmed more
   thoroughly — `Solde` stayed just as small across the *entire* 20-month
   history. No amount of additional history fixes this; it is structurally
   the wrong metric, not a stale one.
3. **`Investments-08-09-2026.xlsx`** (from Mintos's "My investments" page,
   several hundred active note fragments): usable. Summing its `Montant investi`
   column matches the user's own stated real total (read directly off the
   Mintos site the same day) closely enough to attribute the small
   remaining gap to the two observations not being the exact same instant
   rather than a wrong column. `Principal restant`
   (the outstanding note balance net of amortization) was checked too and
   does *not* match — some narrower
   figure than "this investment's current value," left unused.

Built a second Mintos import path rather than folding this into the
existing PDF importer: `app/ingest/mintos_investments_import.py`
(`parse_mintos_investments_export` — sums `Montant investi` across the
first worksheet, with the "as of" date coming from the filename itself,
`Investments-DD-MM-YYYY.xlsx`, since the file carries no date internally)
and `app/ingest/service.py::import_mintos_investments_file`, wired to new
`POST /api/imports/mintos-investments` and `.../mintos-investments/preview`
endpoints. Deliberately reuses the exact mechanism the PDF importer
already established rather than inventing a second one:
one more `TxType.P2P_SNAPSHOT` transaction (deduplicated by its "as of"
date), and `_recompute_mintos_p2p_position` — unchanged — already shows
whichever snapshot is dated latest, from either source. This means a
fresh Investments export always supersedes an older PDF's closing
balance automatically, and an accidentally-old Investments file can never
regress a newer PDF period either — verified by two explicit persistence
tests, not just asserted. The "Finished-Investments" export (matured/
repaid loans) the user also added was not parsed — irrelevant to
*current* portfolio value, the only problem being solved here.

11 new tests (`tests/test_mintos_investments_import.py`): pure-parsing
(sum correctness, a non-numeric cell skipped rather than crashing, three
distinct not-a-crash warning paths — no date in filename, missing
expected column, unreadable content) built against a small synthetic
workbook, never the user's real export (same personal-data reasoning as
the existing PDF tests); persistence (creates the snapshot/position,
re-import is a no-op, an empty parse creates nothing); and the two
cross-source-supersession tests above, reusing `_p2p_period`/
`ParsedMintosExport` imported from `test_mintos_import.py`.

**Live-verified against the real portfolio**: preview showed
`positions_found: 1, transactions_found: 1, warnings: []`; the real
import updated Mintos Core P2P's displayed value from the stale 2025-07/09
PDF figure to the fresh one; the global portfolio total rose
accordingly. Full backend suite: 912 passed (901
+ 11 new).

## Decision 3u.44 — The same live-snapshot fix for Amundi, plus a second, recurring `_current_position_figures` gap it exposed (2026-09-08)

Same day, same pattern as Decision 3u.43: the user added a fresh Amundi
export — `Synthese_20260908_104534.xlsb`, downloaded directly from the
ESR portal's own data feed, a genuinely different format from the annual
"Relevé annuel de situation" PDF (`amundi_import.py`). Inspected before
building anything (`pyxlsb`, not yet a dependency, installed and added to
`requirements.txt`): two sheets, `Donnees` (JSON-shaped account metadata,
unused) and `Mes avoirs par échéance` — one row per (fund, vesting
maturity) pair, since a French "Plan Epargne Groupe" allocates a new
tranche with its own 5-year lock-up maturity every year. The same fund can
have several rows here — this account's real export had two maturities
for "the company-shareholding fund" alone — summed per fund
to match the existing one-position-per-fund
model. Live cross-check: summing `Montant évalué` across every fund
matched the user's stated real Amundi total far
more closely than the already-imported annual PDF's figure — which
undercounted specifically because it was missing that second, more
recently allocated tranche of the company-shareholding fund, not because
the PDF import itself was ever wrong, just older.

Built the equivalent of Decision 3u.43's Mintos solution: rather than a
second full copy of the persistence logic, `import_amundi_file`'s body
was extracted into a shared `_persist_amundi_export(db, parsed, content,
filename, commit)`, called by both the existing PDF path and a new
`import_amundi_synthese_file` (`app/ingest/amundi_synthese_import.py`'s
`parse_amundi_synthese_export`, wired to new `POST /api/imports/amundi-
synthese` + `.../preview` endpoints). Both paths already shared the same
freshness rule (`Position.opened_at` as the source's "as-of" date, newer
always wins per account) unchanged, so a fresher Synthese export
supersedes an older PDF automatically and vice versa — verified by two
explicit tests, same as Mintos's. This format carries no per-fund
gain/loss figure at all (unlike the PDF) — `ParsedFund.estimated_gain_loss`
is always `None` from this source.

**That last fact immediately exposed a second, independent bug — the
same root shape as Decision 3u.42's, recurring in a different function.**
The real import's account totals came back `null` again, `excluded_positions:
3`: `_current_position_figures`'s *generic* broker-value fallback (used
by every non-P2P category, `routers/portfolio.py`) required *both*
`broker_market_value` and `broker_net_pl` to be non-`None` before
returning a value at all —

```python
if position.broker_market_value is not None and position.broker_net_pl is not None:
    return (round(position.broker_market_value, 2), round(position.broker_net_pl, 2), ...)
return None, None, None, None, "broker"
```

— so a position with a real, known value but a genuinely unknown P&L (this
new import's own honest limitation, not a bug in it) lost its *value* too,
not just its P&L, the exact "value is None or pl is None" conflation
Decision 3u.42 fixed once already for `_aggregate()`'s P2P-specific
branch — except this is the generic fallback every FUND/CFD/manually-
entered position without a live price also runs through, so the same
mistake was sitting in a second place, only surfaced now because nothing
had previously created a position with a real value and a `None` P&L
through *this* code path (the P2P branch bypasses it entirely; every
other category always had both or neither, until now). Fixed the same
way: return the value whenever `broker_market_value` is known, and leave
`pl`/`pl_pct` as `None` independently rather than withholding the value
too. Two new tests (`TestBrokerValueFallbackWithoutPnl` in
`tests/test_api.py`) cover this specific shape directly, not just via the
Amundi import path that happened to expose it.

13 new tests (`tests/test_amundi_synthese_import.py`) — `pyxlsb` has no
writer, so parsing tests patch `open_workbook` itself with a mock exposing
its `.sheets`/`.get_sheet(...).rows()` shape rather than round-tripping a
real binary file: tranche-summing, PEG/PERCO account routing, "Ligne
Total" subtotal rows correctly excluded (not double-counted), three
distinct not-a-crash warning paths (no date in filename, missing sheet,
unreadable content); persistence tests reusing `_fund`/`ParsedAmundiExport`
from `test_amundi_import.py`, including the same cross-source-supersession
shape as Mintos's.

**Live-verified against the real portfolio**: preview showed
`positions_found: 3, warnings: []`, correctly split across both accounts;
the real import updated Amundi's total sharply upward (PEG and PERCO
both correctly split); after the broker-fallback fix, the global
portfolio total rose accordingly, `has_incomplete_data`
back to `false`, `excluded_positions: 0`. Full backend suite: 927 passed
(912 + 13 + 2).

Also added, alongside both new "live snapshot" import buttons in Settings
(`import.mintos-investments.*`/`import.amundi-synthese.*` i18n keys,
fr/en/pl; `ImportPanel`'s `BrokerKind` union extended): the whole point of
building real importers instead of a one-off manual value edit is that
the user can repeat this next time their broker-reported total drifts,
without needing this session's investigation again.

## Decision 3u.45 — Target allocation's Edit/Delete buttons were reachable only after scrolling the table (2026-09-08)

The user reported "no button/interface to configure targets" for the
Portfolio page's "Target allocation" table. Investigation showed the
opposite of a missing feature: `GET /api/portfolio/allocation` and the
`PUT`/`DELETE` endpoints all worked correctly, and by the time this was
checked the user had *already* found and used it — all four categories
(including the two Decision 3u.44 just fixed the totals for) had real
15–40% targets saved. The actual problem, confirmed by the user directly:
`AllocationTargets.tsx`'s table put the Edit/Delete/"Set target" actions
in the *last* column, after a column that can hold a full sentence
("About 4,030.09 in new contributions would reach the minimum of this
range — a static estimate assuming...") for any row in the `under` state —
long enough to push the action buttons off the visible width of
`.table-wrap`'s `overflow-x: auto` container, so a real user had to
notice and use horizontal scroll before finding a button that was, in
fact, always there.

Fixed by reordering columns, not by touching `.table-wrap` (a generic
wrapper shared by every table in the app — changing it globally wasn't
warranted for one table's specific content shape): actions now sit right
after the compact "Status" column, with the long free-text "amount to
reach the minimum" column moved last instead. No backend change — this
was a pure column-order fix. Verified live: the reordered table renders
correctly, "Edit Delete" now appears immediately after "Status" for every
row instead of after a sentence-length cell.

## Decision 3u.46 — An account with no known P&L anywhere showed a fabricated "0.00 / 0.00%" instead of "unknown" (2026-09-08)

Reported directly by the user right after Decision 3u.44 landed: "il nous
manque le latent et perf pour l'amundi et mintos" (missing unrealised/perf
for Amundi and Mintos). Root cause, in `_aggregate()`
(`app/routers/portfolio.py`): `unrealized` is a running sum initialised to
`0.0`, only ever incremented for a position whose `pl` is known — so an
account where *every* position's P&L is unknown (Mintos Core P2P, by
design since Decision 3u.39; Amundi funds once their most recent import is
the Synthese live snapshot, which carries no gain/loss column at all,
Decision 3u.44) summed to a literal, committed `0.0`, not an absence of
data. That flowed into `invested = market_value − unrealized` (silently
equal to `market_value`, implying "zero known gain" — itself a second
fabrication) and `unrealized_pl_pct = 0/invested×100 = 0.00%` — both
looking like confident, precise facts rather than "we don't know."

Fixed by tracking whether *any* counted position in the group contributed
a known `pl`; `_aggregate()` now returns `None` (not `0.0`) when none did.
`_compute_totals`/`_compute_account_totals` propagate that `None` through
to `invested_value`/`unrealized_pl`/`unrealized_pl_pct` — deriving
`invested` from an unknown `unrealized` is unknown too, not silently
"today's value" (a different, equally fabricated zero-gain assumption). A
*mixed* group (at least one known contribution — always true for the
global portfolio total, which mixes ordinary priced holdings with
Mintos/Amundi) still sums only the known contributions, same
partial-information posture `excluded_positions` already signals for
value. **No frontend change needed at all**: `formatNumber`/
`formatSignedPercent`/`signClass` already render `null` as "—" in neutral
styling ("Anything that depends on the user's language... A missing value
renders as an em dash, never as '0': unknown is not zero" — already
written into `i18n/index.tsx`, just never reached because the backend was
sending a real `0.0` instead of `null`) — the per-account table in
`Portfolio.tsx` was calling these helpers unconditionally already.

2 new tests (`TestUnknownPnlIsNeverDisplayedAsZero` in `tests/test_api.py`):
an all-unknown-P&L account (Mintos-shaped) shows `None` for
`unrealized_pl`/`unrealized_pl_pct`/`invested_value` while `market_value`
stays known; a mixed group (P2P + a normal Amundi-shaped fund with a real
`broker_net_pl`) still sums the known contribution rather than going blank
entirely. **Live-verified**: Amundi PEG/PERCO and Mintos Core P2P's "By
account" row now render "—" for Invested/Unrealised/Perf. instead of
"0.00"/"0.00 %", global totals (which mix in real XTB positions) unaffected.
Full backend suite: 929 passed (927 + 2).

**Recurring lesson across Decisions 3u.42/3u.44/3u.46, worth remembering
generically for this codebase**: any aggregation that combines a "value"
figure with an "optional companion" figure (P&L alongside value here; the
same shape could recur for e.g. a fundamentals metric with an optional
YoY comparison) must track "was *any* input known" separately from the
running sum itself — initialising an accumulator to `0` and only
conditionally adding to it silently conflates "genuinely zero" with
"nothing contributed," and that conflation reliably survives review
because the code *looks* correct in the common case where something is
always known.

## Decision 3u.47 — Real, honestly-approximated gain/performance for Mintos and Amundi (2026-09-08)

Direct follow-up to Decision 3u.46: with `unrealized_pl`/`unrealized_pl_pct`
now correctly showing "—" for Mintos/Amundi instead of a fabricated
"0.00", the user asked for the missing piece back — real performance
figures, computed from what the already-imported exports actually
contain, "avec tous les exports fournis il est possible de calculer
combien pourcent on a gagné." Investigated what each broker's real data
supports *before* building anything:

- **Amundi**: the annual PDF's own `aggregate_totals` (versements
  volontaires, abondement, intéressement — DEVLOG "Decision 3u.39") are
  real contribution figures, but only for the years actually imported.
  Live-checked: only 2023 and 2025 exist for this account, 2024 is
  missing entirely — a naive "value − known contributions" gain would
  read as an implausibly large percentage for Amundi PEG, not because
  that's wrong arithmetic, but because the denominator is known-incomplete.
- **Mintos**: tried the full account-statement CSV's real "Dépôts"
  (deposit) transactions as a cost basis first — rejected: the file only
  covers 2025-01-01 onward, while the account opened in April 2024 (its
  first quarterly PDF's own `opening_balance: 0.0` proves this), so a
  chunk of real deposits is invisible to it. Unlike a deposits-based cost
  basis, **real income (interest, bonuses, late fees received) needs no
  such completeness** — interest earned in a given window is interest
  earned, independent of what happened before it or how much was ever
  deposited. This sidesteps the missing-data problem entirely rather than
  working around it.

Asked the user directly how to handle the Amundi gap (present the
options: wait for the missing file, compute anyway with an explicit
caveat, or show only real absolute figures instead of a ratio) — chose
"calculate with what we have, with an explicit mention." Built
accordingly, for both brokers:

- **`app/ingest/mintos_transactions_import.py`** (new): parses the full
  Mintos account-statement CSV, categorising each row's "Type de
  paiement" into real income (`Intérêt perçu`, `Intérêts perçus sur le
  rachat de prêt`, `Revenus des intérêts sur les obligations`, `Delayed
  interest income on transit rebuy`, `Revenus de décote des obligations`,
  `Frais de retard perçus`, `Bonus`) or real cost (`Tax withholding`,
  `Mintos Core fee`, `Prélèvement à la source sur les obligations`) —
  `Investissement`/`Principal perçu`-type rows (internal auto-invest
  churn — Decision 3u.39) and `Paiement ETF entrant`/`...sortant` rows
  (the separate Core ETF 90 sub-portfolio) are deliberately excluded from
  both buckets. `import_mintos_transactions_file` combines this file's
  own income/cost with whatever `P2P_INTEREST`/`P2P_FEE` transactions
  already exist from *before* this file's own date range (periodic PDF
  or an earlier CSV import) — avoiding double-counting by construction,
  since both sources persist to the same transaction types dated at
  their own period's end. New `POST /api/imports/mintos-transactions` +
  `.../preview`.
- **Amundi**: `_persist_amundi_export` now falls back to a pro-rata
  share of (account value − known contributions) whenever a fund's
  source doesn't disclose a gain (always true for the Synthese export) —
  computed once per account (contributions aren't tracked per-fund in
  the source data) and split across that account's funds by value share,
  so the parts sum exactly to the account-level approximation. A fund
  whose source *does* disclose a real gain (the annual PDF always does)
  keeps that figure outright — the fallback only ever fills a genuine
  gap, never second-guesses a real disclosed number.
- **`Position.performance_note`** (new column, migration `dc86498fab27`
  then retyped to JSON in `2bccf46c5433`): a caveat attached to a
  position whose `broker_net_pl`/`broker_net_pl_pct` came from one of
  these approximations, surfaced through `AccountTotals`/`PositionOut`
  and rendered in `Portfolio.tsx`'s "By account" table as a `*` marker
  (title-tooltip) plus a plain-text note listed below the table — not
  hidden behind hover-only discovery, the exact lesson from the Target
  Allocation button complaint two decisions ago (3u.45).

**Two real bugs found and fixed via live verification against the real
portfolio, not caught by the unit tests first written**:
1. **The P2P branch in `_current_position_figures` unconditionally
   returned `pl=None`, ignoring `broker_net_pl` even when a real,
   separately-computed figure was stored there.** This branch was
   written for Decision 3u.39's "never derive a P&L from `avg_price` ×
   quantity" guarantee — right at the time, since nothing else ever
   populated `broker_net_pl` for a P2P position — but became
   *over*-broad once this decision started deliberately setting it to a
   real, non-fabricated value. Fixed to pass through
   `broker_net_pl`/`broker_net_pl_pct` unchanged while still never
   deriving one from `avg_price` itself; `tests/test_api.py`'s
   `test_pl_stays_none_even_if_avg_price_would_imply_a_gain` was renamed
   and narrowed to test exactly that narrower guarantee, and a new test
   confirms the pass-through explicitly.
2. **Storing raw French sentences on `Position.performance_note` directly
   violated this codebase's own established convention** ("the backend
   never returns prose meant for humans" — `app/messages.py`'s module
   docstring, already followed by every import diagnostic) — would have
   silently never translated for English/Polish users. Caught before
   shipping to the frontend: refactored to the same `{code, params}`
   shape as an import `Message` (new `PerformanceNote` code namespace,
   `MessageOut`-typed in the API schema, `t(note.code, note.params)` on
   the client) — required a second migration to retype the column
   `TEXT` → `JSON`, and clearing 4 already-written raw-text rows from the
   real DB that predated the fix (found by a `JSONDecodeError` crashing
   the very next unrelated read of those rows — SQLAlchemy eagerly
   deserializes a `JSON`-typed column on every row fetch, not just when
   the value is accessed).
3. **A third bug, in the "since" date shown for Mintos**: computed as
   `min(Transaction.executed_at)` across every `P2P_INTEREST`/`P2P_FEE`
   transaction — but every such transaction (periodic PDF or this new
   CSV importer) is dated at its *period's end*, not its start, so
   "earliest known activity" collapsed to whichever single import
   happened to be the only one on record, understating real history by
   an entire period. Fixed by reading each transaction's own recorded
   `period_start` from its `raw` JSON instead — which surfaced a fourth,
   smaller bug: the periodic PDF importer stores a full datetime string
   ("2024-04-01T00:00:00"), this new importer stores a plain date
   ("2025-01-01") — `date.fromisoformat` rejects the first shape,
   crashing the whole import. Fixed with `datetime.fromisoformat(...).date()`,
   which accepts both. A new test seeds a `raw` payload shaped exactly
   like the real PDF importer's output specifically to catch this again.

30 new tests across `tests/test_mintos_transactions_import.py` (13,
including the pre-period combination and the two datetime-shape
regressions), `tests/test_amundi_synthese_import.py`'s new
`TestAmundiProRataFallbackGain` (4: single-fund fallback, pro-rata split
across multiple funds, no fallback without any known contributions, a
real disclosed gain never overridden), and `tests/test_api.py`'s revised
P2P tests (the narrowed guard plus the new pass-through test). Also
raised `MAX_UPLOAD_BYTES` from 25MB to 50MB — the real Mintos CSV export
came in at ~32MB, a legitimate file that would otherwise have been
rejected outright.

**Live-verified against the real portfolio, end to end, including the
mid-verification bugs above** (each caught by testing against the real
data, not assumed correct after the unit tests passed): Mintos Core P2P
now shows a real invested amount and gain, "depuis le 2024-04-01" (the
account's real, provable inception date, opening_balance 0.0 in its first
quarterly PDF); Amundi PEG shows a real amount and gain, "depuis le
2023-12-31" (the earliest year actually imported — explicitly and
honestly a likely overstatement, per the user's own chosen tradeoff);
Amundi PERCO shows its own real amount and gain. Global portfolio totals
(which mix these with ordinary priced holdings) rose unrealised
accordingly. Full backend suite: 947
passed (929 + 30 − 12 net, after also folding in the two revised P2P
tests). Frontend (`tsc -b`, `oxlint`) clean, same two pre-existing
warnings only, confirmed live in-browser in English (translation working
end-to-end, not just present in the catalogue).

## Decision 3u.48 — Exact per-fund Amundi gain when a fund's quantity hasn't changed (2026-09-08)

Direct refinement of Decision 3u.47's Amundi pro-rata fallback, prompted
by the user's own audit question ("est-ce que tout ça c'est correctement
calculé... ?"). Answering it honestly surfaced that Amundi's real
2024 annual PDF (`DOCINT_RAC-1.pdf`) had never been imported — the
project's local `Extractions/Amundi/` folder held it unimported all
along. Importing it didn't recover the account-level contributions table
this parser expects (the 2024 document uses a different, condensed
template), but it did disclose a real per-fund gain figure for each of
its three funds — and one of them, FONDS MONETAIRE PEG, still exists
today with an unchanged quantity, meaning an *exact* gain is computable
for that fund alone, without pro-rating anything.

Generalised this into a standing mechanism rather than a one-off fix.
New `AmundiFundSnapshot` table (`broker_symbol`, `as_of`, `quantity`,
`gross_value`, `estimated_gain_loss`) records **every** fund's disclosed
figures from **every** Amundi import (annual PDF or live Synthese),
unconditionally — a real, previously-unnoticed gap: `_persist_amundi_export`
only ever kept the *winning* import's figures as live `Position` rows; an
older import's fund-level detail, once superseded, was silently discarded
after parsing (only the `ImportBatch.positions_found` count survived).
Snapshots are now written before the freshness-check `continue`, so
history accumulates regardless of import order.

`_amundi_real_gain_since_snapshot(db, broker_symbol, current_quantity,
current_value, before)` looks up that fund's most recent prior snapshot
with a real disclosed gain, and — only if the quantity matches within
`1e-4` (no new contribution to *this specific fund* since then, which
would muddy the comparison) — returns `current_value − (snapshot.gross_value
− snapshot.estimated_gain_loss)` as an exact gain, tagged
`PerformanceNote.AMUNDI_REAL_GAIN_SINCE_SNAPSHOT`. Per fund, in
`_persist_amundi_export`'s import loop, this is tried *before* the
account-level pro-rata fallback; pro-rata only applies to funds with no
usable per-fund anchor (typically because a new contribution changed
their quantity). `_compute_account_totals` (`routers/portfolio.py`) was
updated to still prefer the `AMUNDI_APPROXIMATE_GAIN` note when an
account mixes both kinds — the account-level total remains honestly
caveated as long as *any* of its funds relies on the cruder
approximation, even if others now have an exact figure.

**Live-verified against the real portfolio**: after re-importing all
three annual PDFs (2023/2024/2025) plus the live Synthese export in
chronological order, FONDS MONETAIRE PEG (Amundi PEG) now shows an exact
gain, "depuis le 2025-12-31" — replacing what would otherwise have been
its share of the account's cruder pro-rata approximation — while
the company-shareholding fund, whose quantity changed between
2025 and 2026 due to a new contribution, correctly still falls back to
the account-level approximation. The Amundi PEG account total itself
still displays the honest `amundiApproximateGain` caveat (mixed-precision
account), matching the note-priority rule above.

**Real, disclosed limitation found and left as-is, not silently patched**:
FONDS RETRAITE PERCO (Amundi PERCO) failed to get the exact treatment despite an
effectively unchanged quantity, because Amundi's own
two export formats disagree on this fund's name — `"FONDS RETRAITE PERCO SOLIDAIRE"`
in the annual PDF vs `"FONDS RETRAITE PERCO"` in the Synthese export — which produces
two different `broker_symbol` slugs and breaks the snapshot lookup. Chose
not to add fuzzy/substring name matching to paper over this: two
genuinely different funds could plausibly share a similar quantity by
coincidence, and silently pairing them would produce a wrong "exact"
figure with no caveat at all — worse than the safe, correctly-labelled
pro-rata fallback it currently gets instead.

3 new tests in `tests/test_amundi_synthese_import.py`'s new
`TestAmundiRealGainSinceSnapshot` (unchanged quantity → exact gain;
changed quantity → pro-rata fallback; both kinds coexisting within the
same account, each fund keeping its own note). The pre-existing
`test_fallback_gain_is_split_pro_rata_across_multiple_funds` test
incidentally became a mixed-precision case once its second fund's
quantity happened to stay unchanged between imports (a consequence of
this feature actually working, not a bug) — adjusted its fixture so both
funds' quantities change, keeping that test isolated to the pure
pro-rata path it was written to cover. Full backend suite: 950 passed.
Frontend (`tsc -b`, `oxlint`) clean, same two pre-existing warnings only.
New i18n key `performance.amundiRealGainSinceSnapshot` added to all three
locales.

## Decision 3u.49 — "Depuis" showed today's date for Amundi/Mintos after a fresh snapshot import (2026-09-08)

User-caught, same day as Decision 3u.48: "dans les transactions il est
marqué que les investissements Amundi avaient lieu aujourd'hui, ce qui est
faux." Traced to `Position.opened_at` — rendered in the UI as "Depuis"
("since"/held-since) — being silently overloaded with a second, unrelated
meaning for these two brokers: for Amundi, `_persist_amundi_export` used
it both to decide *whether this import is newer than what's stored*
(compared against the new import's own `as_of`) and to answer *since when
you've held this fund* for display; for Mintos, `_recompute_mintos_p2p_position`
set it to the *latest* known P2P snapshot's date (correct for picking
which value to show, wrong for "since"). Confirmed live in the real DB
before touching any code: both Amundi's Synthese-derived positions and
the Mintos Core P2P position showed `opened_at = 2026-09-08` — today,
the date of the live snapshot files re-imported for Decision 3u.48 —
while the real Mintos account opened 2024-04-01 (per Decision 3u.47) and
the real Amundi PEG contributions go back to at least 2023.

Fixed by decoupling the two questions rather than trying to make one
field answer both honestly:

- **Amundi**: freshness is now judged from `AmundiFundSnapshot`'s own
  history (`max(as_of)` for this account's fund symbols, captured
  *before* this import's snapshot rows are written) instead of
  `Position.opened_at` — a table that didn't exist before Decision 3u.48
  and is now the natural single source of truth for "have we seen a
  newer statement for this fund." `Position.opened_at` is set to each
  fund's *earliest* recorded `AmundiFundSnapshot.as_of` instead, so it
  answers "since when do we have this fund on file" truthfully regardless
  of which import happens to currently win.
- **Mintos**: new `_mintos_core_earliest_known_date()` scans every known
  P2P transaction (investment/repayment/interest/fee/snapshot) for the
  account, preferring a period's `period_start` over `executed_at` (which
  is always the period's *end* — the same distinction already fixed once
  for the interest-income "since" caveat in Decision 3u.47) and falling
  back to `executed_at` only for the live Investments snapshot's own
  single as-of date. `_recompute_mintos_p2p_position` still always shows
  the *latest* snapshot's value (unchanged), but now sets `opened_at` from
  this earliest-known helper instead.

Both fixes are purely additive to existing behavior: the value shown
(`broker_market_value`) and the freshness/import-order semantics
(which import wins) are completely unchanged — verified by the full
existing test suite passing unmodified. Two new regression tests added
(`test_a_fresh_live_snapshot_does_not_reset_since_to_today` for Mintos,
`test_a_fresh_synthese_does_not_reset_since_to_today` for Amundi), each
importing an old dated statement then a "today"-dated live snapshot and
asserting the value updates while `opened_at` stays anchored to the old
date. 952 backend tests passing (950 + 2 new).

**Live-verified against the real portfolio** after re-importing all
Amundi PDFs/Synthese and the Mintos Investments export against the fixed
backend: FONDS MONETAIRE PEG now shows "Depuis" 12/31/2023 (was
09/08/2026), Mintos Core P2P shows 04/01/2024 (was 09/08/2026, now
matching its real, previously-established inception date exactly),
the company-shareholding fund shows 12/31/2025 (an improvement, though
not as far back as 2023 — see the caveat below). Confirmed live
in-browser, not just via the API.

**Known, disclosed limitation, not fixed here**: FONDS RETRAITE PERCO (Amundi
PERCO) still shows today, because — as already found and documented in
Decision 3u.48 — its name differs between Amundi's own two export
formats ("FONDS RETRAITE PERCO SOLIDAIRE" in the PDF vs "FONDS RETRAITE PERCO" in the Synthese
export), so its snapshot history is split across two different
`broker_symbol`s and the "earliest" query only sees the Synthese side.
Not papered over with fuzzy name matching, for the same reason given in
3u.48: a coincidental name/quantity match between two actually-different
funds would be worse than an honest "today" (which at least isn't
silently wrong in a way nothing flags). If this class of naming-drift
bug recurs for a third fund or a different broker, it may be worth a
deliberate, explicitly-scoped alias mechanism rather than fixing it
piecemeal per fund.

## Decision 3u.50 — Declared valuations get their own freshness signal, distinct from "no value" (2026-09-08)

**Context, and a correction to Decision 3u.42's own numbers.** 3u.42
fixed a real bug — a P2P/Amundi position's whole value was excluded from
every total whenever its P&L was unknown — and, at the time, reported
Mintos Core P2P's value as stale (from a 2025-07-01→09-30
quarterly PDF, a year old) and flagged Amundi's total as "probably
the same staleness issue." Between that decision and this one, Decision
3u.49 had the user re-import a live Mintos "Investments" export and
fresh Amundi Synthese/PDF statements the same day (2026-09-08) — so as
of *this* entry, both Mintos Core P2P and Amundi PEG+PERCO
combined match the real, current site values the
user reported directly. The specific "stale value"
example throughout 3u.42/3u.46 is therefore historical, not the
live state — recorded here so a future reader doesn't chase a staleness
that has already been fixed by a re-import.

**The problem that re-importing doesn't fix.** Even a correctly-included,
currently-accurate value has no notion of *how fresh it is* anywhere in
the app. Mintos and Amundi don't publish live market quotes — Mintos
updates only when a new statement/export is imported, Amundi only on its
annual PDF plus occasional live Synthese snapshots — yet
`Instrument.not_priceable_reason` being set made both `_price_status()`
and the Data Health console treat them identically to a CFD or a
corporate-action residual: "not_priceable," full stop, no notion of a
date at all. The day the user re-imports a fresh statement and the day
before the *next* one is overdue look exactly the same in the UI. That's
a real, distinct problem from the one 3u.42 fixed, and conflating the
two — as if "reimport occasionally" were the whole story — would have
left the app with no way to ever tell the user a re-import is actually
due again.

**Decision.** A position's value and its P&L/PRU already had separate
handling (3u.39/3u.42/3u.44); now a position's value and *how it was
priced* get the same separation. Every value is either a live/cached
market quote (freshness already covered by `_price_status`'s
`FRESH_WINDOW_DAYS`) or a source-declared valuation with its own as-of
date and its own expected update cadence — never silently treated as
either "the same as a live quote" or "no value at all."

```text
Known value, live/cached market quote  → existing fresh/stale handling, unchanged
Known value, declared by its source    → new: fresh/stale against that
                                           source's own cadence
No known value                         → excluded, unchanged (3u.42)
```

The total-inclusion rule from 3u.42 is explicitly preserved, not
reopened: a stale declared valuation is still fully counted in
`market_value` — staleness is a caveat on top, never a new reason to
exclude a known value.

**Implementation.**
- `Position.value_as_of` (nullable `Date`, migration `0f34b2035767`,
  chained after 3u.48's `1be94478a200`) — the date *this* position's
  value was declared, set once at import time: `_recompute_mintos_p2p_position`
  now stores the winning `P2P_SNAPSHOT` transaction's own `executed_at`
  date; `_persist_amundi_export`'s fund loop now stores the winning
  import's own `parsed.as_of` (both `app/ingest/service.py`). Deliberately
  not `opened_at`, which already answers a different question ("since
  held," Decision 3u.49) — reusing one field for both was exactly the bug
  3u.49 fixed once; this doesn't repeat it with a new field.
- `app/messages.py::ValuationNote` (`DECLARED_FRESH`/`DECLARED_STALE`,
  `{provider, date}`), the same language-neutral `{code, params}` shape as
  `PerformanceNote`. `routers/portfolio.py::_declared_valuation_note`
  computes it from `Instrument.not_priceable_reason` (only
  `"p2p_aggregate"` and `"employee_savings_fund"` qualify — a CFD or
  corporate-action residual with no `value_as_of` of its own is untouched)
  against `DECLARED_VALUE_FRESHNESS_DAYS` — 100 days for Mintos (quarterly
  cadence), 400 for Amundi (annual cadence, wider on purpose so an
  Amundi value doesn't get flagged on the same clock as Mintos's).
  Exposed as `PositionOut.valuation_note`.
- `PortfolioTotals.has_stale_declared_valuations` — computed in
  `_build_portfolio_out` from the same per-position notes, not from
  `_aggregate`/`_compute_totals`, which stay completely untouched by this
  decision (verified: existing P&L/value aggregation tests all still pass
  unmodified).
- Data Health (`get_data_health`) gets a new `declared_stale` category,
  checked between `price_error` and `not_priceable`: a stale declared
  valuation is now its own actionable category (detail = the as-of date),
  a *fresh* one isn't flagged at all (same posture as a fresh market
  quote — "not_priceable" no longer means "problem" for these two reasons
  once a usable declared value exists).
- Frontend: `PriceStatusBadge` gets an optional `valuationNote` prop that
  overrides the generic 🚫 with a 🗓 icon (colored via the existing
  `price-status-fresh`/`-stale` classes) and the translated caveat as its
  tooltip; the value cell's tooltip in `PositionsTable` shows the same
  text; `DataHealthPanel` renders the new category; `Portfolio.tsx` shows
  a total-level warning banner when `has_stale_declared_valuations` is
  true. 5 new i18n keys × 3 locales (`valuation.declaredFresh/Stale`,
  `dataHealth.declaredSince`, `dataHealth.kind.declaredStale`,
  `totals.staleDeclaredValuations`).
- A one-off backfill (not part of the app) populated `value_as_of` for the
  4 currently-held Mintos/Amundi positions directly from data already on
  file (`AmundiFundSnapshot.as_of`, the latest `P2P_SNAPSHOT` transaction)
  so the feature has real data from the moment it ships, instead of
  reading as "unknown" until the next import. Backed up the live database
  (`backups/stock_analyst_20260908T152453516711Z.db`) before running the
  migration, per standing practice for schema changes against real data.

7 new tests (`TestDeclaredValuationFreshness`/`TestDeclaredValuationBucket`
in `test_api.py`/`test_data_health_api.py`, plus `value_as_of` assertions
added to the existing Mintos/Amundi import persistence tests) — full
backend suite: 959 passed (952 + 7). Frontend `tsc -b` clean, `oxlint`
clean (same two pre-existing warnings only).

**Live-verified against the real portfolio**, not just the test suite:
after the backfill, all four Mintos/Amundi positions read
`valuation.declaredFresh` (today's date) and Data Health shows zero
categories, matching their actual just-reimported state. To confirm the
stale path renders correctly too, temporarily set Mintos Core P2P's
`value_as_of` back to 2025-09-30 (its old value) directly in the live DB,
confirmed in-browser: the 🗓 badge switched to `price-status-stale` with
the correct tooltip, Data Health showed "1 old declared valuation," and
the total banner appeared — then restored `value_as_of` to 2026-09-08
and re-confirmed Data Health and the banner both went back to clean.
Portfolio total unchanged throughout, `excluded_positions: 0`.

## Bug 3u.51 — The "By account" table gave Mintos Core P2P no context for its bare "—" cells (2026-09-08)

User-caught, same day as 3u.50, from a screenshot of the "By account"
table: every Amundi row carries a `*` on Invested/Unrealised/Perf. with a
footnote explaining the approximate-gain caveat (3u.47), but the Mintos
Core P2P row showed bare "—" in those same columns with nothing at all —
no marker, no footnote, no way to tell "unknown by design" apart from
"looks broken."

**Cause.** `AccountTotals.performance_note` — the field driving that
footnote — is genuinely `None` for this account: ~~no
`import_mintos_transactions_file` (interest-income) run has ever
happened for it, so there is no P&L caveat to show, unlike Amundi which
always carries one~~ — **wrong, corrected in Bug 3u.52 below**: the
import *had* run and correctly computed a real gain; a separate bug
silently wiped it back to `None` on the very next value-only re-import.
At the time this entry was written, `broker_net_pl` was live-checked and
found `None`, and that was taken at face value as "never computed" rather
than investigated further — the right instinct (check the real data) 3u.50/
3u.51 both call out here, applied one level too shallow. This paragraph is
left as originally written, struck through rather than rewritten, so the
mistaken shortcut is visible rather than quietly smoothed over. 3u.50 added
`Position.value_as_of`/`valuation_note`
lower down (the position row's 🗓 badge, the position table's value
tooltip, the global total banner) but never plumbed it up to
`AccountTotals`, the one place this specific account's summary lives.
The gap was real, not cosmetic: an account whose *only* explanatory note
is "this value is a declared statement figure" (true for Mintos on this
data) had no path to show that note at all.

**Fix.** `AccountTotals` gets a new `valuation_note` field, independent
of `performance_note` — an account can have either, both (an Amundi
account: approximate gain *and* a declared value), or neither.
`_compute_account_totals` computes it the same way `_build_portfolio_out`
already does per-position (`_declared_valuation_note`), picking
`DECLARED_STALE` over `DECLARED_FRESH` across the account's positions
when both occur (mirrors the existing `AMUNDI_APPROXIMATE_GAIN`-wins
priority for `performance_note`). Frontend: the Value cell gets its own
`†` marker (distinct from `performance_note`'s `*`, since they're
independent caveats that can both apply to the same row) with the note
as its tooltip; the footnote list below the table now shows a bullet per
note per account, valuation note first, so Amundi accounts can show two
bullets and Mintos now shows one instead of none.

2 new tests (`test_account_totals_carry_the_valuation_note_independently_of_performance_note`,
`test_account_valuation_note_prefers_stale_over_fresh_across_its_positions`
in `TestDeclaredValuationFreshness`, `tests/test_api.py`) — full backend
suite: 961 passed (959 + 2). Frontend `tsc -b` clean. **Live-verified**:
the real "By account" table now shows the correct value with a `†`
marker for Mintos Core P2P, with a footnote reading "Mintos Core P2P † — Value declared by Mintos as
of 2026-09-08 — the latest imported statement, within the expected
window for this kind of source," and Amundi PEG/PERCO each show both
their existing `*` performance footnote and the new `†` valuation one.

## Bug 3u.52 — Mintos Core P2P's real, already-computed gain was silently wiped by a later value-only re-import (2026-09-08)

User pushed back directly on Bug 3u.51's framing: "tu veux dire qu'il n'y
a pas de moyen de calculer les performances? C'est faux, on peut se
baser sur toutes les données que j'ai partagées" — correctly. Tracing the
real database rather than trusting the earlier live-check: the account
*did* have a computed gain at one point. Full history of
`Mintos Core P2P`'s `ImportBatch`es, in order:

```text
18  08:46  Investments-08-09-2026.xlsx        → position created, net_pl = None
20  10:20  20260908-account-statement.csv     → net_pl = [montant] (this file's own window)
23  10:48  20260908-account-statement.csv     → re-import, no-op (dedup)
33  12:08  Investments-08-09-2026.xlsx        → net_pl wiped back to None  ← the bug
```

**Cause.** `_recompute_mintos_p2p_position()` (`app/ingest/service.py`,
called by both `import_mintos_file` — the quarterly PDF — and
`import_mintos_investments_file` — the live snapshot) unconditionally
`DELETE`s the account's `Position` row and re-`INSERT`s a fresh one with
only the fields *this* function knows about: quantity, `avg_price`,
`broker_market_value`, `opened_at`, `value_as_of`. `broker_gross_pl`/
`broker_net_pl`/`broker_net_pl_pct`/`performance_note` — set separately by
`import_mintos_transactions_file` (Decision 3u.47), which updates the
existing row *in place* rather than replacing it — were never part of
this function's own field list, so the fresh `INSERT` simply left them at
their column default: `None`. Re-importing batch 33 (a plain re-upload of
the same Investments file, done after the transactions CSV) blew away
the real gain batch 20 had just computed, with nothing anywhere
signalling that anything had been lost — the account went from "real gain
known" to "no P&L known" silently, indistinguishable in the UI from
"never computed."

This is the same shape of bug as 3u.42/3u.46/3u.49: two independent
pieces of information (declared *value*, and a separately-derived *P&L*)
sharing one storage row that gets wholesale-replaced by whichever import
runs last, with only the replacing import's own concerns preserved.

**Fix.** `_recompute_mintos_p2p_position()` now reads the existing
Position (if any) before deleting it, and carries `broker_gross_pl`/
`broker_net_pl`/`broker_net_pl_pct`/`performance_note` forward into the
replacement row untouched. This is not a recomputation — it's exactly
"don't destroy a value this function was never responsible for in the
first place." A subsequent `import_mintos_transactions_file` run still
overwrites these fields with its own fresh total, same as before; only
the *destructive* side effect of a value-only re-import is removed.

New test `TestGainSurvivesALaterValueOnlyImport` (`tests/
test_mintos_transactions_import.py`) reproduces the exact sequence: import
the transactions CSV (a non-zero gain), then re-import the Investments
snapshot, assert the gain and `performance_note` survive unchanged and
`broker_market_value` still updates normally. Full backend suite: 962
passed (961 + 1).

**Live-verified and repaired**: re-ran `import_mintos_transactions_file`
against the real database with the same parsed figures as the original
correct import (real income, real cost, period 2025-01-01 →
2026-09-08) — idempotent by design, so this replayed the exact production
code path rather than hand-computing a number to write in. The live
position now correctly shows a real `broker_net_pl`, `broker_net_pl_pct`,
`performance_note` (since 2024-04-01). Global portfolio unrealised result
rose accordingly (exactly the restored gain). Confirmed in-browser: the
"By account" table now shows Mintos Core P2P with both its `†` (declared
value) and `*` (interest-income) footnotes, real Investi/Latent amounts
and performance.

**Lesson, stated plainly so it doesn't recur**: a live value of `None`
proves "not currently set," never "never computed" — the earlier entry
(3u.51) stopped at the first explanation that fit the symptom instead of
checking the account's actual import/transaction history first. The
`ImportBatch` table already makes that history fully reconstructable
(as done here); it should be the first thing checked, not skipped,
whenever a figure that ought to be known instead reads as unknown.

## Step 3u.53 — Confirm before deleting a position (2026-09-08)

User-requested: "quand on supprime un titre on voudrait un popup qui nous
demande si on est sûr" — the Portfolio positions table's "Delete" button
called `DELETE /api/portfolio/positions/{id}` on a single click, no
confirmation at all, for an action that also removes the position's open
`Lot` (irreversible — no undo, no trash). `PositionsTable.tsx`'s delete
button now wraps the call in `window.confirm(t('table.deleteConfirm',
{symbol}))`, naming the actual instrument rather than a generic "are you
sure" — only calls `onDelete` when confirmed. Scoped to positions only
(as asked); the same unconfirmed-delete pattern exists on Watchlist,
Screener, Corporate Actions and Allocation Targets too, left untouched —
not part of this request.

**A real incident during verification, disclosed in full.** Testing the
new confirm dialog in the live browser (a `window.confirm` override +
programmatic button click, meant to target only a disposable
`ZZTEST-DELETE-CONFIRM` manual test position) resulted in a real held
position — 1 share of ASTS.US (AST SpaceMobile), `Position` id 100,
`Lot` id 94 — being deleted from the actual database. The exact
mechanism was never conclusively identified; the confirm-guard code
itself is correct and nothing else in the app runs in the background
that could explain it independently. Caught only because a full
positions/lots/transactions/instruments id diff was run against the
same-day pre-migration backup
(`backups/stock_analyst_20260908T152453516711Z.db`) rather than only
checking the test position itself — a narrower check would have missed
it. **Fully restored**: the exact `Position`/`Lot` rows re-inserted with
identical field values and original ids from the backup; a second full
diff across all four tables confirmed an exact match (0 rows missing, 0
extra) before finishing. The one leftover artifact (the orphaned
`ZZTEST-DELETE-CONFIRM` `Instrument` row — deleting a position never
deletes its instrument) was removed via the ordinary
`DELETE /instruments/{id}` endpoint.

**Lesson**: never verify a destructive action against this app's real
database by clicking it live — even "just testing the popup." Any future
live check of a delete/destructive UI change uses a disposable position
only, and diffs every table's id set against a backup taken immediately
before, not just the one row under test.

Frontend `tsc -b`/`oxlint` clean (same two pre-existing warnings). 1 new
i18n key (`table.deleteConfirm`) × 3 locales.

## Step 3u.54 — Price filter on the Hidden gems page (2026-09-08)

User-requested: "dans les pépites on n'a toujours pas de filtre pour par
exemple pouvoir afficher les actions qui coûtent sous un certain seuil."
Neither `ScreenerTable` (the hand-picked "Candidats" list) nor
`DiscoveryPanel` (the S&P 500 universe scan and the two Finviz presets)
had any numeric filter at all — only `ScreenerTable` had a text search.
Added a `filters.priceMin`/`filters.priceMax` pair (same "From/To" range
convention already used for Transactions' date filter) to both:
`ScreenerTable` filters its own `items` alongside the existing search;
`DiscoveryPanel` gets one shared min/max control applied to all three of
its candidate lists (S&P 500 ranking, Finviz insider-buys, Finviz
oversold) — one filter for the whole "Découverte" section rather than
three separate ones, since they're the same kind of list. A candidate
with no known price (`current_price === null`) is excluded whenever a
bound is set, never shown as a false match — consistent with how an
unknown value is excluded rather than guessed everywhere else in this
app (Decision 3u.42 and others). No backend change: filtering is
client-side over data already fetched.

Live-verified: set max price to 20 on the real Candidats list — DYN.US
(24.28), AMCR.US (45.15), APA.US (42.77) and ARE.US (52.65) dropped out,
FUSB.US (16.48) and BIVI.US (2.00) remained; clearing the field restored
the full list. Frontend `tsc -b`/`oxlint` clean. 2 new i18n keys
(`filters.priceMin`/`filters.priceMax`) × 3 locales.

## Step 3u.55 — One shared price filter for the whole Hidden gems page (2026-09-08)

Immediate follow-up, user-requested: "il y a un moyen qu'on puisse
filtrer tous les titres d'un coup?" — 3u.54 gave `ScreenerTable` its own
min/max fields and `DiscoveryPanel` a second, separate pair covering its
own three lists, so filtering the whole page meant setting the same
bound twice. Lifted `priceMin`/`priceMax` state from both components up
to `Screener.tsx` (the page both are mounted in) and turned them into
controlled props on each — `ScreenerTable`'s and `DiscoveryPanel`'s
existing filtering logic (`_declared_valuation_note`-style "unknown price
excluded, not guessed" rule from 3u.54, untouched) now just reads the
bounds instead of owning them. One "Price filter" card at the top of the
page, above "Add a candidate," with a hint naming what it covers
("Candidates, the S&P 500 universe and Finviz scans") so the reach of a
single control isn't left to guessing.

Live-verified: set max price to 20 once at the top — Candidats dropped to
FUSB.US/BIVI.US (same as 3u.54) *and*, simultaneously, the S&P 500 list
dropped from 20 to 3 rows (all ≤ 3.57€), with no second filter to set;
clearing the one field restored both lists (20 S&P 500 rows again).
Frontend `tsc -b`/`oxlint` clean. 2 new i18n keys
(`gems.priceFilterTitle`/`gems.priceFilterHint`) × 3 locales; no backend
change.

## Step 3u.56 — Corporate Actions Phase 4's validation gate is met (2026-09-08)

Decision 3u.41 (2026-09-07) set an explicit condition before building Phase
4's frontend: at least one real `verified_cross_source`/
`verified_three_sources` event must come out of a single fresh
`POST /api/corporate-actions/detect/resume` call — not stitched across
two days' quota, which is what the previous attempt had actually been.
That same evening's last resume run only checked 1 instrument
(`candidate_single_source`, no cross-source confirmation) before the
day's Alpha Vantage quota ran out.

User reviewed the corporate-actions backend state today, gave a
prioritized roadmap (see [[stock-analyst-roadmap-2026-09]] item 15 in
memory) naming Corporate Actions Phase 4 as priority 1, and asked to
check this gate cheaply first (`GET .../resume/status` +
`GET .../incomplete`, no quota spent) before spending quota on a real
run — confirmed the gate was still unmet (20 instruments still
incomplete) — then explicitly approved triggering the real resume call.

**Result, a single fresh run, quota freshly reset overnight**:
```text
POST /api/corporate-actions/detect/resume?provider=alpha_vantage&limit=20
checked: 20, rate_limited: 0, failed: 0
no_events: 9, candidate_single_source: 9
verified_cross_source: 16, verified_three_sources: 0, provider_conflict: 0
suspect_ticker_reuse: 0
complete: true, remaining_incomplete: 15 (was 20)
```
No 429, no stopping point — the full 20-instrument batch completed
within Alpha Vantage's per-minute throttle (~4 minutes). **The gate is
massively cleared**: 16 cross-source-confirmed events in one pass, not
just the required one. Spot-checked 10 of the resulting
`CorporateAction` rows directly in the database — each one's
`corroborating_sources` shows Alpha Vantage and Polygon independently
agreeing on the exact same event_date/ratio (e.g. CMG.US 50:1 split on
2024-06-26, BIVI.US three separate reverse splits across 2019/2024/2025,
CRWD.US 4:1 on 2026-07-02) — genuine agreement, not a coincidence of
the classification logic. Zero `provider_conflict`, zero
`suspect_ticker_reuse` — the isolation-window fix from Decision 3u.41
holds up under a real, larger batch.

**Unblocks Phase 4**: per the user's roadmap, next is building the
frontend around these real states (manual resume button showing pending
count/quota cost before the click, per-event trust labels, a
"Couverture automatique" summary) — not started yet, this entry only
records that the go/no-go check passed. 15 instruments remain
incomplete for a future resume run (tomorrow, once quota resets again).

## Step 3u.57 — Corporate Actions Phase 4 frontend (2026-09-08)

User-prioritized (see [[stock-analyst-roadmap-2026-09]] item 15 in
memory) as the single active chantier once 3u.56's validation gate
cleared. Scope: make the multi-source states from Decision 3u.41 visible
— never redesign the underlying detection engine. Strict rule enforced
throughout: **instrument counts and event counts are never conflated** —
one instrument (BIVI.US) can carry several corporate-action events.

**Backend, additive only — no change to `detect_splits`'s own logic:**
- `CoverageSummary`/`compute_coverage_summary()` — a read-only, no-
  provider-calls snapshot (`GET /api/corporate-actions/coverage`):
  eligible/excluded/checked/unchecked instrument counts, plus event
  counts by confidence. Eligible/excluded reuses `detect_splits`'s own
  `_all_tracked_instruments()`/`provider_symbol` split; applied-event
  counts read `CorporateAction.confidence` directly (exact); outstanding
  counts are recomputed by re-running `_merge_events_for_instrument`/
  `_classify_group` — the *same* engine `detect_splits` uses — over
  already-persisted `ProviderCorporateActionCandidate` rows, so this is
  safe to call on every page load.
- `OutstandingCandidate`/`list_outstanding_candidates()` — the detailed
  counterpart (`GET /api/corporate-actions/outstanding`): every still-
  unconfirmed merged event, for a "Candidats à confirmer" list that shows
  an actual amber badge, not just a bare count. Read-only w.r.t. the raw
  per-provider candidate rows — promoting one still goes through the
  pre-existing `POST .../candidates/{id}/promote`, untouched here.

**Two real bugs found and fixed while building this — exactly the kind
this project's "verify against live data" habit exists to catch:**

1. **Crash on a legacy candidate row with no real ratio.** A
   `ProviderCorporateActionCandidate` with `event_type = None` (a
   provider-reported ratio that isn't actually a split, e.g. 1:1 —
   `detect_splits` itself already skips these when building its own
   `observations`, via its `if action_type is not None` guard) made the
   new merge path build a group with no `action_type` at all, 500ing on
   response validation the moment `/outstanding` was first hit for real.
   Fixed by applying the exact same skip `detect_splits` already uses.

2. **Retroactive cross-source agreement was silently stuck as
   "unconfirmed" forever.** `detect_splits` only ever merges observations
   gathered within *one* scan call. If Alpha Vantage confirmed an event on
   one day's run and Polygon confirmed the identical event on a
   *different* day's run (each run seeing only one of the two — e.g. the
   other provider was rate-limited, or the instrument wasn't due for a
   recheck that day), the two observations sat in
   `ProviderCorporateActionCandidate` as genuine 2-source agreement that
   no single scan had ever noticed side by side — a real confirmed event
   permanently misclassified as `candidate_single_source`. Found live: the
   very first real call to the new coverage endpoint showed
   `verified_cross_source` events (NVO.US ×3, NTES.US ×2, DOYU.US, CRM.US)
   sitting in the *outstanding* list — self-contradictory, since
   "verified" and "still needs confirming" can't both be true. Root cause
   confirmed by checking actual scan history, not assumed. Fixed by having
   `list_outstanding_candidates` recompute classification over *every*
   persisted observation regardless of which scan produced it — when a
   group now qualifies as verified but has no matching `CorporateAction`
   yet, it is applied on the spot (the exact write `detect_splits` itself
   would have made, had it seen both observations together), not
   displayed with a contradictory "verified, please confirm" badge.
   **Live-verified and applied against the real database** (backed up
   first: `backups/stock_analyst_20260908T214639141349Z.db`): 7 events
   retroactively promoted from `candidate_single_source` to
   `verified_cross_source` — `verified_cross_source_events` 10 → 17,
   `candidate_single_source_events` 24 → 17, confirmed by re-querying the
   real `CorporateAction` table (each new row's `corroborating_sources`
   shows Alpha Vantage + Polygon independently agreeing). 5 new tests
   covering both bugs plus the intended instrument/event distinction
   (`TestComputeCoverageSummary` in `tests/test_corporate_actions.py`) —
   full backend suite: 967 passed (962 + 5).

**Frontend (`CorporateActionsPanel.tsx`, rewritten, not replaced —
manual-add and the EODHD single-check section kept as-is):**
- "Couverture automatique" now reads the persistent coverage endpoint
  instead of only appearing after a scan, and is multi-source (no more
  "avec FMP" wording) — instrument line, then event lines, always
  labeled as such (never "16 instruments confirmés").
- New "Alpha Vantage" section: `[ Relancer la vérification Alpha
  Vantage ]`, disabled while running or once nothing remains incomplete;
  shows the last run's own summary (checked/verified/candidates/no-
  events) and a distinct rate-limited notice when applicable — never
  triggers EODHD, never re-checks an instrument Alpha Vantage already
  answered (unchanged backend behavior, just newly visible).
- New "Candidats à confirmer" section: every outstanding event with an
  amber `confidence-review` badge (`ConfidenceBadge` component), never
  auto-applied, never presented as definitive.
- Main history table gets a "Confiance" column (`ConfidenceBadge` again —
  blue `confidence-confirmed` for the two auto-applied states, neutral
  gray for manual/manual_promotion) distinct from the existing "Source"
  column; clicking the badge expands a "Vérification" detail row listing
  each corroborating provider's own date/ratio, an explicit "FMP — non
  utilisé dans le calcul de confiance actuellement" line when FMP didn't
  contribute, and "EODHD — non vérifié (source ciblée, à la demande)".
- New CSS: `.tag.confidence-confirmed/-review/-neutral`, reusing the
  existing `--accent`/`--warning`/`--text-muted` tokens already meaning
  the same things elsewhere (`.tag.manual`/`.tag.unresolved`/
  `.tag.neutral`) — no new color introduced, never red (none of these
  states mean something is broken).
- Every backend enum value (`confidence`, `source`) goes through an i18n
  key (`corporateActions.confidence.*`, `corporateActions.source.*`) —
  added `alpha_vantage`/`polygon` source labels, missing until now.

**Scope deliberately not touched**: no promote-from-the-merged-view UI
(promoting a candidate still requires the existing per-provider-row
endpoint — a merged "Candidats à confirmer" row isn't 1:1 with a single
promotable id, and wiring that through was judged out of scope for
"make states visible", not "redesign the promotion flow"); the full
multi-source `/detect` button (all three providers, not just Alpha
Vantage) is kept alongside the new targeted resume button, relabeled
away from "avec FMP" but otherwise unchanged.

**Live-verified in-browser against the real, just-updated database**
(not mocks): coverage showed 50 eligible / 4 excluded / 38 checked / 12
remaining, 17 verified-events / 17 candidate-events / 2 suspect-events —
exactly matching the API. Alpha Vantage section showed "15 instruments
still need checking" and the last batch's real summary (20 checked, 16
cross-source, 9 candidates, 9 no-events — the exact numbers from 3u.56's
run). Candidates list showed real amber-badged single-source rows
(SAN.FR, EL.PA.US, MRVL.US...) and APLD.US correctly labeled "Not
applied — this symbol's history needs a look" rather than lumped in with
the others. Clicked a confirmed badge (CRWD.US, 4:1) in the main table:
expanded to show Alpha Vantage and Polygon both reporting 2026-07-02
4:1 independently, FMP's "not used" line, EODHD's "not checked" line.
Frontend `tsc -b`/`oxlint` clean (same two pre-existing warnings).

## Decision 3u.58 — Data Health v2: per-instrument valuation + corporate-action trust report (2026-09-10)

First chantier off the 2026-09-08/2026-09-10 re-prioritization: the app's
biggest remaining gap was named as *coherence between wealth tracking,
data quality, and beginner comprehension*, and Data Health v2 was picked
as the structural prerequisite for everything after it (a personal
policy page, a portfolio-risk view, a decision journal — none useful if
the user can't first see which values and corporate actions are
trustworthy). v1 (Decision 3u.33/3u.50) only listed *problem* categories
for held positions; v2 replaces it with one row per held instrument,
always shown, carrying two independent signals resolved into a single
overall severity — never make the user reconcile two separate panels to
know whether a number can be trusted.

**Backend, no new tables or migration** — everything was already
computable from existing columns (`Instrument.not_priceable_reason`/
`prices_checked_at`/`verified_provider`/`corporate_actions_checked_at`,
`Position.value_as_of`, `CorporateAction`, `ProviderCorporateActionCandidate`
via the Phase 4 `list_outstanding_candidates`/`list_incomplete_instrument_ids`
helpers). `GET /api/portfolio/data-health`'s response shape was replaced
outright (`DataHealthOut` now `{summary, rows}` instead of
`{total_positions, categories}}`) rather than versioned alongside v1:
single-user local app, one frontend consumer, no reason to carry two
shapes.

- `DataHealthValuationOut`: `kind` (`market_price` | `declared_value` |
  `unavailable`), `source`, `as_of`, `freshness` (`fresh`|`stale`|
  `unknown`) — reuses `_declared_valuation_note`/`_price_status`
  unchanged (Decision 3u.50/3u.33's freshness rules are still the source
  of truth here, just surfaced per-instrument instead of only when
  broken).
- `DataHealthCorporateActionsOut`: `status` (`verified` | `no_events` |
  `candidate_single_source` | `provider_conflict` | `suspect_ticker_reuse`
  | `incomplete_coverage` | `never_checked` | `not_applicable`) +
  `confirmed_events`/`outstanding_events` **event** counts (never read as
  instrument counts — same discipline as `CoverageSummary`, Decision
  3u.41). `not_applicable` whenever the row's valuation isn't
  `market_price` or the instrument has no `provider_symbol` — a
  Mintos/Amundi declared-value position or a still-unresolved symbol
  never gets a corporate-actions verdict, since checking one wouldn't
  mean anything.
- Overall `severity` (`info` | `attention` | `action_required` |
  `not_applicable`) is the more severe of the two signals, ties won by
  valuation (the more fundamental one) — `_combine_severity` in
  `routers/portfolio.py`. `reason`/`recommended_action` travel with
  whichever signal won, so the row never shows an action that doesn't
  match its own severity.
- New `DataHealthSummaryOut` rollup (`info_count`/`attention_count`/
  `action_required_count`/`not_applicable_count`); rows sorted worst-
  first (`action_required`, `attention`, `info`, `not_applicable`), so
  the fix-it console reads top-to-bottom by what matters most.
- 22 new tests (`tests/test_data_health_api.py`, fully rewritten): every
  valuation/corporate-actions state in isolation, the severity-tie-break
  rule both ways, and the full portfolio summary/ordering. Full backend
  suite: 976 passed.

**Frontend (`DataHealthPanel.tsx`, fully rewritten)**: a summary strip
of colored tags (only non-zero buckets shown) above a per-instrument
table (Instrument / Valorisation / Corporate actions / Qualité / Action
utile). New `SeverityBadge` reuses the Phase-4 `ConfidenceBadge` color
convention exactly (`confidence-confirmed` blue for info,
`confidence-review` amber for attention, `confidence-neutral` gray for
not-applicable) plus one new mapping: `action_required` → `.tag.negative`
(red) — the one severity here that means a number may genuinely be
wrong, mirroring `.price-status-error`'s existing use of the same
`--negative` token. Every backend enum goes through an i18n key
(`dataHealth.valuation.kind.*`, `.freshness.*`, `.corporateActions.status.*`,
`.severity.*`, `.action.*`) in all three locales — no raw status string
reaches the UI. Deliberately not built in this first increment (kept as
a next-scoped follow-up if picked up): operational buttons wired to each
`recommended_action` (jump to symbol correction, trigger the Alpha
Vantage resume, open the EODHD mini-form) — this pass is about
*visibility*, matching the roadmap's own "contrat de sortie backend,
pas une refonte de l'interface" framing; `recommended_action` is
descriptive text only for now.

**Live-verified in-browser against the real 40-position portfolio**, in
both English and French (no raw key or enum string rendered in either):
19 info / 21 attention / 0 action_required / 0 not_applicable. Surfaced
a real, previously-invisible gap as a direct byproduct: 11 held
instruments (mostly the French/European names — AF.FR, AI.FR, CAC.FR,
DSY.FR, MC.FR, ORA.FR, TTE.FR...) have **never** been checked by the
corporate-actions scan at all (`corporate_actions_checked_at` is
`None`), not just incompletely covered by Alpha Vantage — a different
and more basic gap than the "15 instruments still incomplete on Alpha
Vantage" figure Decision 3u.41/Step 3u.56 already tracked. Also
confirmed SAN.FR carries a second `suspect_ticker_reuse` event (1999
2:1, in addition to the already-known 2020 case) — real data, not a
bug in this pass's own logic (unchanged from Phase 4's classification
engine, simply not previously surfaced per-instrument). Both are now
visible facts for the user to act on, not something this pass tried to
fix — consistent with Data Health's own charter of showing gaps, not
silently resolving them. `tsc -b`/`oxlint` clean (same two pre-existing
warnings).

## Decision 3u.59 — Personal policy: the user's own decision rules, compared against the portfolio as plain facts (2026-09-10)

Second chantier off the 2026-09-08/2026-09-10 re-prioritization, right
after Data Health v2 (Decision 3u.58): a page where the user makes their
*own* investment rules explicit — objective, horizon, liquidity need,
risk tolerance, personal concentration limits — and the app compares the
current portfolio against them, stated as a fact, never a suggestion.
Explicit guardrails from the user's own spec, carried through the whole
design: no forced "prudent/balanced/dynamic" profile, no "your portfolio
is/isn't suited" verdict, no instrument recommendation, no PEA/CTO tax
calculation, no unnecessary personal data (no exact income, full net
worth, family situation). Placed on the Portfolio page next to
`AllocationTargets`, not in Settings — this is portfolio strategy, not
data administration.

**Backend, one new migration** (`0f3df0ede51c`, additive-only, two new
tables, nothing existing touched): `PersonalPolicy` (singleton, id=1,
same pattern as `AppMetadata`) — objective (three independent booleans,
never a single forced label, plus a free-text note), horizon (a
qualitative bucket and/or a target date, independent of each other),
liquidity need (amount/date/note), risk tolerance (free text — no
imposed scale) and a loss-capacity percentage. Every field optional; an
incomplete policy is a normal, permanent state, not a form to push to
completion.

`PersonalPolicyLimit` — one row per personal concentration rule:
`dimension` (`line` | `sector` | `country` | `currency` | `category` |
`declared_valuation`) + `target` (the specific value being limited, e.g.
`target="Technology"` for `dimension="sector"`; `None` for `line` —
applies uniformly to every position — and `declared_valuation` — a fixed
pseudo-dimension covering Mintos/Amundi-style declared valuations as a
whole) + `min_pct`/`max_pct` (either or both). `(dimension, target)`
unique at the DB level, plus an explicit 409 in the router for the
`target=None` cases SQLite's own unique index wouldn't catch (NULLs
never collide with each other there).

`GET/PUT /api/portfolio/policy`, `GET/POST/DELETE /api/portfolio/policy/limits`,
`GET /api/portfolio/policy/gaps` (`routers/portfolio.py`). `PUT` replaces
the whole policy in one call (the edit form always submits every field —
no partial-update ambiguity). `POST .../limits` validates via
`PersonalPolicyLimitIn.check_shape`: at least one bound, `min_pct <=
max_pct`, and target required/forbidden exactly per dimension.

`GET .../gaps` is the comparison engine, and — per the user's explicit
step 1 ("auditer d'abord l'emplacement actuel de l'allocation cible,
des poids, des catégories") — it reuses rather than reinvents:
`get_breakdown`'s and `_current_allocation_values`'s near-identical
"group market value by one Instrument attribute" loops were unified into
one `_weight_buckets(positions, figures, attribute)` helper (plus a new
shared `_positions_figures_and_total`), so `/breakdown`, `/allocation`
and `/policy/gaps` now all compute from the same code path — three
independent copies of that loop became one. Only breaches are returned
(same "nothing to report when nothing needs a look" posture as
`/attention`); a `line` breach is reported per breaching instrument
(target = its own symbol), every other dimension per configured
limit. 17 new tests (`tests/test_personal_policy_api.py`) covering the
policy CRUD, every validation rule, and a gap in each of the six
dimensions (including a real declared-valuation-weight breach against a
seeded Mintos-shaped position). Full backend suite: **993 passed**.

**Frontend (`PersonalPolicyPanel.tsx`, new)**: a consultation view (four
fact blocks: Objectif/Horizon/Liquidité/Tolérance, `<dl
className="position-detail-facts">` — the same grid-definition-list class
`PositionDetailRow.tsx` already uses, reused rather than adding a
near-duplicate) with a "Modifier ma politique" button opening a full
edit form (`PUT`, whole-policy replace); a "Limites personnelles" table
+ add-row mini-form (dimension select, conditional target input, min/max
— mirrors `AllocationTargets.tsx`'s inline-edit-row pattern); a "gaps"
list below it, shown only once at least one limit exists, prefixed with
one fixed disclaimer line ("Ces constats ne constituent pas une
suggestion d'achat ou de vente") rather than repeating it per row.
Reuses `allocation.state.under`/`.over` i18n keys for the gap state tag
(same concept, no new keys needed). All new i18n in fr/en/pl.

**Live-verified in-browser against the real portfolio**: filled and saved
a real policy (objective, horizon, liquidity, risk note, loss capacity)
— consultation view rendered every field correctly. Added a `currency`/
`USD` limit at 20%: real USD exposure is 17.13% (`GET
/breakdown?by=currency` confirms), correctly reported as "toutes vos
limites sont respectées" — not a bug, a real and mildly surprising fact
about this portfolio's actual currency mix (dominated by EUR-denominated
PEA/Amundi/Mintos holdings, not the US-heavy My Trades account alone).
Lowered the same limit to 10% to confirm the breach path: rendered
"Devise — USD : 17,13 % (Surpondéré votre limite : ≤ 10 %)" correctly.
Test data cleaned up afterward (limit deleted, policy fields reset to
null) so the user finds a genuinely empty policy to fill in themselves,
not synthetic verification data. `tsc -b`/`oxlint` clean (same two
pre-existing warnings).

**Deliberately not built in this pass, per the user's own explicit
ordering**: linking this policy to a future full portfolio-risk view
(sector/country/currency concentration beyond what a configured limit
already checks, liquidity-by-asset-class, valuation-risk breakdown,
historical drawdown) — stays a separate, later chantier once this
model has stabilized in real use. A decision journal (per-trade
rationale/thesis/review-date log) is the chantier after that.

## Decision 3u.60 — Annual tax-year reconciliation: a rapprochement aid, deliberately not a tax calculator (2026-09-10)

The user asked for tax-declaration help ("calculer les taxes pour les
déclarations"), explicitly accepting the legal risk after this project's
own standing rule against it (roadmap memory, and this session's earlier
"pas de calcul fiscal PEA/CTO prétendument définitif" guardrail) was
raised. A detailed follow-up spec reframed the goal correctly before any
code was written: not a tax calculator, a **reconciliation assistant** —
collect, classify, explain, and flag gaps against official documents;
never announce a "final tax" or apply a rate. Naming follows this exactly:
"Préparation fiscale" / "Synthèse fiscale à rapprocher", never "Calcul
d'impôt".

**A real, load-bearing fact surfaced before writing anything**, precisely
because scoping questions were asked first rather than assumed: this
portfolio's PEA has **zero taxable activity this year, regardless of its
age** — under French law, dividends and gains stay inside a PEA/PEG/PERCO
wrapper untaxed until an actual withdrawal, and the real transaction data
shows no `WITHDRAWAL` row for PEA or either Amundi account this year. A
naive design that just summed "PEA dividends" as taxable income would have
been factually wrong from the first row shipped.

**v1 scope, deliberately narrow** (`app/tax/service.py`,
`routers/tax.py`, `GET /api/tax/summary?year=`, `GET /api/tax/years`, `GET
/api/tax/summary.csv`): one `TaxEnvelopeSummary` per account with any
transaction in the selected calendar year — plain sums of already-imported
transactions, **no tax rate ever applied, no liability ever computed**.
`_classify_envelope` maps an account name to `cto | pea | p2p |
employee_savings` (a heuristic on the account string, since no structured
"wrapper type" field exists on `Transaction` yet). Dividends/withholding
are **not recomputed** — `dividends/service.py::dividend_summary` (Decision
3u.28) is reused as-is, specifically to avoid silently reintroducing the
exact bug that module's own docstring documents having found and fixed
live (French FTT/UK stamp duty sharing `TxType.TAX` with genuine dividend
withholding). Every other figure (interest, realized gains/losses, fees,
deposits, withdrawals) is a direct sum by `TxType`, split into gains vs.
losses shown *separately*, never netted.

**Explicitly never computed, by design**: a final PFU/barème tax figure;
any Mintos-ETF plus-value (real `SELL` transactions exist with no
`CLOSED_TRADE` counterpart — flagged `taxPrep.unmatchedSales`, "rapprochement
des lots (FIFO) non disponible", never estimated); any consequence of a
detected PEA/employee-savings withdrawal beyond flagging it for the user's
own or an advisor's review (`taxPrep.withdrawalDetected` — plan age and
exit conditions are not modeled). `Instrument`-less `OTHER` transactions
(Amundi's own annual-statement aggregate lines — "versements_volontaires",
"abondement_net"...) are shown verbatim as `other_flows`, never bucketed
into a guessed tax category, and never counted as taxable activity.

**One real UX bug found and fixed via live verification, not by the test
suite**: an account with *only* contribution-side `OTHER` flows (Amundi PEG
in a year with no dividend/interest/gain activity) initially showed two
notes that said the same thing in different words — "aucun retrait
importé" and "aucune opération pertinente" both firing at once. Fixed by
suppressing the generic `NOT_APPLICABLE` note whenever a more specific
PEA/employee-savings note already explains the same conclusion.

21 new tests (`tests/test_tax_service.py`) — envelope classification, each
figure computed correctly, the PEA-no-withdrawal vs. PEA-withdrawal
branches, the Mintos-ETF unmatched-sales case, the CTO account with both
raw `SELL` *and* `CLOSED_TRADE` never double-counting the same sale as
"unmatched", year filtering, and an API-level test asserting the words
"rate"/"tax_due"/"pfu" never appear anywhere in a response. Full backend
suite: **1014 passed**.

**Frontend**: new `TaxPrep.tsx` page (`/tax-prep`, new top-level nav
entry), a year picker, one card per envelope with a non-dismissible
disclaimer always shown above the data, and a CSV export
(`preparation_fiscale_{year}.csv`) — matching the roadmap's step 6 ahead
of schedule since it cost nothing extra once the summary endpoint existed.
Live-verified against the real portfolio across four real tax years
(2023–2026): correctly showed a genuine 5-unmatched-sale Mintos ETF year,
a contribution-only Amundi year, and the always-true "no PEA withdrawal"
state. `tsc -b`/`oxlint` clean (same two pre-existing warnings).

**Deliberately not built in this v1, per the user's own "ordre de mise en
œuvre"**: the versioned `TaxRuleSet`/`TaxClassification` model (steps 2–3
of their spec — no PFU rate is hardcoded anywhere yet, so there is nothing
to version), reconciliation against an imported IFU/Mintos tax-report
document (steps 4–5), and the FIFO lot-matching engine for Mintos ETF
(step 7, explicitly gated on validating its output against real Mintos
tax reports across several years before ever showing a number). All
remain named, scoped follow-ups, not started.

## Decision 3u.61 — Moved off the daily-driver laptop onto a dedicated host, and stopped running the servers by hand (2026-09-11/12)

The whole project (repo incl. `.git`, `data/stock_analyst.db`, both
`.env` files) moved from this Kali laptop to a dedicated always-on
host — done as part of a broader move of the Hermes gateway to the same
host, since the `*/15 * * * * export_for_hermes.py` cron (Hermes'
`portfolio-analyst` skill's only data source) couples the two projects:
without this app's backend answering on `127.0.0.1:8000`, that skill has
nothing to read. `Stock-Analyst`'s own git remote — `github.com/Jacob-dot-bit/Stock-Analyst`,
public, unlike Hermes' own repo — was already current, so no separate
transfer step was needed for the code itself beyond a
`git clone` on the new host — the manual copy this session actually did
(`rsync`, since a stale local commit was still possible) doubled as the
verification that the remote truly was in sync (`git status` came back
clean).

**Real bug found while setting up the frontend on the new host — not
present on the old laptop, so never seen before**: `npm install` succeeds
(with `npm WARN EBADENGINE` noise), but `npm run dev` crashes immediately
with `SyntaxError: The requested module 'node:util' does not provide an
export named 'styleText'`. Cause: Debian 12's packaged `nodejs` is
v18.20.4, while Vite 8 and `react-router@7` require Node ≥20.19 or
≥22.12 — `styleText` only exists from Node 20.12 on. The old laptop
happened to already have a newer Node installed for unrelated reasons,
so this had never been exercised. Fixed with `nvm` (Node 22) rather than
touching the system package, to avoid clobbering anything else on the
host that might expect the distro's own Node.

**Operational fragility fixed, not just relocated**: on the old laptop,
both the backend (`uvicorn --reload`) and the frontend (`vite`) were
processes started by hand and left running in a terminal — surviving
purely because that laptop was rarely rebooted. Reproducing that same
pattern with `nohup` on the new host would have silently broken the
15-minute export cron on the very first reboot (`Connection refused`,
looping forever, nothing surfaced anywhere). Replaced with two `systemd`
units (`stock-analyst-backend.service`, `stock-analyst-frontend.service`,
`Restart=on-failure`) instead — verified end to end after an actual
kernel-update reboot of the host: both came back on their own, and the
export log kept writing successful entries straight through it with no
manual intervention. Unit definitions and the exact setup steps live in
the Hermes repo's `MIGRATION.md` (this project's own repo doesn't carry
host-provisioning concerns), since the same steps apply regardless of
which project's servers are being made persistent on that host.

**Not affected, confirmed rather than assumed**: `vite.config.ts`'s
loopback-only default (`VITE_DEV_HOST_ALL`) still applies unchanged on
the new host — the frontend service sets that env var explicitly (needed
here since the new host has no display of its own, browsed to only from
another machine), the backend stays on `127.0.0.1` exactly as documented
in `scripts/export_for_hermes.py`'s own module docstring.

## Step 3u.62 — Discovery verdict filter, alongside the existing price filter (2026-09-15)

Roadmap item 14 (raised in passing at the end of the corporate-actions
Phase 3 discussion, 2026-09-07): filter Discovery candidates by verdict
in addition to the existing price range — the user's own example, a
"buy" verdict under a given price threshold.

**Scoped to `DiscoveryPanel` only, not lifted to `Screener.tsx`**: unlike
the shared price filter (Decision 3u.54/3u.55), `recommendation` only
exists on `DiscoveryCandidateOut` — `ScreenerTable`'s hand-picked
candidates have no verdict field to filter by, so a shared control at
the page level would silently do nothing for that list. Kept as local
state inside `DiscoveryPanel`, with its own hint explicitly saying it
covers the S&P 500 ranking and Finviz scans below it, not the candidates
list above.

Four toggle buttons (All/Buy/Hold/Sell, same pattern as the existing
`rankBy` toggle), ANDed with the price filter already in effect. Same
"unknown excluded, never a false match" discipline as the price filter:
a candidate with `recommendation: null` (no composite score to derive
one from) is excluded whenever a specific verdict is selected, not shown
under "All" filtering logic by coincidence.

No backend change — filtering is client-side over data already fetched,
same as the price filter. Reused `filters.all` (already used by
`PositionsTable`) rather than adding a new "All" key. `tsc -b`/`oxlint`
clean (same two pre-existing warnings); all three i18n catalogues still
at parity (752 keys each, verified by direct comparison).

## Decision 3u.63 — Discovery's data-quality gate, the "simplest cut" of the fuller Pépites-filters vision (2026-09-15)

Same day, immediate follow-up: this chantier had been scoped much further
in an earlier session (see memory `stock-analyst-roadmap-2026-09.md` item
5 of the 2026-09-08 re-prioritization) into a dozen filter dimensions
(market/country, sector, instrument type, cap, valuation/growth data
availability, data quality, analysis score, dividend yield, debt, minimum
history, fresh-data-only) plus an explicit "not a recommendation"
disclaimer — with the user's own suggested starting point: a single
toggle for "instruments avec données suffisamment complètes ET cours
récent ET sans problème de mapping ET sans corporate action en attente",
data-quality gating before adding financial criteria. Built exactly that
starting slice, not the full dozen dimensions.

**Real layering wart found and fixed while wiring this up**: `_price_status`
(and its `FRESH_WINDOW_DAYS` constant) lived in `routers/portfolio.py`,
already cross-imported from there by `routers/screener.py` and
`routers/watchlist.py` — a router importing from another router, backwards
layering that happened to work only because Python doesn't enforce module
boundaries. Adding a third cross-import for Discovery was the point where
this stopped being tolerable. Moved both to `prices/service.py` (the
natural home — a pure function of `Instrument`, no router dependencies)
as public `price_status`/`FRESH_WINDOW_DAYS`, re-exported into
`portfolio.py` under the same `_price_status` alias so every existing
call site and comment reference stays valid. No behavior change — full
suite still 1015 passing (3 new tests) after the move.

**The four conditions collapse into three checks, not four**: "cours
récent" and "sans problème de mapping" are both already folded into a
single `price_status == 'fresh'` check (`price_status` returns
`'unmapped'` before it ever gets to evaluate freshness) — reusing this
one existing signal instead of re-deriving mapping/freshness separately
avoided a second implementation of a rule that already exists. "Données
suffisamment complètes" is `composite_score is not None` (already on
`DiscoveryCandidateOut`, no backend work). "Sans corporate action en
attente" is a genuinely new field, `corporate_action_pending: bool`,
computed once per request (not per row) via
`corporate_actions/service.py::list_outstanding_candidates` — the exact
same merge/classify engine Data Health v2 and the "Candidats à confirmer"
list already rely on, no new query logic invented.

Frontend: one checkbox ("N'afficher que les candidats aux données
fiables") below the verdict filter, ANDed with both existing filters.
3 new backend tests (price_status reflects an unmapped instrument;
corporate_action_pending true/false against a real seeded
`ProviderCorporateActionCandidate` row) — full suite 1015 passed.
`tsc -b`/`oxlint` clean; i18n catalogues at parity (755 keys each).

**Deliberately not built in this slice**: market/country, sector,
instrument type, cap, dividend yield, debt, minimum-history-length
filters, and the explicit "not a recommendation" disclaimer rework — all
still named in the memory note as the fuller vision, none scoped yet.
Cap/dividend-yield/debt in particular need new derived metrics (this app
only stores raw filed XBRL figures today, not ratios) — a real backend
chantier of its own, not a filter-UI addition.

## Decision 3u.64 — Discovery country/sector filters, no backend change needed (2026-09-15)

Continuing the same slice-by-slice build of the fuller Pépites-filters
vision (memory `stock-analyst-roadmap-2026-09.md` item 5): market/pays
and secteur next, user-requested by name.

**Zero backend work, unlike 3u.63's data-quality gate**: `Instrument.country`/
`.sector` were already columns, already populated (`country` from
`get_or_create_instrument`'s broker-symbol-suffix resolution — every
instrument gets one, not just S&P 500 imports; `sector` from the S&P 500
import's own bundled data), and already exposed on `InstrumentOut` since
before this session. Purely a frontend addition: two `<select>`s, options
derived from whatever's actually loaded (`[...new Set(...)].sort()` over
the combined S&P 500 + Finviz candidate list) rather than a hardcoded
taxonomy, so a filter never offers a choice that would show an empty
list. Same "unknown excluded, never a false match" rule as every other
filter here.

Reused the existing `breakdown.dimension.country`/`.sector` i18n keys
(Country/Sector, already used by the allocation-breakdown and personal-
policy dimension pickers) for the field labels, rather than adding
duplicate `filters.market`/`filters.sector` keys — "Country" not "Market"
matches what the field actually is and what the rest of the app already
calls it. Kept scoped to `DiscoveryPanel` (same as verdict/data-quality),
even though `country`/`sector` also exist on `ScreenerTable`'s
`ScreenerCandidate.instrument` and so *could* have been lifted to
`Screener.tsx` like the price filter — the hint says so explicitly,
matching the verdict filter's own disclosed-scope convention, rather than
silently doing nothing for the Candidates list above.

Live-verified against the real portfolio: real S&P 500 data shows 11 GICS
sectors plus `null` (a handful of imported symbols never resolved
fundamentals) and a single "US" market (expected — it's a US index; the
Finviz preset scans are the path that would surface other countries).
No backend change means no new tests needed beyond the existing coverage
— `tsc -b`/`oxlint` clean, i18n catalogues at parity (757 keys each).

**Still not built**: instrument type, cap, dividend yield, debt,
minimum-history-length, and the "not a recommendation" disclaimer rework
— unchanged from 3u.63's list.

## Decision 3u.65 — Personal Policy exported to Hermes, closing the AI-piloting gap found by asking the question directly (2026-09-16)

User asked, exploratory: "un investisseur qui voudrait être piloté par
IA, il aurait besoin de quoi sur notre site ?" Answered without building
anything first (this app has no trade-execution capability at all, and
never will unless that's a deliberate future scope change — XTB's own
API is gone, see the README's "Read this first"): the two real gaps are
an agent-facing consolidated data surface, and a decision about whether
an agent should invent its own recommendations or stay strictly inside
the investor's *own* stated rules. Recommended the latter — reusing
Personal Policy (Decision 3u.59) rather than adding a new recommendation
engine that would contradict this app's whole "never tell the user what
to do" posture everywhere except Discovery's narrow, disclosed exception.
User agreed to pursue this direction.

**Found by re-reading `scripts/export_for_hermes.py` (Decision 3u.61-era,
commit `c08d67c5`) before writing anything**: the Hermes export already
exists and already bundles portfolio/breakdown/allocation/attention/
data-health/lots/dividends/tax — a real, working "agent-facing snapshot"
that answers half of what was just discussed. But it never included
Personal Policy or its gaps — the one piece that would let an agent
reason about the investor's *own* constraints rather than just seeing
raw numbers. Also found: that feature's own introducing commit
(`49d1df3`) claimed to add docs for both tax prep *and* Hermes export in
its message, but its actual diff only ever documented tax prep — the
Hermes export has had zero DEVLOG/ARCHITECTURE.md coverage since it
shipped. Both gaps closed together.

**Change**: `export_for_hermes.py` gains three more `_get()` calls —
`personal_policy`, `personal_policy_limits` (every configured limit,
satisfied or not — deliberately not just `/policy/gaps`'s breaches-only
view, since an agent needs to know "within bounds" is different from "no
rule set"), and `personal_policy_gaps`. Same pattern as every existing
field: calls the app's own endpoint, no logic duplicated, `None` on
failure rather than crashing the whole export. No backend change — all
three endpoints already existed (Decision 3u.59).

Verified live against the real backend on the dedicated host: all three
endpoints return real data (a configured policy, 4 real limits, 2 real
breaches). No new data-sensitivity concern — the export already carries
every position's real broker symbol via the existing `portfolio` field;
this only repeats the same already-flowing identifiers in a new field,
into the same already-authorized destination (Hermes' own read-only
bind mount, requested by the user in Decision-adjacent Hermes work,
never a public or shared surface).

**Not built, explicitly out of scope per the user's own agreed
direction**: any execution/trading capability, any endpoint that lets
Hermes *write* to this app rather than only read, and any new
independent "recommendation" surface for an agent to consume beyond
what Discovery already discloses. If Hermes needs to act, it acts inside
the investor's own Personal Policy — this app stays read-only and
descriptive, same posture as everywhere else.

## Decision 3u.66 — Wiring up the backtest report, the deliberate framing decision Decision 3u.23 deferred (2026-09-16)

Direct follow-up to the "philosophy evolving" exchange: the user asked
for a real prediction module first. `POST /api/prediction/backtest` has
existed, fully working and tested, since Decision 3u.23 (2026-09-03) —
`instruments_used`/train-test sample counts and date ranges/`test_accuracy`/
`avg_return_predicted_{up,down}`/`low_sample_warning`/`single_class_warning`
— but no frontend code ever called it (confirmed by grep before writing
anything: zero references in `client.ts` or any component). That commit's
own words: *"presenting a number like this responsibly needs its own
framing decision, a separate conversation from building the number
itself."* This is that conversation, finally had.

**The real choice, put to the user explicitly before coding**: an
aggregate report of the model's own historical performance (what it
already does, just never shown), or a per-instrument "predicted up/down"
label on Discovery candidates/positions. Chose the aggregate report.
Reasoning laid out for the user: the model's real, live-measured result
(`test_accuracy: 0.542` — barely above chance — over exactly one walk-
forward test period, even though the predicted-up/predicted-down buckets'
average *realized* returns are genuinely separated by ~15 points) does
not support showing a confident-looking label next to a specific ticker
without it reading as advice this app has spent the whole session
explicitly refusing to give anywhere except Discovery's narrow, disclosed
verdict exception — and even that exception is a mechanical score-band
mapping, not a statistical model with barely-above-chance accuracy.

**Built**: `BacktestPanel.tsx`, next to the existing `PredictionBackfillButton`
in `DiscoveryPanel.tsx` — a "Run backtest" button, the real metrics
(instruments used, train/test periods and sample counts, accuracy, the
two buckets' average realized returns), the two existing warnings
surfaced as actual warning notices (never silently dropped), and a
**permanent, non-dismissible disclaimer** every time a report renders —
same convention as Tax Prep's own permanent disclaimer (Decision 3u.60):
"one historical evaluation, not proof of a real trading edge... past
results say nothing certain about the future." Reworded
`prediction.description` (the phase-1 backfill button's own text), which
used to end with the now-false "No prediction is shown yet — this is
data collection only" — it now points at "Backtest" below instead.

No backend change at all — `run_backtest`/`BacktestReport` were already
correct and already tested (Decision 3u.23's 7 model tests). Purely a
frontend addition: new `BacktestReport` type, `api.runBacktest()`, the
component, 3 locales (770 keys each, parity verified). `tsc -b`/`oxlint`
clean (same two pre-existing warnings); existing `test_prediction_api.py`
(8 tests) still passing, confirming the reused endpoint is unaffected.

**Still deliberately not built**: any per-instrument prediction label,
anywhere. If that's ever revisited, it needs either a materially better-
validated model (more than one test period, ideally out-of-sample across
different market regimes) or an extremely careful framing that a ~54%
accuracy figure does not currently support — not a decision to make
implicitly by shipping a UI element.

## Decision 3u.67 — "Risques du portefeuille": unconditional exposure facts, split from Personal Policy (2026-09-16)

Direct follow-up, same "philosophy evolving" conversation: after the
prediction module, the next question was what an AI-piloted investor
would still be missing from this site. Answered by re-reading, not
guessing: Personal Policy (Decision 3u.59) already closes with an
explicit named follow-up — *"a future full portfolio-risk view
(sector/country/currency concentration beyond what a configured limit
already checks, liquidity-by-asset-class, valuation-risk breakdown,
historical drawdown)"* — this is that chantier, finally picked up.

**Real finding before writing anything**: two of the facets that follow-up
named are **already shipped**, mounted directly on `Portfolio.tsx` —
`PortfolioBreakdown.tsx` (category/currency/country/sector concentration)
and `FactorExposures.tsx` (Carhart four-factor exposure). Asked the user
how to organize the new page given this; chose a **new dedicated page
that reunites everything** — the two existing components moved (same
code, new home, not duplicated), alongside three genuinely new facets.

**Backend** — three new endpoints under `/api/portfolio/risk/`, all in
`routers/portfolio.py` (same reasoning `/policy/gaps` already established:
they need that module's private helpers, and there's no precedent here
for importing another router's private helpers):

- `GET /risk/concentration?limit=` — every held position's weight,
  largest first, reusing `_positions_figures_and_total` exactly as
  `/breakdown`/`/policy/gaps` already do. Real finding while designing
  this: `PositionOut.weight_percent` already exists unconditionally on
  plain `GET /api/portfolio` — added the dedicated endpoint anyway, for
  the same single-purpose-GET granularity every other risk/policy fact in
  this codebase already follows, and to decouple this page from
  `PortfolioOut`'s much larger, irrelevant-here shape.
- `GET /risk/liquidity` — declared-valuation share (Mintos Core P2P /
  Amundi ESR), by source and freshness. Reuses
  `_positions_figures_and_total` + `_declared_valuation_note` +
  `DECLARED_VALUE_FRESHNESS_DAYS`/`DECLARED_VALUE_PROVIDER_NAME` — the
  same pattern `/policy/gaps`'s own `declared_value` loop already uses,
  just unconditional and split by source. Deliberately **excludes** the
  third `not_priceable_reason` value in this codebase,
  `"corporate_action"` (CVR/corporate-action residuals) — that's a
  data-trust fact `/data-health` already owns, not a liquidity fact;
  mixing the two would blur what each page is for. Not currently
  exercised by the real portfolio (no held residual right now), but
  covered by an explicit regression test (`test_risk_api.py`) so the
  exclusion can't silently regress later.
- `GET /risk/drawdown` — the genuinely new metric. New pure function
  `compute_max_drawdown` in `prices/history_service.py`, next to
  `compute_value_history` (no signature change to that function) —
  computed from the exact same `Lot`-replay series `/value-history`
  already returns, no new data source. `MIN_DRAWDOWN_POINTS = 30`
  (~6 trading weeks) gates an honest `insufficient_history: true` below
  that many priced days. Chose backend over client-side TypeScript
  specifically because this project writes real pytest coverage for
  every computation while explicitly accepting "no frontend test
  framework" as a known gap — peak/trough/recovery edge cases (gaps,
  monotonic series, no recovery, two candidate drawdowns) would otherwise
  be the one computation with zero test coverage. "Recovered" means the
  series reached back to the pre-drawdown peak at some point after the
  trough — a real historical fact, never "is it at that peak right now."

No migration, no model change — everything derives from existing columns.

**Frontend**: new `pages/Risques.tsx` at route `/risk`, nav entry after
Tax Prep. `Portfolio.tsx` loses its `PortfolioBreakdown`/`FactorExposures`
imports and mount lines — nothing else on that page changes.
`PositionConcentration.tsx`/`Liquidity.tsx`/`Drawdown.tsx` are new,
self-contained (own fetch, `.card` wrapper), same convention as every
other standalone panel on this page. A permanent, non-dismissible
`notice info` disclaimer states the Policy-vs-Risk split in plain
language: *"These facts describe your portfolio's current exposure — not
a limit, and not a buy/sell recommendation."* Reused
`breakdown.dimension.country`/`.sector` and `breakdown.category.*` i18n
keys rather than duplicating them; reused `valuation.declaredStale` for
Liquidity's per-source staleness note rather than inventing new wording.

Tests: `test_risk_api.py` (new, 11 tests) — concentration ranking/limit/
unpriced-exclusion with exact hand-computed weights, liquidity per-source
grouping and the corporate-action-exclusion regression guard, stale-vs-
fresh freshness flagging, and a drawdown endpoint smoke test.
`compute_max_drawdown` itself gets 6 exhaustive pure-function unit tests
in `test_history_service.py` (below-minimum, monotonic/no-decline,
peak-trough-recovery, no-recovery, `None`-gap handling, largest-of-two-
drawdowns) — every hand-computed expectation matched the implementation
on the first run. Full backend suite: **1032 passed**. `tsc -b`/`oxlint`
clean; i18n catalogues at parity (792 keys × 3 locales).

**Live-verified against the real portfolio, end to end**: `/portfolio` no
longer shows breakdown/factors; `/risk` shows all five sections with real
numbers. Cross-checks, all exact matches: `PositionConcentration`'s top
row (17,504.04€, 39.98%) against `GET /api/portfolio`'s own
`weight_percent` for the same instrument; `Liquidity`'s total (70.94%)
against `/policy/gaps`'s already-configured `declared_valuation` limit's
`current_pct` (same real figure surfacing unconditionally now instead of
only as a breach). Real drawdown: **34.75%**, peak 2025-08-28
(11,636.57€) → trough 2025-09-08 (7,593.40€), recovered 2026-05-06 — a
real, previously-invisible fact about this portfolio's actual volatility
history, now visible for the first time anywhere in the app.

**Deliberately not built**: nothing execution-related, nothing that lets
Hermes or any agent *write* to this app — read-only and descriptive, same
posture as everywhere else (Decision 3u.65's own closing line). Line-item
color-coded "risk tiers" were considered and rejected for
`PositionConcentration` — a color implies a verdict this page explicitly
avoids everywhere else.

## Decision 3u.68 — Decision journal: instrument-optional, never per-trade (2026-09-16)

The chantier DEVLOG "Decision 3u.58" named and deferred (2026-09-10):
*"a decision journal (per-trade rationale/thesis/review-date log)"* — one
line, never scoped further anywhere else in the codebase. Picked up right
after Risques du portefeuille, on the user's "on y va."

Asked directly what an entry should be tied to, since "per-trade" is
ambiguous between three real shapes with different implications: tied to
a specific `Lot` (fragile once that lot closes), tied to an instrument
(survives lots being closed/sold, can be written *before* a trade even
happens), or untied entirely. The user chose **an instrument, optional** —
not a specific `Lot`. This means the actual "thesis" — arguably the most
valuable moment to capture it — can be written before any trade exists,
and a general/macro entry with no instrument at all is a first-class case,
not an edge case.

**Backend**: new standalone `routers/journal.py` (plain CRUD, no derived
computation, so unlike Risques there's no private-helper reuse forcing it
into another module) — `POST/GET /api/journal`, `PATCH
/api/journal/{id}`, `PATCH /api/journal/{id}/outcome`, `DELETE
/api/journal/{id}`. New model `JournalEntry` (`instrument_id` nullable,
no cascade delete — same `Lot`-style FK-survival guarantee), new Alembic
migration `75e668ef8794`. `entry_date` is set server-side to today and
never accepted from the client, not even on `PATCH` — a historical fact
about when the decision was actually written, never silently rewritten.

**Deliberate refinement over the approved plan**: the plan's
`JournalEntryUpdateIn` had `thesis`/`review_date`/`outcome_note` all
independently optional on one `PATCH`. Implemented instead as **two
separate endpoints** — editing the original decision
(`thesis`/`review_date`, mirrors `WatchlistItemUpdateIn`'s "the edit form
submits everything it owns" convention) and adding an outcome
(`outcome_note` alone) — because the plan itself already framed these as
two conceptually different moments (the decision vs. a later reflection
on it), and this codebase has no precedent for `exclude_unset`-style
partial updates that a single merged endpoint would have needed.

**Frontend**: new `pages/Journal.tsx` at route `/journal`, nav entry after
Risk. `AddJournalEntryForm.tsx` reuses the exact debounced-symbol-search
pattern `AddToWatchlistForm.tsx` already established. The thesis field is
a `<textarea>` — **the first multi-line free-text field in this entire
app** (every other free-text field, `WatchlistItem.note` included, is a
single-line `<input>`). Deliberate: a thesis is the one thing this
feature exists to capture, genuinely multi-sentence by nature — forcing
it into a single-line input would hurt the feature's actual point.
Entries render as cards, newest `entry_date` first; an entry with a past
`review_date` and no `outcome_note` yet gets a descriptive `tag
confidence-review` "Due for review" badge — a fact, not a nudge to act.
Edit (thesis/review date) and "add/edit outcome" are two separate inline
actions, matching the backend's own two-endpoint split; delete has no
confirmation dialog, same as every other list in this app.

Tests: `test_journal_api.py` (new, 16 tests) — symbol vs. no-symbol
creation, blank/missing thesis rejected, `entry_date` immutable even if
the client sends one, newest-first ordering, the two `PATCH` endpoints
independently, and the FK-survival regression guard (deleting the
referenced `Instrument` does not cascade-delete the journal entry). Full
backend suite: **1050 passed** (2 known pre-existing unrelated flaky
tests excluded from the count, same as every prior chantier this
session). `tsc -b`/`oxlint` clean (same 2 pre-existing warnings as
baseline, nothing new); i18n catalogues at parity (816 keys × 3 locales).

**Live-verified against the real running app**: created one entry with a
symbol (AAPL.US) and one without (a "General" entry) via the actual UI —
both appeared immediately, `entry_date` on both read **16/09/2026**,
matching today. Set `review_date` to 2026-09-01 (in the past) on the
General entry — the "Due for review" tag rendered correctly, and stayed
absent from the AAPL entry, which has no `review_date`. Added an
`outcome_note` to the AAPL entry ("Sold half the position after a 12%
rally...") without touching its `thesis` — reloaded the page and both the
original thesis and the outcome persisted correctly, independently.
Deleted the AAPL entry via the API and confirmed directly against the
database that instrument id 10 (AAPL.US) was untouched — still resolvable,
not orphaned. Both throwaway verification entries were removed from the
real database afterward, leaving the journal empty as it was before this
chantier.

**Deliberately not built**: no scheduled reminder/notification for
`review_date` — it's a descriptive "due" fact surfaced on the page, not a
push. No per-entry link to a specific `Lot`/trade fill, per the
instrument-optional decision above.

## Decision 3u.69 — Beginner UX audit: Transactions/Dividendes, and a codebase-wide color-as-verdict sweep (2026-09-17)

Continuing the beginner-comprehension initiative (Portfolio and Position-
detail screens were audited and fixed earlier — Decisions 3u.37/3u.38):
picked up Transactions/Dividendes, the next screens in the priority order
set back in Decision 3u.37. Three parallel audits (Transactions.tsx,
Dividends.tsx, and a codebase-wide grep for the known bug pattern — a
status reusing the app's green/red gain/loss tokens, `var(--positive)`/
`var(--negative)`, for something that isn't a gain or loss) found real
instances in both screens plus 7 more across the app once checked
everywhere, per the standing lesson from Decision 3u.38 ("once one
component has a color-as-verdict bug, grep for the same pattern across the
rest of the codebase").

**Transactions**: `signClass(tx.amount)` on the "Montant" column colored
every row by raw cash-flow sign regardless of `tx.type` — a `BUY`/
`WITHDRAWAL`/`FEE` rendered red, a `DEPOSIT`/`SELL`/`DIVIDEND` rendered
green, misreadable as a loss/gain when only `CLOSED_TRADE` rows are an
actual realized gain/loss. Fixed by scoping the color to
`tx.type === 'CLOSED_TRADE'` only. Also added a tooltip to "Effet titre"
mirroring the one "Devise & frais" already had — an asymmetry that had
gone unnoticed.

**Dividends**: the "Rapprochement" tag colored `'matched'` green
(`.tag.resolved`) — a purely technical "the app auto-matched this row"
fact, not a financial outcome — switched to `.tag.confidence-confirmed`
(blue), the same class Corporate Actions already uses for "confirmed by
the app's own matching." `withholding_tax` was colored red via
`signClass` in three places even though it's structurally always ≤ 0, a
routine deduction, not a variable outcome — removed. Also: `unmatched_tax`
detail rows were reusing the "Net" column to show the bare orphan tax
amount under the same header as every other row's real net figure — now
shown as `—`, matching how "Gross" already reads for those rows.

**Codebase-wide sweep, 7 more instances found, all fixed or explicitly
justified**: `Settings.tsx`'s provider "enabled" badge (green → blue,
`--accent`) and "cooling-down"/quota-near-limit notes (red → amber,
`--warning` — a temporary, recoverable state, not a broken one);
`MappingCell.tsx`'s "verified" symbol-mapping tag and
`AllocationTargets.tsx`'s "within target" tag (both green → blue,
`.tag.confidence-confirmed`) — a configured target being met shouldn't
read as an implicit "good job," same no-verdict discipline already
applied to Personal Policy gaps. Three more were checked and left
unchanged, each with a one-line comment recording why: `Settings.tsx`'s
API-key test result (a genuine live pass/fail, same justified class as
`PriceStatusBadge`), `AttentionCard.tsx`'s "missing" severity (checked its
real triggers in `routers/portfolio.py` — `price_error`/
`unresolved_instruments`, genuine data-correctness gaps, same class as
`DataHealthPanel`'s `action_required`), and `OnboardingChecklist.tsx`'s
done checkmark (a near-universal completion convention, no realistic
misread risk).

**Watchlist/Pépites**: the grep came back clean — no misuse of the color
tokens there. The full vocabulary/disclosure audit for those two screens
is still un-started and stays queued as the next pass, per this project's
own "one screen at a time, verify before generalizing" rule.

Live-verified against the real running app: a `Buy`/`Deposit`/`Withdrawal`
row's Montant is now plain white (`rgb(232, 234, 237)`) regardless of
sign — a real -177.60€ `Buy` and a real -200.00€ reversed `Deposit` both
render uncolored — while `Closed position` rows still color correctly by
their real P&L (green `rgb(95, 211, 154)` / red `rgb(255, 138, 128)`,
confirmed on real rows). Dividends' "Automatic" reconciliation tag now
renders `rgb(122, 165, 255)` (accent blue) instead of the previous green.
Settings' provider "Enabled" badges render the same blue. The mapping
"verified" tag and allocation "within target" tag on the Portfolio page
both render `.tag.confidence-confirmed`'s blue background
(`rgb(30, 42, 68)`). `tsc -b`/`oxlint` clean (same 2 pre-existing
warnings, nothing new); i18n at parity (819 keys × 3 locales).

## Decision 3u.70 — Real bug: dividend summary was summing different currencies together (2026-09-17)

Found while auditing Dividends for Decision 3u.69, not a UX/wording issue:
`dividend_summary()` grouped only by `(year, account)` and summed raw
`Transaction.amount`, with **no currency dimension at all**. Confirmed
live against the real database before writing any fix — the "My Trades"
account holds dividend/withholding rows in EUR, USD, CHF, GBP and SEK, and
the 2025 summary row was silently adding
`20.91 EUR + 55.98 USD + 3.23 CHF + 1.84 GBP` into one reported "82.3," as
if 1 EUR equaled 1 USD equaled 1 CHF. This fed both the year-by-account
table and the page's hero cards.

Fixed by adding `currency` (via the existing `_currency_for()` helper,
already used in `dividend_detail` but never called in `dividend_summary`)
as a third grouping key alongside year and account — no conversion logic
added, this app never implicitly converts currency anywhere else either.
`DividendSummaryRow`/`DividendSummaryRowOut` gained a `currency` field;
the summary CSV export gained a `currency` column. Frontend: the
year-by-account table gained a "Devise" column (row key now
`year-account-currency`); the hero cards, which used to blindly sum
`heroRows` across every account *and* currency for the latest year, now
render one line per currency present ("6.72 CHF + 21.06 EUR + 18.07 USD")
instead of a single blended number, falling back to today's plain single
figure when only one currency is present (the common case — PEA is always
EUR-only). "Comptes analysés" now counts distinct accounts rather than
distinct summary rows, since one account can now produce several rows.

New test `test_currencies_are_never_summed_together` in
`TestSummaryAggregation`, using the exact real-world shape (two
instruments in different currencies, same account, same year) — asserts
two separate summary rows, values never mixed. Full backend suite:
**1050 passed** (1 pre-existing unrelated flaky test excluded, same as
every prior chantier this session).

**Live-verified against the real portfolio**: the 2026 summary table now
shows four separate rows for that year (`PEA/EUR`, `My Trades/USD`,
`My Trades/EUR`, `My Trades/CHF`) where it used to show two blended ones;
the 2025 hero "Dividendes 2025 — brut" no longer shows a single "82.3" but
correctly separates EUR/USD/CHF/GBP. A real, previously-wrong number is
now correct for the first time since this page shipped (Decision 3u.28).

## Decision 3u.71 — Beginner UX audit: Watchlist and Pépites, closing the screen-by-screen sequence (2026-09-17)

Last two screens in the priority order set on 2026-09-07 (Portfolio and
Position-detail: Decisions 3u.37/3u.38; Transactions/Dividendes: Decisions
3u.69/3u.70). Two Explore agents read every component and i18n string
these screens use — a codebase-wide grep had already confirmed neither
has any color-as-verdict misuse, so this pass was wording/disclosure only.

**Watchlist**: the "Écart à l'entrée" column — a signed, green/red
percentage with no explanation on the column itself — looks exactly like
the P&L figures already audited on Portfolio/Position, but it isn't one:
it's the gap to the *user's own* target price, not a performance figure.
Added a header tooltip. The Score column's header had no tooltip either,
unlike `PositionsTable.tsx`'s equivalent — added the same
`table.scoreTooltip` it already reuses elsewhere. The "hold" signal state
rendered as a bare "—", visually indistinguishable from "no data," while
its siblings ("Insufficient data", the reinforce fact) show real
sentences — changed to a short visible phrase ("Nothing to flag" / "Rien
à signaler" / "Brak sygnału"), still neutral-gray. Added a tooltip on the
target-price field stating it's the user's own reference, never
app-suggested. Also removed `watchlist-opportunity`, a CSS class applied
to reinforce-signal rows with **no matching rule anywhere in `index.css`**
— found dead while auditing the Signal column. Chose to remove rather than
implement new row-highlight styling: this app has already deliberately
downplayed "reinforce" to a neutral amber badge rather than a stronger
visual cue (`SignalBadge.tsx`'s own doc comment), so adding a full-row
highlight now would cut against that established direction.

**Pépites/Discovery**: the `RecommendationBadge` — the single place in
the whole app carrying an actual Buy/Hold/Sell verdict (a deliberate,
disclosed exception, Decision 3u.21) — had no tooltip at all, unlike every
sibling badge on the page (`ScoreBadge`, `PriceStatusBadge`,
`InsightsBadge`). This is exactly the gap Decisions 3u.63 and 3u.64 both
already named as "not yet built." Added one, stating plainly the verdict
is mechanically derived from the composite score, not real investment
advice — applies everywhere the shared component renders (S&P 500 table,
both Finviz result tables). `discovery.description` explained the
mechanism but never said "not advice," unlike every other verdict-
adjacent surface in this app (`scores.notAdvice`, `backtest.disclaimer`,
`policy.gaps.disclaimer`) — appended that sentence. Added tooltips to the
Value/Growth pillar-score columns in the S&P 500 table too, since a bare
"72"/"40" sitting next to the Verdict column risked reading as two more
little verdicts.

Not changed: the verdict's existence and its green/gray/red coloring —
both the settled Decision 3u.21 exception, not revisited. Everything else
on both screens (price-status icon, sparkline, news sentiment, AI-
commentary disclaimer, category tags, filters, S&P 500/Finviz operational
counts, backtest panel) was checked and already carries adequate
disclosure.

`tsc -b`/`oxlint` clean (same 2 pre-existing warnings); i18n at parity
(824 keys × 3 locales). Frontend-only change — no backend touch, no
migration, no service restart needed.

**Live-verified against the real running app**: both new Watchlist header
tooltips render with the intended text; the strengthened
`discovery.description` reads with its new closing clause. The "hold"
signal string and the three new Pépites tooltip strings were confirmed
served by the dev server (`GET /src/i18n/en.ts`) — this live portfolio
currently has no watchlist row in the exact "hold" state and no S&P 500
data imported yet, so those two specific badges couldn't be visually
hovered this session; re-check once either exists.

**This closes the beginner-comprehension initiative's screen-by-screen
sequence** — all five screens named in the 2026-09-07 priority order
(Portfolio, Position-detail, Transactions, Dividendes, Watchlist, Pépites)
are now audited and fixed.

## Decision 3u.72 — Pépites filters: market cap, debt ratio, minimum price history (2026-09-17)

Picked up the "Pépites filters" backlog item's remaining dimensions.
Decisions 3u.62-3u.64 (2026-09-15) had already shipped verdict/data-
quality/country/sector and explicitly deferred capitalisation/dividend
yield/debt/minimum-history, on the strength of a 2026-09-08 roadmap note
claiming they all "need new derived metrics — this app only stores raw
filed XBRL figures today, not ratios... a real backend chantier."

**That claim was checked against the actual code before trusting it
again, and it was only true for one of the four.** `fcf_yield`
(`scoring/metrics.py`) already computes `market_cap = price ×
shares_diluted` as a throwaway intermediate on every scoring pass;
`debt_to_equity` is a real, active, weight-20 Value-pillar metric
(`scoring.yaml`) computed for every Discovery candidate on every request
already — its raw ratio just never left `InstrumentScore.pillars[].
metrics[].value`. Minimum price history needed no derived metric at all,
just `len(closes)` over `PriceBar` rows already cached and already loaded
for the Technical pillar. Only dividend yield genuinely needs new data (a
new XBRL concept tag, fetched via the existing `fetch_fundamentals`
pipeline) — deferred, on its own, to a later chantier; the other three
shipped now.

**Backend**: `scoring/metrics.py` gained a small `market_cap()` function
extracted from `fcf_yield`'s existing inline logic, deliberately *not*
wrapped in the scored `MetricResult` machinery (a plain `float | None`) —
this is informational only and must never influence the composite score.
`InstrumentScore` (`scoring/service.py`) gained `market_cap`/`debt_ratio`/
`price_history_years`, computed inline in `compute_scores`'s existing
per-instrument loop from data it already assembles — zero new queries.
`debt_ratio` is read straight out of the Value pillar's already-computed
`debt_to_equity` metric (`_metric_value` helper), never recomputed.
Additive-only to the dataclass: every other caller of `compute_scores`
(`routers/scoring.py`, position signals) is unaffected. `discovery/
service.py` and `routers/discovery.py` (both the S&P 500 and Finviz
paths) pass the three fields through to `DiscoveryCandidateOut`.

**Frontend**: three new filters in `DiscoveryPanel.tsx`, same established
pattern as verdict/data-quality/country/sector (local state, `.filter()`
chained at both call sites, "unknown excluded, never a false match,"
explicit "doesn't apply to the hand-picked Candidates above" hint) —
market cap as a min/max range (mirrors the shared price filter), debt
ratio as a max-only input ("endettement" is a ceiling concept in
practice), minimum price history as a min-only input in years. New
`formatCompactNumber` in `i18n/index.tsx` (`Intl.NumberFormat` with
`notation: 'compact'`) renders a market cap as "5.6B" instead of a
13-digit number, locale-aware for free. New Market cap/Debt-to-equity
columns in the S&P 500 table (mirroring Value/Growth); minimum history
stays filter-only, no column — a data-sufficiency gate like the existing
data-quality checkbox, not a decision-relevant number worth displaying.

Tests: `test_scoring_service.py` — three new cases (a fully-resolved
stock gets all three fields; an ETF with no fundamentals gets history but
not cap/debt; a stock with fundamentals but no price bars gets debt but
not cap/history) confirming the "missing data → `None`, never guessed"
rule holds for the new fields too. `test_discovery_api.py` — two new
cases confirming the fields flow through `GET /api/candidates` and default
to `null`. Full backend suite: **1056 passed** (1 pre-existing unrelated
flaky test excluded — it happened to pass this run). `tsc -b`/`oxlint`
clean; i18n at parity (836 keys × 3 locales).

**Live-verified against the real S&P 500 candidates already evaluated in
this portfolio's Discovery data**: spot-checked ACGL.US (Arch Capital
Group) at **$36.5B** market cap — matches its real-world order of
magnitude, confirming the price×shares_diluted computation isn't a
units bug. Applied each filter on the real `/gems` page: the debt-ratio
filter (max 0.05) narrowed 20 S&P 500 candidates to 5, all genuinely
≤0.05; the history filter (min 4 years) narrowed to 9; the market-cap
filter (min 10B) narrowed to 11, all genuinely ≥10B. One real snag hit
and resolved during this verification, not a code bug: Vite's HMR had
left the page's mounted component in a stale state after the earlier
edits, so a filter change had no visible effect until a hard page reload
— a fresh mount picked up the new code immediately and every filter
worked first try afterward. Table columns render the new compact
formatting correctly ("5.6B", "43.3B") rather than raw 11-13 digit
numbers.

## Decision 3u.73 — Pépites filters: dividend yield estimate, closing the backlog item (2026-09-17)

The one piece Decision 3u.72 deferred: Discovery candidates aren't held,
so the existing scored `dividend_yield` metric (lot-replay of
`Transaction` rows) returns `None` for essentially all of them. Fixed by
adding a `dividend_per_share` XBRL concept
(`CommonStockDividendsPerShareDeclared`/`CashPaid` for EDGAR,
`ifrs-full:DividendsPaidPerShare` for ESEF) to the existing fetch
pipeline — zero new HTTP requests, EDGAR's company-facts call already
returns every concept — and deriving a new, deliberately separate,
unscored `dividend_yield_estimate` field from it (`scoring/metrics.py`),
never folded into the scored Value-pillar metric: the two measure
genuinely different things (this account's realized yield vs. a
company-level filed estimate) and conflating them under one name would
be a real, hard-to-notice correctness problem, plus it would reopen the
deliberate ETF exclusion the scored metric's own test guards.

**A real gap found during design, not implementation**: `refresh_batch`
never revisits an already-evaluated candidate (`verified_at IS NOT
NULL` permanently excludes it), so every Discovery candidate already in
this app's database would have shown `dividend_yield_estimate: null`
forever. New `backfill_dividend_concept` (`discovery/service.py`) plus
`POST /api/discovery/backfill-dividends` — same batched, "click again to
continue" convention as `/refresh`, targets specifically the instruments
missing this one concept, `force=True` to bypass the normal "already
fresh today" skip.

**A real, honest live-verification story.** The first backfill attempt
against the real running app processed 20 real candidates and saved
**zero** dividend figures — including for IBM, a well-known payer.
Investigated live rather than assumed broken: fetched IBM's actual EDGAR
company-facts payload directly and ran it through this app's own
`_normalise()` in isolation — it extracted correct, sane real figures
(6.55, 6.59, 6.63, 6.67, 6.71 $/share for 2021-2025, matching IBM's real
dividend history). So the code was right; something else wasn't. Traced
it to `GET /api/health` reporting `"edgar": false` on the live host —
`SEC_USER_AGENT` was present in `.env` but **empty**, so `EdgarProvider.
is_enabled()` (`bool("")` is falsy) had disabled EDGAR entirely, for
every fetch, not just this one. Pre-existing, unrelated to this change —
not something to silently patch: setting a real `SEC_USER_AGENT` needs a
real contact string per SEC's fair-use policy, the user's own choice, not
something to invent. Flagged it and asked; the user set it and asked for
a backend restart. Once EDGAR came back (`"edgar": true`), the exact same
already-committed code worked correctly on the very next real request —
no code change was needed once the environment was actually fixed. A
useful general lesson: when a fetch-based feature produces uniformly-zero
results across many real, known-good inputs, check whether the provider
itself is reachable *before* suspecting the newly-written logic.

**Live-verified with real EDGAR data after the fix**: 6 backfill batches
processed ~130 of this app's 547 real Discovery candidates; 66 now carry
real filed dividend figures, 291 remain (genuinely un-checked, not
failures — the endpoint is resumable, same "click again" pattern as
`/refresh`). Every value spot-checked against the raw filed figure
matches exactly: Albemarle (ALB.US) 1.43% = $1.62/share ÷ $113.45; Wynn
Resorts (WYNN.US) 0.29% = $0.25/share ÷ $86.71; Uber (UBER.US) exactly
0% (never paid a dividend, a real `0.0` fact, not a missing one).
Applied the new minimum-yield filter live on the real `/gems` page with
a real mixed set (Arch Capital 5.15%, Arthur J. Gallagher 1.05%, AIG
2.30%, Allstate 1.56%, Altria 5.96%) — a 3% threshold correctly narrowed
20 rows to exactly 2 (Arch Capital, Altria), both genuinely ≥3%. The
"Backfill dividend data" button and its evaluated/remaining notice work
in the real UI. Full backend suite: **1059 passed** (including the one
previously-flaky test, which happened to pass this run).

**This closes the "Pépites filters" backlog item completely** — all
four dimensions named as deferred back on 2026-09-08 (capitalisation,
dividend yield, endettement, historique minimal) are now shipped.

## Decision 3u.74 — Two real bugs found running the dividend backfill for real (2026-09-17)

Asked to actually run Decision 3u.73's backfill against the real 291
remaining candidates. Running it live surfaced two genuine bugs neither
the plan nor the first round of testing had caught.

**Bug 1 — a genuine non-payer never left the "still missing" batch.**
`_missing_dividend_concept_query` was keyed on "no `dividend_per_share`
`Fundamental` row exists" — but a real non-payer with no XBRL dividend
tag at all will *never* get such a row, no matter how many times it's
fetched, so it was re-selected and re-fetched on every single call
forever. Live-confirmed: three consecutive calls dropped "remaining" by
only 1 each time (291→290→289), and the exact same ~19 tickers (AMD,
ADBE, DDOG, TSLA, AMZN, PLTR, SMCI, RDDT, CRWD, NFLX, ABNB, AKAM, ALGN,
APP, ANET, ADSK, AZO, AXON, BKR — all genuine non-payers) kept reappearing.
Fixed by tracking "has been checked" as its own fact, mirroring
`Instrument.verified_at`'s own role: new `DiscoveryCandidate.
dividend_checked_at` (migration `c9bb4d8cd815`), set unconditionally by
`backfill_dividend_concept` after every fetch attempt regardless of
outcome. Renamed the query accordingly
(`_unchecked_dividend_candidates_query`).

**Bug 2 — more serious: a real filer's data was silently wrong, not just
missing.** Investigating why Bank of America (a well-known payer) showed
no dividend estimate led to a genuine correctness bug: BAC's real 10-K
tags **each quarter's dividend separately**, all individually marked
`fp == "FY"` (confirmed by pulling BAC's actual EDGAR company-facts
payload directly) — a real filing convention this codebase's existing
`_extract` (built for `shares_diluted`/`revenue`/etc., which reliably
file one true annual fact per year) had never had to handle. Taking "the
latest `fp == 'FY'` entry," the rule every other concept safely follows,
silently kept only Q4's own $0.28 instead of the real ~$1.08 annual
total — a plausible-looking but wrong number, not an absence anyone
would have thought to double-check. Fixed with a new, dividend-specific
`_extract_dividend`/`_annual_dividend_total` (`providers/edgar.py`):
groups same-tag, same-year entries; if one already spans most of the
year (≥330 days) it's a genuine annual total, used as-is (the IBM/
Albemarle/Oracle case, unchanged); otherwise every entry is treated as a
same-year sub-period fragment and summed (the BAC case). Exact-duplicate
periods (a `10-K/A` restating the same quarter) are deduped first, kept
rather than double-counted. Scoped to `dividend_per_share` only via a
per-concept dispatch in `_normalise` — every other concept's extraction
is byte-for-byte unchanged.

**A useful general lesson, worth restating**: this is the second time
this session a fetch-based feature's "uniformly wrong/missing results"
turned out to have a root cause one level removed from where the
investigation started (the first time was `SEC_USER_AGENT` being empty;
this time, a filer-specific tagging convention nobody had reason to
expect). Both were found by pulling the real raw payload directly and
inspecting it, not by guessing from the app's own output — worth doing
that first whenever a real, known-good input produces a suspicious
result.

**Data hygiene**: before shipping the fix, backed up the live database
(`POST /api/backup`), then deleted all 843 already-saved
`dividend_per_share` rows (66 instruments × their filed years) rather
than leave any BAC-style wrong values in place hoping they'd self-correct
later — every one of those instruments' `dividend_checked_at` was still
unset at that point (the column is new), so a fresh backfill pass
naturally recomputes all of them under the corrected logic with nothing
skipped.

**Live-verified end to end after the fix**: ran the corrected backfill
to completion — 18 calls, `remaining` dropping by exactly 20 every single
time (357→0, no more plateauing) — confirming Bug 1's fix. **246 of 357**
already-evaluated candidates now carry real, correct dividend data (a
~69% payer rate, a plausible ratio for a broad market universe). BAC
specifically now shows **$1.08/share (2025)** on the real database,
**1.81% yield** (1.08 ÷ 59.52) rendering correctly on the real `/gems`
page — confirming Bug 2's fix end to end, not just at the unit level.
Full backend suite: **1064 passed**. New tests: `test_edgar.py` gained
`TestDividendAggregation` (the BAC quarterly-sum case, the single-annual-
fact regression case, the restatement-dedup case, the no-tag-at-all
case); `test_discovery_api.py`'s backfill tests rewritten around
`dividend_checked_at` plus a new regression test asserting a non-payer
is never re-selected on a second call.

## Decision 3u.75 — Minimum composite score filter, closing the Pépites filters backlog for good (2026-09-17)

Went back to the original 2026-09-08 backlog wording for "Pépites
filters" (item 15.5) to check what was actually still open beyond the
four dimensions Decisions 3u.72-3u.74 shipped. Three items in that list
had never been precisely scoped: "score d'analyse," "valorisation
disponible," "croissance disponible." Asked directly how to define them
rather than guess; the user chose a single minimum-composite-score
threshold — covering "score d'analyse" directly, and "valorisation/
croissance disponible" implicitly (a candidate with no Value/Growth
data has no composite score either, so it's excluded by the same
threshold without a separate toggle).

Pure frontend addition: `composite_score` already exists on
`DiscoveryCandidate` (Decision 3u.20) — no new backend field, no new
fetch. New `scoreMin` filter in `DiscoveryPanel.tsx`, same established
pattern as every other Pépites filter this session (min-only numeric
input, "unknown excluded" convention — a candidate with no computed
score at all is hidden, not shown as if it cleared the bar — applied at
both the S&P 500 and Finviz call sites, same disclosed-scope hint
sentence).

`tsc -b`/`oxlint` clean; i18n at parity (844 keys × 3 locales).
**Live-verified against the real portfolio**: a minimum of 90 on the
real `/gems` page's value-ranked top 20 narrowed 20 rows to exactly 1
(AJG.US) — cross-checked against the raw `composite_score` values from
the API directly: AJG was the only one of the 20 at 91.10, every other
candidate scored between 55.5 and 89.5.

**This closes the "Pépites filters" backlog item completely, including
the three previously-unscoped dimensions** — nothing named in the
2026-09-08 backlog list remains unaddressed.

## Decision 3u.76 — Canonical instrument identity via OpenFIGI, and two real bugs found running the backfill for real (2026-09-17)

The "new data sources" architecture proposal (2026-09-07) named a
canonical-identity layer as its recommended starting point. Picked up to
address a real, already-documented gap: `get_or_create_instrument` (the
single chokepoint every import path funnels through) keys **only** on
exact `broker_symbol` — never ISIN or anything else — so the same real
company held under one broker symbol and later watchlisted under a
different one silently becomes two unrelated `Instrument` rows today. A
real duplicate-ISIN case is already on record (Decision 3u.16, 4 rows
one company), and the existing reactive warning
(`symbols/duplicates.py::check_for_duplicate`) only fires at add time
when a company name happens to be supplied.

**Supersedes, not contradicts, Decision 2c.3.** OpenFIGI was evaluated
and rejected once before, for a *different* need (resolving an ISIN for
Frankfurt pricing — OpenFIGI returns FIGIs, not ISINs, so it didn't fill
that gap). Today's need is different: a stable cross-reference to
recognise the same real-world instrument under two different broker
symbols, for which FIGI itself — specifically OpenFIGI's *share-class*
FIGI, identical across every exchange listing of the same security — is
exactly the right key.

**Shipped**: `Instrument.figi`/`share_class_figi`/`figi_checked_at`
(migration `0873d0d3f871`); new `providers/openfigi.py` (keyless, works
unauthenticated); `symbols/duplicates.py::backfill_figis` (same "batch,
resumable" shape as `backfill_isins`/`backfill_dividend_concept`, scoped
to held/watchlisted/screened plus already-evaluated Discovery rows) and
`find_figi_duplicates` (cache-only, read-only, scoped to tracked
instruments — never Discovery's raw, unpromoted pool); `POST
/backfill-figis`; `DataHealthOut.figi_duplicates`, additive; a
`BackfillFigisButton` on Watchlist/Screener; a new Data Health section,
hidden when empty. Detection only, same as every other identity check in
this app — never merges or blocks.

**Running the real backfill against the real portfolio surfaced two
genuine bugs, neither caught by the first round of tests:**

**Bug 1 — a bare ISIN lookup was misread as "ambiguous."** The first
live call resolved **0 of 20**. OpenFIGI's real response for a single
ISIN returns *one row per exchange/vendor feed* — Apple's ISIN
(`US0378331005`) came back with **275 rows**, all but a handful sharing
one `shareClassFIGI`. `map_instruments`'s ambiguity check
(`len(data) != 1`) treated any multi-row response as unresolvable,
which is true for almost every real security. Fixed: `_resolve_match`
now drops rows with no `shareClassFIGI` (a handful of synthetic
CFD-style tickers, e.g. `AAPLGBX` on exchange `X1`, that OpenFIGI can't
assign one to) and is ambiguous only if the remaining rows *disagree* on
`shareClassFIGI` — genuinely different securities, not just different
listings of the same one. After the fix, the same batch resolved
**20/20**.

**Bug 2 — a rate-limited request was recorded as a permanent
non-match.** Backfilling the full queue hit OpenFIGI's unauthenticated
25 req/min limit partway through; the last 6 batches (110 instruments)
all came back **0 resolved**, confirmed live via a direct probe against
`api.openfigi.com` returning `429 Too many requests`. The existing code
treated any non-200/network failure the same as a genuine "OpenFIGI
answered, no match" and set `figi_checked_at` regardless — exactly the
bug class Decision 3u.74 already fixed once for dividends, reintroduced
here on a new signal. Fixed: `map_instruments` now returns a distinct
`FIGI_LOOKUP_FAILED` sentinel for HTTP/network failures, and
`backfill_figis` skips marking those instruments checked, leaving them
eligible for the next call.

**Data hygiene**: backed up the live database (`POST /api/backup`)
before touching anything, then reset `figi_checked_at` to `NULL` for the
130 instruments mis-marked by the two bugs above (the very first batch,
pre-Bug-1-fix, plus the six rate-limited batches) — confirmed first that
none of the 130 had a `figi` already stored, so nothing real was
discarded.

**Live-verified end to end after both fixes**: re-ran the backfill to
completion — **390 checked, 349 resolved** (~89.5% resolution rate on
this portfolio's tracked instruments). Spot-checked `AAPL.US` against
the live OpenFIGI API directly: `figi=BBG000B9XRY4`,
`share_class_figi=BBG001S5N8V8` — matches exactly. `figi_duplicates` is
empty for this portfolio (no genuine same-company-different-symbol case
exists in it today); confirmed live in the browser that the new Data
Health section correctly stays hidden rather than rendering an empty
list — the synthetic case is covered in the test suite instead
(`test_symbol_duplicates.py::TestFindFigiDuplicates`).

Full backend suite: **1095 passed**. New/updated tests:
`test_openfigi.py` (multi-row-same-share-class resolves; noise rows with
no `shareClassFIGI` ignored; genuine disagreement still ambiguous; HTTP/
network failure returns `FIGI_LOOKUP_FAILED`, not `None`);
`test_symbol_duplicates.py` (a transient lookup failure is never marked
checked and stays eligible for retry, distinct from the existing
genuine-non-match-is-permanent test).

## Decision 3u.77 — Visual design pass: the app "looked like a draft" (2026-09-18/20)

User feedback, verbatim: "il faudrait refaire l'interface car actuellement
il ressemble plutôt à un brouillon" (the interface should be redone, it
currently looks more like a draft). Scoped before touching any code, via
three explicit choices: pilot one screen first (Portfolio) rather than a
big-bang rewrite; the complaint was lack of hierarchy/spacing, a generic
look, and inconsistency between screens (not, e.g., colors specifically);
direction is "épuré, fintech moderne" (clean, modern fintech — controlled
whitespace, cards with subtle shadow, targeted accent color), not a warm/
playful or a dense/technical alternative also offered.

**The whole app already shares one design system** — a single
`index.css` with CSS custom-property tokens and hand-rolled utility
classes (`.card`, `.stat`, `.tag`, tables, buttons, `.notice`), no
component framework. This mattered: refining the shared tokens once
uplifts every screen automatically, rather than needing a per-page
rewrite — confirmed live, screen by screen, after the first pass.

**Token/primitive changes** (`frontend/src/index.css`): added a real
spacing scale (`--space-1`…`--space-8`) and type scale (`--fs-xs`…
`--fs-2xl`) to replace ad hoc rem values; split card radius from
control radius (`--radius-lg: 16px` for cards, `--radius: 9px` for
buttons/inputs — was one flat `10px` for everything); layered shadows
(`--shadow-sm`/`--shadow`/`--shadow-lg`) instead of a single flat
`box-shadow`; deepened the dark palette's background (`#0c0e13` vs the
old `#14171c`) so surfaces read as genuinely elevated instead of a
slightly-lighter gray; refined the light palette similarly. `.stat`
tiles gained a 3px top accent bar, colored green/red via `:has(.value
.positive)`/`:has(.value.negative)` when the metric has a sign — the
"hero KPI" treatment Portfolio/Dividends/Transactions all get for free.
`.card h2` became a small-caps "section eyebrow" (uppercase, muted
color, bottom divider) instead of a plain bold label. `.tag` moved from
a small square radius to the same 999px pill `.score-badge`/
`.insights-badge` already used — one of the concrete "inconsistency
between screens" instances named in the complaint.

**Three real bugs found while touring every screen for the pass, none
related to the visual tokens themselves:**

1. **Settings' entire "Data provider status" section had zero shared
   styling** — `.provider-row`/`.provider-info`/`.status-badge`/
   `.providers-list`/`.signup-link`/`.keyless-note` were styled by a
   page-local `<style>{...}</style>` tag at the bottom of `Settings.tsx`,
   completely disconnected from `index.css`: its own hardcoded `3px`/
   `4px` radius (vs. the app's `9px`/`16px`), `opacity: 0.7` instead of
   `--text-muted`, and solid-fill white-on-color badges instead of the
   `.tag` family's soft-pill convention everywhere else. This alone was
   probably the single biggest concrete source of "looks like a draft"
   on that page. Moved into `index.css`, rewritten onto the shared
   tokens and the soft-pill formula.
2. **The Settings save-confirmation banner never had a color, ever.**
   `className={\`card notice notice-${notice.type}\`}` produced a class
   literally named `notice-success`/`notice-error` (one token), while
   the CSS selector is `.notice.success`/`.notice.error` (two classes)
   — never matched. Every "API keys updated" or error banner on the
   most-used Settings action rendered as plain text in a padded box, no
   background, no border color. Fixed the template string; confirmed
   live via the real save button and a computed-style check (`class:
   "card notice success"`, green background/text/border as intended).
3. **The new `.card h2` eyebrow divider broke 12 components' headers.**
   Found via a full grep audit of every `<h2>` in the codebase, not by
   screenshot luck — screenshots alone had already missed it (none of
   the collapsed "add" forms happened to be open in the screens
   captured). Any `<h2>` sharing its row with a subtitle and/or a
   button (a collapsed add-form's summary row, `ValueHistoryChart`'s
   legend, `PortfolioBreakdown`'s view-toggle buttons,
   `OnboardingChecklist`'s dismiss link, `PersonalPolicyPanel`'s edit
   button — 12 call sites total) would render the new border-bottom
   divider only under the h2's own shrink-wrapped box, producing a
   short underline in a random spot instead of a clean full-width line.
   Added `.card h2.compact` (plain heading: no divider, no uppercase,
   tight margin) and applied it at all 12 sites, replacing each one's
   previous ad hoc `style={{ marginBottom: '0.2rem' }}` override.

**Also fixed, unrelated to the visual tokens, found by the same
full-screen tour**: five Mintos P2P transaction types
(`P2P_INVESTMENT`/`P2P_PRINCIPAL_REPAYMENT`/`P2P_INTEREST`/`P2P_FEE`/
`P2P_SNAPSHOT`) existed on the backend's `TxType` enum since Decision
3u.39 but had no i18n key in any of the three locales — every P2P row
on Transactions/`PositionDetailRow` rendered the raw key
(`transactions.type.P2P_FEE`) instead of a label. Added all 5 keys to
en/fr/pl (857 keys × 3 locales, parity re-confirmed).

**Scope actually covered**: Portfolio (pilot — hero stat tiles,
page-header cleanup), then every other screen (Transactions, Watchlist,
Hidden gems, Tax prep, Risk, Journal, Settings) via the shared
primitives plus targeted per-page fixes (`.page-header-actions` for the
two backfill buttons that were dropped flush under the description with
no gap on Watchlist/Screener; the Settings provider-status rewrite; the
12-site `.compact` fix). Not touched: no new component framework, no
webfont (kept the existing system-font stack — the hierarchy problem
named in the complaint came from scale/weight/color/spacing, not
typeface), no icons (deliberately, matching the "épuré" direction).

**Live-verified after every commit** (this chantier's own discipline:
commit → push → SSH pull → verify against the real running app, no
batching): light and dark themes on Portfolio; no regressions on
Watchlist/Settings/Screener/Tax prep/Risk/Journal; the Settings notice
fix confirmed via a real save click plus computed styles
(`getComputedStyle`) rather than trusting the screenshot tool alone,
which had an unrelated pane-rendering quirk on tall pages after
scrolling (confirmed pre-existing, not a CSS regression, by cross-
checking `get_page_text`/computed styles matched the real DOM). `tsc
-b`/`oxlint` clean at every step; i18n parity re-confirmed at 857 keys.

## Decision 3u.78 — gitleaks pre-commit hook, after giving the Hermes agent read-write access to backend/ and frontend/ (2026-09-24)

The Hermes agent's sandbox (a separate, internet-connected Docker container on
hermes-host, used for code review/fixes on this project) got `backend/` and
`frontend/` bind-mounted read-write so it could work on real ISIN/ticker
reliability fixes without a copy-paste round trip. A bind mount means its
edits land directly in this working tree — there is no staging area between
"Hermes wrote a file" and "it's sitting in `git status`" — so the actual
checkpoint against an accidentally-committed secret is at commit time, not a
review step beforehand. `.env`, `data/`, `backups/`, `Extractions/` are not
mounted (real API keys and real financial data — none of it reachable from
the sandbox), but that only covers what's excluded by construction, not a new
file Hermes might create inside `backend/`/`frontend/` themselves.

Added `.githooks/pre-commit` (a tracked hook, not the untracked default
`.git/hooks/`, so every clone gets the same one — enable with `git config
core.hooksPath .githooks`) running `gitleaks protect --staged`. Config in
`.gitleaks.toml` extends gitleaks' default ruleset rather than replacing it,
plus one project-specific allowlist for `.env.example` (placeholder key
*names*, no real values) and `backend/tests/` (fixtures deliberately use fake
keys like `ab12cd34ef56` to test settings parsing — flagged by the baseline
scan below, confirmed as the expected false positive, not a leak).

**Baseline scan of the full history (141 commits) came back clean** once
that allowlist was in place — `.env` itself was never committed, only
`.env.example`. Worth knowing since the repo is already public on GitHub:
a clean history isn't something this hook produced, it's what was already
true; the hook's job is keeping it that way going forward.

Deliberately fails *open*, not closed: if `gitleaks` isn't on `PATH`, the
hook prints a warning and lets the commit through rather than blocking every
commit on a machine where it isn't installed yet. Verified both directions
for real (not just read) on both machines this project runs on — hermes-host
and the local dev machine — with an actual fake secret (a Stripe-shaped
token), not a synthetic test string, staged and committed for real each time.

One thing the fail-open path costs: it can't rescue you from itself. The very
first test ran before `gitleaks` was installed locally, so the hook warned
and let the fake-secret commit through — `git reset --hard HEAD~1` cleaned it
up fine since it only touches history the hook itself already let land, not
anything the hook is supposed to catch. That's expected, not a bug: the hook
protects against secrets slipping in on a machine where it *is* set up, not
against the gap before it is.
