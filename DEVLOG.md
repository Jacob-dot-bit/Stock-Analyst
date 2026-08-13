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
no source anywhere quotes it. XTB itself reports a price of 0.00 against a placeholder
nominal placeholder value.

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

---

# Up next

| Phase | Content | Status |
|---|---|---|
| 3 | Scoring engine (5 pillars, `scoring.yaml`) | to do |
| 4 | Watchlist and entry timing | to do |
| 5 | Hidden gems page (screener) | to do |
| 6 | Qualitative synthesis via Perplexity | to do |

**Open items for phase 2**

- Promote mappings from "unverified" to "verified" once a provider has actually served
  data for that symbol.
- FX rates (`Open/Close Conversion Rate`) are captured but not yet used — useful for
  splitting performance between instrument effect and currency effect.
- `yfinance` will break periodically (unofficial endpoints): the fallback chain to Stooq
  needs to be tested for real, not merely written.
- **Introduce Alembic before the next schema change.** No longer hypothetical: adding a column already required a hand-written ALTER TABLE to avoid discarding 10,193 collected price bars.
