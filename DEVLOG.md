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
- Introduce Alembic before phase 4 if the watchlist is to survive schema changes.
