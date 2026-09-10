export type MappingStatus = 'RESOLVED' | 'VERIFIED' | 'MANUAL' | 'UNRESOLVED'

/**
 * A translatable message from the API.
 *
 * The backend never returns prose: it returns a key into the i18n catalogues plus
 * the parameters needed to render it. That is what lets the same import report be
 * read in English, French or Polish.
 */
export interface ApiMessage {
  code: string
  params: Record<string, string | number | string[]>
}

export type SectionKind =
  | 'open_positions'
  | 'closed_positions'
  | 'cash_operations'
  | 'unknown'

export interface ImportSection {
  sheet: string
  kind: SectionKind
  count: number
  /** Raw row count before aggregation — larger than `count` when lots are listed. */
  source_rows: number
}

export interface Instrument {
  id: number
  broker_symbol: string
  provider_symbol: string | null
  mapping_status: MappingStatus
  name: string | null
  /** Category supplied by the broker: STOCK, ETF, CFD... */
  category: string | null
  currency: string | null
  country: string | null
  sector: string | null
  /** Unlocks the European price source; entered by hand, never guessed. */
  isin: string | null
  /** Set once a provider actually returned data for this symbol. */
  verified_at: string | null
  verified_provider: string | null
  not_priceable_reason: string | null
  /** Computed server-side. See backend `_price_status` for the rule. */
  price_status: 'fresh' | 'stale' | 'error' | 'not_priceable' | 'unmapped' | null
}

export interface Position {
  id: number
  instrument: Instrument
  source: 'IMPORT' | 'MANUAL'
  /** Originating account: "My Trades", "PEA"... */
  account: string | null
  quantity: number
  avg_price: number
  currency: string | null
  opened_at: string | null
  /** How many lots this holding aggregates. */
  lots_count: number
  broker_market_value: number | null
  broker_net_pl: number | null
  broker_net_pl_pct: number | null
  broker_gross_pl: number | null
  broker_purchase_value: number | null
  market_price: number | null
  commission: number | null
  swap: number | null
  comment: string | null
  /** Translatable caveat on `broker_net_pl`/`broker_net_pl_pct` when
   * derived from an approximation rather than a true cost basis — render
   * with `t(note.code, note.params)`. See `AccountTotals`. */
  performance_note: ApiMessage | null
  /** The date this position's *value* (not P&L) was declared by its
   * source — set only for a broker-declared valuation (Mintos Core P2P,
   * Amundi ESR), null for an ordinary priced position. */
  value_as_of: string | null
  /** Pairs with `value_as_of`: whether that declared value is within its
   * source's expected update cadence ('valuation.declaredFresh') or
   * predates it ('valuation.declaredStale'). null for an ordinary priced
   * position. Render with `t(note.code, note.params)`. See DEVLOG
   * "Decision 3u.50". */
  valuation_note: ApiMessage | null
  weight_percent: number | null

  // Up-to-date figures, computed server-side from whatever pricing is
  // currently available (live quote, cached daily close, or — CFDs and
  // anything not yet priceable — the broker's own frozen import figure).
  // See DEVLOG "Decision 2f.3".
  current_value: number | null
  current_unrealized_pl: number | null
  current_unrealized_pl_pct: number | null
  current_price: number | null
  price_source: 'live' | 'cached' | 'broker' | null
}

/** One actual buy fill for a single instrument — see `app/models.py::Lot`.
 * Open (still held) and closed (a complete round trip) lots share this
 * shape, distinguished by `lot_type`. Read-only. */
export interface Lot {
  id: number
  quantity: number
  open_price: number
  opened_at: string | null
  close_price: number | null
  closed_at: string | null
  currency: string | null
  account: string | null
  lot_type: 'OPEN' | 'CLOSED'
  source: 'IMPORT' | 'MANUAL'
}

export interface AccountTotals {
  account: string
  positions_count: number
  market_value: number | null
  invested_value: number | null
  unrealized_pl: number | null
  unrealized_pl_pct: number | null
  /** Set when this account's unrealized/invested figures come from an
   * approximation rather than an ordinary cost basis — e.g. Mintos Core
   * P2P's real cumulative interest income, or an Amundi fund's gain
   * pro-rated from known contributions. Render with `t(note.code,
   * note.params)`. See DEVLOG "Decision 3u.47". */
  performance_note: ApiMessage | null
  /** Set when at least one position in this account is a broker-declared
   * valuation (Mintos Core P2P, Amundi ESR) — independent from
   * `performance_note`: this account's `market_value` may be a dated
   * statement figure even when its P&L is unknown (Mintos) or vice versa.
   * Render with `t(note.code, note.params)`. See DEVLOG "Decision 3u.50". */
  valuation_note: ApiMessage | null
}

export interface PortfolioTotals {
  base_currency: string
  positions_count: number
  market_value: number | null
  invested_value: number | null
  unrealized_pl: number | null
  unrealized_pl_pct: number | null
  /** Sum of every closed trade's net P&L — independent of market_value/
   * unrealized_pl (completed round trips, not currently-held positions). */
  realized_pl: number | null
  has_incomplete_data: boolean
  excluded_positions: number
  /** True when at least one counted position carries a
   * 'valuation.declaredStale' note (a Mintos/Amundi valuation older than
   * its source's expected cadence) — the value is still fully included,
   * this only means the total isn't uniformly as fresh as it looks. See
   * DEVLOG "Decision 3u.50". */
  has_stale_declared_valuations: boolean
}

export interface Portfolio {
  totals: PortfolioTotals
  accounts: AccountTotals[]
  positions: Position[]
  unresolved_symbols: Instrument[]
  last_import_at: string | null
  last_price_refresh_at: string | null
}

export interface ImportBatch {
  id: number
  filename: string
  imported_at: string
  positions_found: number
  transactions_found: number
  transactions_inserted: number
  warnings: ApiMessage[]
  sections: ImportSection[]
  accounts: string[]
}

/** What an import would do, without persisting anything — see DEVLOG "Decision 3h.1". */
export interface ImportPreview {
  filename: string
  positions_found: number
  transactions_found: number
  transactions_inserted: number
  warnings: ApiMessage[]
  sections: ImportSection[]
  accounts: string[]
}

export interface Health {
  status: string
  base_currency: string
  integrations: Record<string, boolean>
}


export interface RefreshReport {
  outcomes: ApiMessage[]
  updated: number
  skipped: number
  failed: number
  /** Instruments with no possible market price — not a shortfall. */
  not_priceable: number
  /** Instruments left when the time budget ran out. Ask again to continue. */
  remaining: number
}

export interface RefreshStatus {
  running: boolean
  total: number
  done: number
  current_symbol: string | null
  started_at: string | null
  finished_at: string | null
  report: RefreshReport | null
}

export interface Sparkline {
  instrument_id: number
  closes: number[]
}

export type BreakdownDimension = 'category' | 'currency' | 'country' | 'sector'

export interface EnrichSectorsResult {
  enriched: number
  skipped: number
  failed: number
}

export interface BackfillIsinsResult {
  checked: number
  updated: number
}

export interface SymbolSearchResult {
  symbol: string
  name: string
}

export interface BreakdownItem {
  label: string
  value: number
  weight_percent: number
}

export type AllocationState = 'within' | 'under' | 'over' | 'no_target'

export interface AllocationRow {
  category: string
  current_value: number
  current_pct: number
  min_pct: number | null
  max_pct: number | null
  state: AllocationState
  gap_pct: number
  amount_to_reach_min: number | null
}

export type PersonalPolicyHorizon = 'short' | 'medium' | 'long'

export interface PersonalPolicy {
  objective_growth: boolean
  objective_income: boolean
  objective_preservation: boolean
  objective_note: string | null
  horizon: PersonalPolicyHorizon | null
  horizon_target_date: string | null
  liquidity_need_amount: number | null
  liquidity_need_date: string | null
  liquidity_note: string | null
  risk_tolerance_note: string | null
  loss_capacity_pct: number | null
  updated_at: string
}

export type PersonalPolicyDraft = Omit<PersonalPolicy, 'updated_at'>

export type PersonalPolicyLimitDimension = 'line' | 'sector' | 'country' | 'currency' | 'category' | 'declared_valuation'

export interface PersonalPolicyLimit {
  id: number
  dimension: PersonalPolicyLimitDimension
  target: string | null
  min_pct: number | null
  max_pct: number | null
}

export interface PersonalPolicyLimitDraft {
  dimension: PersonalPolicyLimitDimension
  target: string | null
  min_pct: number | null
  max_pct: number | null
}

export interface PersonalPolicyGap {
  limit_id: number
  dimension: PersonalPolicyLimitDimension
  target: string | null
  current_pct: number
  min_pct: number | null
  max_pct: number | null
  state: 'under' | 'over'
  gap_pct: number
}

export type AttentionSeverity = 'missing' | 'warning'

export type AttentionKind =
  | 'unresolved_instruments'
  | 'price_error'
  | 'price_stale'
  | 'allocation_under'
  | 'allocation_over'

export interface AttentionItem {
  severity: AttentionSeverity
  kind: AttentionKind
  count: number
  category: string | null
  gap_pct: number | null
}

export type DataHealthSeverity = 'info' | 'attention' | 'action_required' | 'not_applicable'

export type DataHealthValuationKind = 'market_price' | 'declared_value' | 'unavailable'

export type DataHealthFreshness = 'fresh' | 'stale' | 'unknown'

export type DataHealthCorporateActionsStatus =
  | 'verified'
  | 'no_events'
  | 'candidate_single_source'
  | 'provider_conflict'
  | 'suspect_ticker_reuse'
  | 'incomplete_coverage'
  | 'never_checked'
  | 'not_applicable'

export type DataHealthReason =
  | 'unresolved_symbol'
  | 'price_error'
  | 'price_stale'
  | 'never_refreshed'
  | 'declared_stale'
  | 'declared_value_missing_date'
  | 'corporate_action_candidate'
  | 'corporate_action_conflict'
  | 'corporate_action_suspect'
  | 'corporate_action_incomplete_coverage'
  | 'corporate_action_never_checked'

export type DataHealthRecommendedAction =
  | 'fix_symbol'
  | 'refresh_quotes'
  | 'import_recent_statement'
  | 'resume_alpha_vantage'
  | 'verify_eodhd'

export interface DataHealthValuation {
  kind: DataHealthValuationKind
  source: string | null
  as_of: string | null
  freshness: DataHealthFreshness
}

export interface DataHealthCorporateActions {
  status: DataHealthCorporateActionsStatus
  confirmed_events: number
  outstanding_events: number
}

export interface DataHealthRow {
  instrument_id: number
  symbol: string
  name: string | null
  valuation: DataHealthValuation
  corporate_actions: DataHealthCorporateActions
  severity: DataHealthSeverity
  reason: DataHealthReason | null
  recommended_action: DataHealthRecommendedAction | null
}

export interface DataHealthSummary {
  total_instruments: number
  info_count: number
  attention_count: number
  action_required_count: number
  not_applicable_count: number
}

export interface DataHealth {
  summary: DataHealthSummary
  rows: DataHealthRow[]
}

export interface OnboardingStatus {
  imported: boolean
  prices_refreshed: boolean
  unresolved_resolved: boolean
  fundamentals_fetched: boolean
  allocation_target_set: boolean
  watchlist_started: boolean
}

export interface ValueHistoryPoint {
  date: string
  /** null when nothing held that day could be priced at all — never a guessed/zero value. */
  value: number | null
  invested: number | null
  /** "If the same cash had bought the benchmark instead, on the same days." */
  benchmark: number | null
}

export interface ValueHistory {
  points: ValueHistoryPoint[]
  start_date: string | null
  /** True when the earliest lot predates the available price history. */
  capped_by_history: boolean
  benchmark_available: boolean
  benchmark_name: string | null
}

export type TxType =
  | 'BUY'
  | 'SELL'
  | 'CLOSED_TRADE'
  | 'DIVIDEND'
  | 'TAX'
  | 'FEE'
  | 'DEPOSIT'
  | 'WITHDRAWAL'
  | 'INTEREST'
  | 'OTHER'

export interface Transaction {
  id: number
  external_id: string | null
  type: TxType
  executed_at: string | null
  quantity: number | null
  price: number | null
  amount: number | null
  currency: string | null
  commission: number | null
  swap: number | null
  comment: string | null
  account: string | null
  instrument: Instrument | null
  /** Only set for CLOSED_TRADE rows with a resolvable split — see DEVLOG
   * "Decision 3p.1". null whenever it can't be computed. */
  instrument_effect: number | null
  /** Residual against `amount` — also absorbs commission/swap/rounding. */
  currency_effect: number | null
}

export interface TransactionSummary {
  total_dividends: number
  total_withholding_tax: number
  net_dividends: number
  total_fees: number
  total_realized_pl: number
  total_instrument_effect: number
  total_currency_effect: number
  /** How many closed trades fed the two totals above, out of how many
   * closed trades are in scope — CFDs routinely have neither a matching
   * lot nor conversion-rate data, so this is often a strict subset and
   * the two totals routinely do NOT sum to total_realized_pl. */
  closed_trades_with_effect: number
  closed_trades_total: number
}

export interface TransactionList {
  transactions: Transaction[]
  summary: TransactionSummary
}

/** One calendar year × account's dividend totals — computed directly from
 * DIVIDEND/TAX transactions, never by summing detail rows, so a
 * reconciliation miss can never silently shrink a real total. Descriptive
 * only: no tax liability is computed. See DEVLOG "Decision 3u.28". */
export interface DividendSummaryRow {
  year: number
  account: string | null
  gross: number
  withholding_tax: number
  net: number
  payment_count: number
}

/** "matched" (withholding found and attributed) | "no_withholding" (no tax
 * row found — normal, not an error) | "unmatched_tax" (a withholding that
 * couldn't be attributed to any dividend — a genuine anomaly worth a look). */
export type DividendReconciliationStatus = 'matched' | 'no_withholding' | 'unmatched_tax'

export type TaxEnvelopeKind = 'cto' | 'pea' | 'p2p' | 'employee_savings'

export interface TaxOtherFlow {
  label: string
  amount: number
}

export interface TaxEnvelopeSummary {
  account: string
  envelope_kind: TaxEnvelopeKind
  dividends_gross: number | null
  dividends_withholding: number | null
  interest: number | null
  realized_gains: number | null
  realized_losses: number | null
  fees: number | null
  deposits: number | null
  withdrawals: number | null
  unmatched_sales_count: number
  unmatched_sales_amount: number | null
  other_flows: TaxOtherFlow[]
  status: 'to_reconcile' | 'not_applicable'
  notes: ApiMessage[]
}

export interface TaxYearSummary {
  tax_year: number
  envelopes: TaxEnvelopeSummary[]
  disclaimer: ApiMessage
}

export interface DividendDetailRow {
  id: number
  executed_at: string | null
  instrument: Instrument | null
  account: string | null
  currency: string | null
  /** null only for an "unmatched_tax" row — an orphan withholding with no
   * dividend payment of its own. */
  gross: number | null
  /** null when no withholding was found — most dividends legitimately
   * carry none (0% treaty rate, PEA wrapper). */
  withholding_tax: number | null
  net: number | null
  comment: string | null
  reconciliation_status: DividendReconciliationStatus
}

/** Whether a price source is currently usable — not its API-key configuration
 * (see the separate `ProviderStatus` shape in Settings.tsx), but whether it is
 * presently rate-limited and how much of the held portfolio it can price. */
export interface ProviderAvailability {
  name: string
  enabled: boolean
  /** Backing off after hitting a rate limit — clears itself after a short wait. */
  cooling_down: boolean
  serves_holdings: number
  total_holdings: number
  /** null when this source has no documented quota — not "no limit", just unknown. */
  quota_limit: number | null
  quota_period: 'day' | 'month' | 'minute' | null
  quota_used: number | null
}

export interface QuoteStatus {
  running: boolean
  total: number
  done: number
  current_symbol: string | null
  started_at: string | null
  finished_at: string | null
}

/** One metric's contribution to its pillar. `score`/`value` are null when
 * `dropped_reason` is set — missing data is dropped, never guessed. See
 * DEVLOG "Decision 3r.1". */
export interface MetricScore {
  name: string
  weight: number
  score: number | null
  value: number | null
  dropped_reason: string | null
}

export interface PillarScore {
  name: string
  score: number | null
  /** This pillar's weight, renormalized against sibling pillars that also
   * scored — 0 when this pillar itself has no score. */
  weight_used: number
  metrics: MetricScore[]
}

export interface Score {
  instrument_id: number
  composite: number | null
  pillars: PillarScore[]
}

export type SignalValue = 'reinforce' | 'reduce' | 'hold' | 'not_applicable'
export type ScoreBand = 'high' | 'mid' | 'low' | 'none'

export interface PositionSignal {
  instrument_id: number
  signal: SignalValue
  composite_score: number | null
  score_band: ScoreBand
  category: string | null
  allocation_state: 'within' | 'under' | 'over' | 'no_target'
  gap_pct: number
}

export interface WatchlistSignal {
  instrument_id: number
  signal: SignalValue
  composite_score: number | null
  score_band: ScoreBand
  distance_to_target_pct: number | null
}

export interface WatchlistItem {
  id: number
  instrument: Instrument
  added_at: string
  target_entry_price: number | null
  note: string | null
  current_price: number | null
  price_source: string | null
  /** Negative or zero = current price is AT OR BELOW the target — a real
   * entry signal, the inverse of how "distance" normally reads. `null`
   * whenever either `current_price` or `target_entry_price` is missing. */
  distance_to_target_pct: number | null
  /** Set only right after a successful add, when the resolved ISIN matches
   * something already held/watchlisted/screened elsewhere — a soft signal,
   * the add still succeeds. `null` on every other read. */
  duplicate_warning: string | null
}

export interface ScreenerCandidate {
  id: number
  instrument: Instrument
  added_at: string
  current_price: number | null
  price_source: string | null
  /** See `WatchlistItem.duplicate_warning`. */
  duplicate_warning: string | null
}

export interface DiscoveryImportResult {
  imported: number
  already_present: number
}

export interface DiscoveryRefreshResult {
  evaluated: number
  remaining: number
}

/** A candidate surfaced automatically — never a real, tracked "hidden gem"
 * until explicitly added via the same screener-add flow as a manual pick. */
export interface DiscoveryCandidate {
  instrument: Instrument
  /** "sp500" | "finviz:insider_buys" | "finviz:oversold" — always shown,
   * never blended into one undifferentiated pool. */
  source: string
  composite_score: number | null
  value_score: number | null
  growth_score: number | null
  current_price: number | null
  price_source: string | null
  /** "buy" | "hold" | "sell" | null — an explicit verdict derived from
   * `composite_score`, Discovery-only exception to this app's usual
   * fact-based labeling (see DEVLOG "Decision 3u.21"). */
  recommendation: 'buy' | 'hold' | 'sell' | null
}

export interface DiscoveryFinvizResult {
  preset: string
  candidates: DiscoveryCandidate[]
  /** A candidate whose refresh/scoring failed is skipped, not left to
   * discard every other result in the same scan — this counts how many
   * were dropped that way, so the gap stays visible. */
  failed: number
}

export interface NewsArticle {
  title: string
  url: string
  source: string
  time_published: string
  summary: string
  overall_sentiment_label: string
  overall_sentiment_score: number
  ticker_relevance_score: number
  ticker_sentiment_score: number
  ticker_sentiment_label: string
}

export interface NewsSentiment {
  instrument_id: number
  fetched_at: string | null
  articles: NewsArticle[]
  outcome: ApiMessage
}

export interface Citation {
  url: string
  title: string | null
}

export interface InstrumentCommentary {
  instrument_id: number
  fetched_at: string | null
  model: string
  content: string
  citations: Citation[]
  outcome: ApiMessage
}

export interface FundamentalsRefreshReport {
  outcomes: ApiMessage[]
  updated: number
  skipped: number
  /** ETFs and CFDs — not a shortfall, a property of the instrument. */
  not_applicable: number
  failed: number
}

export interface FundamentalsRefreshStatus {
  running: boolean
  total: number
  done: number
  current_symbol: string | null
  started_at: string | null
  finished_at: string | null
  report: FundamentalsRefreshReport | null
}

/** Phase 1 of a real, backtestable Discovery prediction — deepening price
 * history so a technical/momentum model can later be trained and
 * validated (see DEVLOG "Decision 3u.22"). Deliberately price-only, never
 * fundamentals: `Fundamental` rows hold only each concept's latest known
 * figure, not a dated history, so using today's score to "predict" a past
 * return would be lookahead bias. */
export interface PredictionBackfillReport {
  updated: number
  failed: number
  bars_added: number
  already_running: boolean
}

export interface PredictionBackfillStatus {
  running: boolean
  total: number
  done: number
  current_symbol: string | null
  started_at: string | null
  finished_at: string | null
  report: PredictionBackfillReport | null
}

export interface FactorImportResult {
  imported: number
  already_present: number
}

/** One held position's Carhart four-factor exposure — explanatory
 * (what has historically driven this holding's returns), never
 * predictive. Region-matched: a US instrument is regressed against US
 * factors, a European one against Europe's — never mixed. See DEVLOG
 * "Decision 3u.24". */
export interface FactorLoadings {
  instrument: Instrument
  /** "US" | "EUROPE" | null when `not_applicable_reason` is set. */
  region: string | null
  n_observations: number
  start_date: string | null
  end_date: string | null
  alpha: number | null
  beta_mkt: number | null
  beta_smb: number | null
  beta_hml: number | null
  beta_mom: number | null
  r_squared: number | null
  alpha_p_value: number | null
  /** "no_region_match" | "insufficient_history" | null (regression ran). */
  not_applicable_reason: string | null
}

/** One timestamped snapshot of the live SQLite database — a plain file
 * copy, nothing more. See DEVLOG "Decision 3u.29". */
export interface Backup {
  filename: string
  created_at: string
  size_bytes: number
}

/** How a merged, cross-source split event was classified — see
 * `app/models.py::CorporateActionConfidence` and DEVLOG "Decision 3u.41".
 * Only the two `verified_*` values are ever auto-applied; the rest stay
 * visible only as `OutstandingCandidate` rows until promoted. Never render
 * this raw string in the UI — always go through
 * `corporateActions.confidence.{value}` so a beginner never sees a backend
 * enum name. */
export type CorporateActionConfidence =
  | 'verified_three_sources'
  | 'verified_cross_source'
  | 'candidate_single_source'
  | 'provider_conflict'
  | 'suspect_ticker_reuse'
  | 'manual_promotion'
  | 'manual'

/** One provider's raw observation contributing to a `CorporateAction`'s
 * `corroborating_sources` — the "detail de provenance" shown on demand,
 * separate from the compact confidence badge. */
export interface CorroboratingSource {
  provider: string
  event_date: string
  numerator: number
  denominator: number
}

/** A confirmed stock split or reverse split — see `app/corporate_actions/
 * service.py`. Raw `PriceBar`/`Lot` rows are never mutated; every
 * historical calculation applies this at read time instead. See DEVLOG
 * "Decision 3u.30"/"Decision 3u.41". */
export interface CorporateAction {
  id: number
  instrument: Instrument | null
  action_type: 'split' | 'reverse_split'
  effective_date: string
  ratio_numerator: number
  ratio_denominator: number
  source: 'fmp' | 'eodhd' | 'yahoo' | 'alpha_vantage' | 'polygon' | 'manual'
  /** Whether the cached price history for this instrument was found to
   * already reflect the split ("already_adjusted", never corrected again)
   * or confirmed unadjusted ("raw", corrected at read time). */
  price_history_status: 'raw' | 'already_adjusted' | 'not_applicable' | 'unknown'
  confidence: CorporateActionConfidence
  /** `null` for a `"manual"` entry — nothing to corroborate a hand-typed row with. */
  corroborating_sources: CorroboratingSource[] | null
  created_at: string
}

/** Result of one `POST /api/corporate-actions/detect` run — see
 * `app/corporate_actions/service.py::DetectionSummary`. `complete` is the
 * field to check before trusting `created`/`found`: a provider rate limit
 * can stop the scan partway through, and `created: 0` reads identically
 * whether nothing was found or nothing was checked. Never show "no splits
 * found" without also checking this flag. `verified_*`/`candidate_*`/
 * `provider_conflict`/`suspect_ticker_reuse` (DEVLOG "Decision 3u.41")
 * break `found` down by cross-source classification — count **events**,
 * never instruments (one instrument can carry several). */
export interface CorporateActionDetection {
  candidates: number
  checked: number
  found: number
  created: number
  already_known: number
  no_events: number
  rate_limited: number
  not_checked: number
  failed: number
  skipped: number
  recently_checked: number
  verified_three_sources: number
  verified_cross_source: number
  candidate_single_source: number
  provider_conflict: number
  suspect_ticker_reuse: number
  complete: boolean
  actions: CorporateAction[]
}

/** Read-only, no-provider-calls snapshot of automatic corporate-action
 * coverage — see `app/corporate_actions/service.py::CoverageSummary`.
 * Instrument counts and event counts are kept strictly separate: one
 * instrument (e.g. a stock with several historical splits) can contribute
 * several events. See DEVLOG "Step 3u.57". */
export interface CorporateActionCoverage {
  eligible_instruments: number
  excluded_instruments: number
  checked_instruments: number
  unchecked_instruments: number
  verified_three_sources_events: number
  verified_cross_source_events: number
  candidate_single_source_events: number
  provider_conflict_events: number
  suspect_ticker_reuse_events: number
}

/** One still-outstanding (never auto-applied, never manually promoted)
 * cross-source-merged event — see `app/corporate_actions/service.py::
 * OutstandingCandidate`. Read-only in this UI: promoting one still goes
 * through the raw per-provider candidate, not exposed here. */
export interface OutstandingCandidate {
  instrument: Instrument
  effective_date: string
  action_type: 'split' | 'reverse_split'
  ratio_numerator: number
  ratio_denominator: number
  confidence: CorporateActionConfidence
  providers: string[]
}

/** One execution of the targeted Alpha Vantage resume job — see
 * `app/models.py::CorporateActionResumeRun`. `skipped_reason` is set (and
 * every count stays 0) when the run did no real work: `"paused"` or
 * `"nothing_incomplete"`. See DEVLOG "Decision 3u.41". */
export interface CorporateActionResumeRun {
  id: number
  provider: string
  started_at: string
  finished_at: string | null
  skipped_reason: 'paused' | 'nothing_incomplete' | null
  targeted_instrument_ids: number[]
  checked: number
  rate_limited: number
  failed: number
  no_events: number
  verified_three_sources: number
  verified_cross_source: number
  candidate_single_source: number
  provider_conflict: number
  suspect_ticker_reuse: number
  complete: boolean
  remaining_incomplete: number
}

/** What the manual "Relancer la vérification Alpha Vantage" button reads
 * before the click — see `app/corporate_actions/service.py::get_resume_status`. */
export interface CorporateActionResumeStatus {
  enabled: boolean
  remaining_incomplete: number
  last_run: CorporateActionResumeRun | null
}

/** Result of one `POST /api/corporate-actions/detect-one` call — a
 * targeted, single-instrument check against one specific on-demand
 * source, never part of the bulk `/detect` scan above. `status`
 * distinguishes a genuine "no split" answer (`no_events`) from every
 * failure shape — a failure must never be presented as a confirmed
 * absence of split. See DEVLOG "Decision 3u.35". */
export interface DetectOneResult {
  instrument_id: number
  provider: string
  status: 'created' | 'already_known' | 'no_events' | 'not_supported' | 'plan_limited' | 'rate_limited' | 'failed'
  found: number
  created: number
  already_known: number
  actions: CorporateAction[]
}
