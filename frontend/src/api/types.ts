export type MappingStatus = 'RESOLVED' | 'MANUAL' | 'UNRESOLVED'

export interface Instrument {
  id: number
  broker_symbol: string
  provider_symbol: string | null
  mapping_status: MappingStatus
  name: string | null
  /** Catégorie fournie par le courtier : STOCK, ETF, CFD… */
  category: string | null
  currency: string | null
  country: string | null
  sector: string | null
}

export interface Position {
  id: number
  instrument: Instrument
  source: 'IMPORT' | 'MANUAL'
  /** Compte d'origine : « My Trades », « PEA »… */
  account: string | null
  quantity: number
  avg_price: number
  currency: string | null
  opened_at: string | null
  /** Nombre de lots agrégés dans cette position. */
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
}

export interface AccountTotals {
  account: string
  positions_count: number
  market_value: number | null
  invested_value: number | null
  unrealized_pl: number | null
  unrealized_pl_pct: number | null
}

export interface PortfolioTotals {
  base_currency: string
  positions_count: number
  market_value: number | null
  invested_value: number | null
  unrealized_pl: number | null
  unrealized_pl_pct: number | null
  has_incomplete_data: boolean
  excluded_positions: number
}

export interface Portfolio {
  totals: PortfolioTotals
  accounts: AccountTotals[]
  positions: Position[]
  unresolved_symbols: Instrument[]
  last_import_at: string | null
}

export interface ImportBatch {
  id: number
  filename: string
  imported_at: string
  positions_found: number
  transactions_found: number
  transactions_inserted: number
  warnings: string[]
  detected_sections: string[]
  accounts: string[]
}

export interface Health {
  status: string
  base_currency: string
  integrations: Record<string, boolean>
}
