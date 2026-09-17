import type {
  AllocationRow,
  AttentionItem,
  BackfillFigisResult,
  BackfillIsinsResult,
  BacktestReport,
  Backup,
  BreakdownDimension,
  BreakdownItem,
  CorporateAction,
  CorporateActionCoverage,
  CorporateActionDetection,
  CorporateActionResumeRun,
  CorporateActionResumeStatus,
  DataHealth,
  DetectOneResult,
  DiscoveryCandidate,
  DiscoveryFinvizResult,
  DiscoveryImportResult,
  DiscoveryRefreshResult,
  DividendDetailRow,
  DividendSummaryRow,
  Drawdown,
  EnrichSectorsResult,
  FactorImportResult,
  FactorLoadings,
  FundamentalsRefreshReport,
  FundamentalsRefreshStatus,
  Health,
  ImportBatch,
  ImportPreview,
  Instrument,
  InstrumentCommentary,
  JournalEntry,
  Liquidity,
  Lot,
  NewsSentiment,
  OnboardingStatus,
  OutstandingCandidate,
  PersonalPolicy,
  PersonalPolicyDraft,
  PersonalPolicyGap,
  PersonalPolicyLimit,
  PersonalPolicyLimitDraft,
  Portfolio,
  Position,
  PositionConcentration,
  PositionSignal,
  PredictionBackfillReport,
  PredictionBackfillStatus,
  ProviderAvailability,
  QuoteStatus,
  RefreshReport,
  RefreshStatus,
  Score,
  ScreenerCandidate,
  Sparkline,
  SymbolSearchResult,
  TaxYearSummary,
  Transaction,
  TransactionList,
  ValueHistory,
  WatchlistItem,
  WatchlistSignal,
} from './types'

/** Surface the backend's error message rather than an opaque "500". */
async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)

  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = await response.json()
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      // Non-JSON response: keep the HTTP status.
    }
    throw new Error(detail)
  }

  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export const api = {
  health: () => request<Health>('/api/health'),

  getPortfolio: () => request<Portfolio>('/api/portfolio'),

  // "xtb" | "mintos" | "mintos-investments" | "amundi" | "amundi-synthese" —
  // one preview-then-confirm flow shared by every broker importer, each
  // backed by its own parser but the identical ImportBatch/ImportPreview
  // response shape. "mintos-investments" and "amundi-synthese" are live
  // snapshots (Mintos's "Investments" .xlsx, Amundi's "Synthese" .xlsb) that
  // complement, not replace, their respective periodic PDF statements — see
  // DEVLOG "Decision 3u.43"/"Decision 3u.44".
  importBrokerFile: (
    kind: 'xtb' | 'mintos' | 'mintos-investments' | 'amundi' | 'amundi-synthese',
    file: File,
  ) => {
    const form = new FormData()
    form.append('file', file)
    return request<ImportBatch>(`/api/imports/${kind}`, { method: 'POST', body: form })
  },

  listImports: () => request<ImportBatch[]>('/api/imports'),

  previewBrokerFile: (
    kind: 'xtb' | 'mintos' | 'mintos-investments' | 'amundi' | 'amundi-synthese',
    file: File,
  ) => {
    const form = new FormData()
    form.append('file', file)
    return request<ImportPreview>(`/api/imports/${kind}/preview`, { method: 'POST', body: form })
  },

  undoImport: (importId: number) => request<void>(`/api/imports/${importId}`, { method: 'DELETE' }),

  createManualPosition: (payload: {
    broker_symbol: string
    quantity: number
    avg_price: number
    currency?: string | null
    comment?: string | null
  }) =>
    request<Position>('/api/portfolio/positions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  deletePosition: (id: number) =>
    request<void>(`/api/portfolio/positions/${id}`, { method: 'DELETE' }),

  deleteInstrument: (id: number) =>
    request<void>(`/api/portfolio/instruments/${id}`, { method: 'DELETE' }),

  refreshPrices: (force = false, symbols?: string[]) => {
    const params = new URLSearchParams({ force: String(force) })
    if (symbols && symbols.length > 0) params.set('symbols', symbols.join(','))
    return request<RefreshReport>(`/api/prices/refresh?${params.toString()}`, { method: 'POST' })
  },

  getRefreshStatus: () => request<RefreshStatus>('/api/prices/refresh/status'),

  getSparklines: () => request<Sparkline[]>('/api/prices/sparklines'),

  getProviderAvailability: () => request<ProviderAvailability[]>('/api/prices/providers'),

  getBreakdown: (by: BreakdownDimension) =>
    request<BreakdownItem[]>(`/api/portfolio/breakdown?by=${by}`),

  getAllocation: () => request<AllocationRow[]>('/api/portfolio/allocation'),

  setAllocationTarget: (category: string, payload: { min_pct: number; max_pct: number }) =>
    request<AllocationRow>(`/api/portfolio/allocation/${category}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  deleteAllocationTarget: (category: string) =>
    request<void>(`/api/portfolio/allocation/${category}`, { method: 'DELETE' }),

  getPersonalPolicy: () => request<PersonalPolicy>('/api/portfolio/policy'),

  setPersonalPolicy: (payload: PersonalPolicyDraft) =>
    request<PersonalPolicy>('/api/portfolio/policy', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  getPersonalPolicyLimits: () => request<PersonalPolicyLimit[]>('/api/portfolio/policy/limits'),

  createPersonalPolicyLimit: (payload: PersonalPolicyLimitDraft) =>
    request<PersonalPolicyLimit>('/api/portfolio/policy/limits', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  deletePersonalPolicyLimit: (id: number) =>
    request<void>(`/api/portfolio/policy/limits/${id}`, { method: 'DELETE' }),

  getPersonalPolicyGaps: () => request<PersonalPolicyGap[]>('/api/portfolio/policy/gaps'),

  getAttention: () => request<AttentionItem[]>('/api/portfolio/attention'),

  getDataHealth: () => request<DataHealth>('/api/portfolio/data-health'),

  getOnboardingStatus: () => request<OnboardingStatus>('/api/portfolio/onboarding'),

  getValueHistory: () => request<ValueHistory>('/api/portfolio/value-history'),

  getRiskConcentration: (limit = 10) =>
    request<PositionConcentration[]>(`/api/portfolio/risk/concentration?limit=${limit}`),

  getRiskLiquidity: () => request<Liquidity>('/api/portfolio/risk/liquidity'),

  getRiskDrawdown: () => request<Drawdown>('/api/portfolio/risk/drawdown'),

  getLots: (instrumentId: number) =>
    request<Lot[]>(`/api/portfolio/lots?instrument_id=${instrumentId}`),

  getTransactions: (params?: {
    type?: string[]
    startDate?: string
    endDate?: string
    instrumentId?: number
  }) => {
    const q = new URLSearchParams()
    params?.type?.forEach((t) => q.append('type', t))
    if (params?.startDate) q.set('start_date', params.startDate)
    if (params?.endDate) q.set('end_date', params.endDate)
    if (params?.instrumentId) q.set('instrument_id', String(params.instrumentId))
    const query = q.toString()
    return request<TransactionList>(`/api/transactions${query ? `?${query}` : ''}`)
  },

  getDividendSummary: () => request<DividendSummaryRow[]>('/api/dividends/summary'),

  getDividendDetail: (params?: { year?: number; account?: string; instrumentId?: number }) => {
    const q = new URLSearchParams()
    if (params?.year) q.set('year', String(params.year))
    if (params?.account) q.set('account', params.account)
    if (params?.instrumentId) q.set('instrument_id', String(params.instrumentId))
    const query = q.toString()
    return request<DividendDetailRow[]>(`/api/dividends/detail${query ? `?${query}` : ''}`)
  },

  getTaxYears: () => request<{ years: number[] }>('/api/tax/years'),

  getTaxSummary: (year: number) => request<TaxYearSummary>(`/api/tax/summary?year=${year}`),

  createBackup: () => request<Backup>('/api/backup', { method: 'POST' }),

  getBackups: () => request<Backup[]>('/api/backup'),

  restoreBackup: (filename: string) =>
    request<void>(`/api/backup/${encodeURIComponent(filename)}/restore`, { method: 'POST' }),

  getCorporateActions: (params?: { instrumentId?: number }) => {
    const q = new URLSearchParams()
    if (params?.instrumentId) q.set('instrument_id', String(params.instrumentId))
    const query = q.toString()
    return request<CorporateAction[]>(`/api/corporate-actions${query ? `?${query}` : ''}`)
  },

  createCorporateAction: (payload: {
    instrument_id: number
    action_type: 'split' | 'reverse_split'
    effective_date: string
    ratio_numerator: number
    ratio_denominator: number
  }) =>
    request<CorporateAction>('/api/corporate-actions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  deleteCorporateAction: (id: number) => request<void>(`/api/corporate-actions/${id}`, { method: 'DELETE' }),

  detectCorporateActions: () =>
    request<CorporateActionDetection>('/api/corporate-actions/detect', { method: 'POST' }),

  detectCorporateActionOne: (payload: { instrumentId: number; provider: 'eodhd' }) =>
    request<DetectOneResult>('/api/corporate-actions/detect-one', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ instrument_id: payload.instrumentId, provider: payload.provider }),
    }),

  getCorporateActionsCoverage: () =>
    request<CorporateActionCoverage>('/api/corporate-actions/coverage'),

  getOutstandingCorporateActionCandidates: () =>
    request<OutstandingCandidate[]>('/api/corporate-actions/outstanding'),

  getCorporateActionsResumeStatus: () =>
    request<CorporateActionResumeStatus>('/api/corporate-actions/resume/status?provider=alpha_vantage'),

  resumeAlphaVantageDetection: () =>
    request<CorporateActionResumeRun>(
      '/api/corporate-actions/detect/resume?provider=alpha_vantage&limit=20',
      { method: 'POST' },
    ),

  createTransaction: (payload: {
    type: string
    executed_at?: string | null
    amount: number
    currency?: string | null
    account?: string | null
    broker_symbol?: string | null
    comment?: string | null
  }) =>
    request<Transaction>('/api/transactions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  updateTransaction: (
    id: number,
    payload: Partial<{
      type: string
      executed_at: string | null
      amount: number
      currency: string | null
      account: string | null
      comment: string | null
    }>,
  ) =>
    request<Transaction>(`/api/transactions/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  deleteTransaction: (id: number) => request<void>(`/api/transactions/${id}`, { method: 'DELETE' }),

  enrichSectors: () =>
    request<EnrichSectorsResult>('/api/portfolio/enrich-sectors', { method: 'POST' }),

  backfillIsins: () =>
    request<BackfillIsinsResult>('/api/portfolio/backfill-isins', { method: 'POST' }),

  backfillFigis: () =>
    request<BackfillFigisResult>('/api/portfolio/backfill-figis', { method: 'POST' }),

  searchSymbols: (query: string) =>
    request<SymbolSearchResult[]>(`/api/portfolio/symbol-search?q=${encodeURIComponent(query)}`),

  refreshLivePrices: () => request<Portfolio>('/api/portfolio/refresh-live', { method: 'POST' }),

  getRefreshLiveStatus: () => request<QuoteStatus>('/api/portfolio/refresh-live/status'),

  setIsin: (payload: { broker_symbol: string; isin: string }) =>
    request<Instrument>('/api/portfolio/isin', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  setSymbolOverride: (payload: { broker_symbol: string; provider_symbol: string; note?: string }) =>
    request<Instrument>('/api/portfolio/symbol-overrides', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  getProviderStatus: () =>
    request<
      Array<{
        name: string
        enabled: boolean
        description?: string
        signup_url?: string | null
        has_api_key: boolean
      }>
    >('/api/settings/providers'),

  getApiKeysStatus: () =>
    request<Record<string, boolean>>('/api/settings/api-keys'),

  updateApiKeys: (payload: Record<string, string | null>) =>
    request<{ status: string; message: string }>('/api/settings/api-keys', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  verifyApiKey: (provider: string, apiKey?: string) =>
    request<{ valid: boolean; message: string }>('/api/settings/verify-key', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, api_key: apiKey || null }),
    }),

  getScores: () => request<Score[]>('/api/scoring/scores'),

  getPositionSignals: () => request<PositionSignal[]>('/api/portfolio/position-signals'),

  refreshFundamentals: (force = false) =>
    request<FundamentalsRefreshReport>(`/api/scoring/fundamentals/refresh?force=${force}`, {
      method: 'POST',
    }),

  getFundamentalsRefreshStatus: () =>
    request<FundamentalsRefreshStatus>('/api/scoring/fundamentals/refresh/status'),

  getWatchlist: () => request<WatchlistItem[]>('/api/watchlist'),

  addWatchlistItem: (payload: {
    broker_symbol: string
    currency?: string | null
    target_entry_price?: number | null
    note?: string | null
    company_name?: string | null
  }) =>
    request<WatchlistItem>('/api/watchlist', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  updateWatchlistItem: (
    id: number,
    payload: { target_entry_price?: number | null; note?: string | null; company_name?: string | null },
  ) =>
    request<WatchlistItem>(`/api/watchlist/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  deleteWatchlistItem: (id: number) => request<void>(`/api/watchlist/${id}`, { method: 'DELETE' }),

  getWatchlistScores: () => request<Score[]>('/api/watchlist/scores'),

  getJournalEntries: () => request<JournalEntry[]>('/api/journal'),

  addJournalEntry: (payload: { broker_symbol?: string | null; thesis: string; review_date?: string | null }) =>
    request<JournalEntry>('/api/journal', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  updateJournalEntry: (id: number, payload: { thesis: string; review_date: string | null }) =>
    request<JournalEntry>(`/api/journal/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  updateJournalEntryOutcome: (id: number, payload: { outcome_note: string | null }) =>
    request<JournalEntry>(`/api/journal/${id}/outcome`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  deleteJournalEntry: (id: number) => request<void>(`/api/journal/${id}`, { method: 'DELETE' }),

  getWatchlistSignals: () => request<WatchlistSignal[]>('/api/watchlist/signals'),

  getWatchlistSparklines: () => request<Sparkline[]>('/api/watchlist/sparklines'),

  getScreenerCandidates: () => request<ScreenerCandidate[]>('/api/screener'),

  addScreenerCandidate: (payload: {
    broker_symbol: string
    currency?: string | null
    company_name?: string | null
  }) =>
    request<ScreenerCandidate>('/api/screener', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  updateScreenerCandidate: (id: number, payload: { company_name?: string | null }) =>
    request<ScreenerCandidate>(`/api/screener/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  deleteScreenerCandidate: (id: number) => request<void>(`/api/screener/${id}`, { method: 'DELETE' }),

  getScreenerScores: () => request<Score[]>('/api/screener/scores'),

  getScreenerSparklines: () => request<Sparkline[]>('/api/screener/sparklines'),

  importSp500Universe: () => request<DiscoveryImportResult>('/api/discovery/import-sp500', { method: 'POST' }),

  refreshDiscovery: () => request<DiscoveryRefreshResult>('/api/discovery/refresh', { method: 'POST' }),

  backfillDiscoveryDividends: () =>
    request<DiscoveryRefreshResult>('/api/discovery/backfill-dividends', { method: 'POST' }),

  getDiscoveryCandidates: (rankBy: 'value' | 'growth', limit = 20) =>
    request<DiscoveryCandidate[]>(`/api/discovery/candidates?rank_by=${rankBy}&limit=${limit}`),

  scanFinvizPreset: (preset: 'insider_buys' | 'oversold') =>
    request<DiscoveryFinvizResult>(`/api/discovery/finviz?preset=${preset}`, { method: 'POST' }),

  backfillPredictionHistory: () =>
    request<PredictionBackfillReport>('/api/prediction/backfill-history', { method: 'POST' }),

  getPredictionBackfillStatus: () =>
    request<PredictionBackfillStatus>('/api/prediction/backfill-history/status'),

  runBacktest: () => request<BacktestReport>('/api/prediction/backtest', { method: 'POST' }),

  importFactorData: () => request<FactorImportResult>('/api/factors/import', { method: 'POST' }),

  getFactorLoadings: () => request<FactorLoadings[]>('/api/factors'),

  getInstrumentNews: (instrumentId: number) =>
    request<NewsSentiment>(`/api/insights/${instrumentId}/news`, { method: 'POST' }),

  getInstrumentCommentary: (instrumentId: number) =>
    request<InstrumentCommentary>(`/api/insights/${instrumentId}/commentary`, { method: 'POST' }),
}
