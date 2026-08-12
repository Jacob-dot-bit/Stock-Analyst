import type { Catalogue } from './types'

/**
 * English catalogue — the reference.
 *
 * Every key defined here must exist in `fr.ts` and `pl.ts`; `index.tsx` checks this
 * at module load in development, so a forgotten translation surfaces immediately
 * rather than as a stray identifier in the UI.
 */
export const en: Catalogue = {
  // --- Shell ---------------------------------------------------------------
  'app.title': 'Stock Analyst',
  'nav.portfolio': 'Portfolio',
  'nav.watchlist': 'Watchlist',
  'nav.gems': 'Hidden gems',
  'language.label': 'Language',
  'app.disclaimer':
    'This tool produces indicators from public data; it is not investment advice. The decisions remain yours.',

  // --- Common --------------------------------------------------------------
  'common.ok': 'OK',
  'common.cancel': 'Cancel',
  'common.save': 'Save',
  'common.saving': 'Saving…',
  'common.add': 'Add',
  'common.delete': 'Delete',
  'common.loading': 'Loading…',
  'common.notComputable': 'not computable',
  'common.none': '—',

  // --- Portfolio page ------------------------------------------------------
  'portfolio.title': 'Portfolio',
  'portfolio.subtitle': 'Holdings and unrealised result.',
  'portfolio.lastImport': 'Last import: {date}.',
  'portfolio.openPositions': 'Open positions',

  'totals.positions': 'Positions',
  'totals.marketValue': 'Market value ({currency})',
  'totals.unrealized': 'Unrealised result ({currency})',
  'totals.performance': 'Performance',
  'totals.incomplete': {
    one: '{count} position has no valuation — typically a hand-entered row. It is excluded from the totals rather than counted as zero, which would give a wrong total that looks correct. Market prices arrive in the next phase of the project.',
    other:
      '{count} positions have no valuation — typically hand-entered rows. They are excluded from the totals rather than counted as zero, which would give a wrong total that looks correct. Market prices arrive in the next phase of the project.',
  },

  'accounts.title': 'By account',
  'accounts.account': 'Account',
  'accounts.positions': 'Positions',
  'accounts.invested': 'Invested',
  'accounts.value': 'Value',
  'accounts.unrealized': 'Unrealised',
  'accounts.performance': 'Perf.',

  // --- Import panel --------------------------------------------------------
  'import.title': 'Import an XTB statement',
  'import.instructions':
    'In xStation: Account history → Export → period "All", Excel format. XTB shut down its API on 14 March 2025, so exporting a file is the only reliable way to retrieve your positions. No credentials are asked for or stored.',
  'import.multiAccount':
    'One export covers a single account. If you hold several (brokerage and PEA, for instance), export them separately and import both files: they coexist without overwriting each other.',
  'import.dropzone': 'Drop the file here, or pick it manually (.xlsx or .csv)',
  'import.chooseFile': 'Choose a file',
  'import.importing': 'Importing…',
  'import.failed': 'Import failed: {error}',
  'import.summary':
    '{filename} — {positions} open position(s), {transactions} operation(s) detected, {inserted} of them new.',
  'import.sectionsTitle': 'Sheets detected in the file',
  'import.sectionLine': '{sheet} → {count} × {kind} ({rows} source rows)',

  'section.open_positions': 'open position',
  'section.closed_positions': 'closed position',
  'section.cash_operations': 'cash operation',
  'section.unknown': 'unrecognised block',

  // --- Backend message codes ----------------------------------------------
  // Rendered from {code, params} returned by the API. The backend stays
  // language-neutral so the same import can be read in any of these languages.
  'import.unsupportedFileType':
    'Unsupported "{extension}" file type. Export from xStation as Excel (.xlsx) or CSV.',
  'import.fileUnreadable': 'Unreadable file: {error}',
  'import.noTableRecognised':
    'No table recognised in this file. Check that it is a report exported from Account history.',
  'import.nothingImportable': 'No usable position or operation was found.',
  'import.unmappedColumns':
    'Unrecognised columns in "{sheet}": {columns}. Their values are stored but not used.',
  'import.positionSkipped': 'Position "{symbol}" skipped: volume or opening price unreadable.',
  'import.closedPositionSkipped':
    'Closed position "{symbol}" skipped: volume or opening price unreadable.',
  'import.unresolvedSymbols': {
    one: '{count} symbol has no provider mapping: {symbols}. Fix it below to enable its analysis.',
    other: '{count} symbols have no provider mapping: {symbols}. Fix them below to enable their analysis.',
  },

  // --- Symbol mapping ------------------------------------------------------
  'unresolved.title': {
    one: 'Symbol without a mapping ({count})',
    other: 'Symbols without a mapping ({count})',
  },
  'unresolved.description':
    'These instruments have no automatic mapping to a data provider: until corrected, they will not be analysed. CFDs on indices, commodities and currencies have no fundamentals — it is normal for them to stay unmapped.',
  'unresolved.brokerSymbol': 'XTB symbol',
  'unresolved.providerSymbol': 'Provider symbol (Yahoo format)',

  'mapping.confirmed': 'confirmed',
  'mapping.unverified': 'unverified',
  'mapping.toFix': 'needs fixing',
  'mapping.fix': 'fix',
  'mapping.unverifiedTooltip':
    'Automatic conversion of the listing suffix. The root of the symbol has not been checked against a provider.',
  'mapping.placeholder': 'e.g. ERIC-B.ST',

  'symbol.manualOverride': 'Mapping set manually.',
  'symbol.suffixConverted': 'Suffix .{suffix} converted to "{providerSuffix}".',
  'symbol.derivative': 'Derivative ({category}): no fundamentals, so no analysis applies.',
  'symbol.unknownFormat':
    'Symbol outside the expected "ROOT.COUNTRY" format, or unknown listing venue. Enter the provider symbol by hand if the instrument is covered.',
  'symbol.notAnEquity':
    'Not recognised as an equity (index, commodity, FX or crypto). Fundamental analysis does not apply.',

  // --- Manual position -----------------------------------------------------
  'manual.title': 'Hand-entered position',
  'manual.subtitle': 'For an instrument missing from the export, or held at another broker.',
  'manual.newTitle': 'New position',
  'manual.symbol': 'XTB symbol',
  'manual.quantity': 'Quantity',
  'manual.avgPrice': 'Average cost',
  'manual.currency': 'Currency',
  'manual.note':
    'A hand-entered position has no broker valuation: it will not count towards the totals until market prices are wired in.',

  // --- Positions table -----------------------------------------------------
  'table.instrument': 'Instrument',
  'table.mapping': 'Mapping',
  'table.quantity': 'Qty',
  'table.avgPrice': 'Average cost',
  'table.price': 'Price',
  'table.value': 'Value ({currency})',
  'table.unrealized': 'Unrealised ({currency})',
  'table.performance': 'Perf.',
  'table.since': 'Since',
  'table.account': 'Account',
  'table.empty': 'No positions. Import an XTB statement or add a row by hand.',
  'table.lots': {
    one: '{count} lot',
    other: '{count} lots',
  },
  'table.short': 'short',
  'table.manual': 'manual',

  'filters.account': 'Account',
  'filters.all': 'All',
  'filters.sortBy': 'Sort by',
  'sort.value': 'Market value',
  'sort.unrealized': 'Unrealised result',
  'sort.performance': 'Performance %',
  'sort.symbol': 'Symbol',

  // --- Prices ---------------------------------------------------------------
  'prices.title': 'Market prices',
  'prices.subtitle':
    'Free providers throttle heavily, so a refresh works through the list within a time budget and reports what is left. Data already stored is never re-fetched.',
  'prices.refresh': 'Refresh prices',
  'prices.refreshing': 'Refreshing…',
  'prices.summary': '{updated} updated, {skipped} already up to date, {failed} not retrieved.',
  'prices.remaining': {
    one: '{count} instrument still to go — click again to continue.',
    other: '{count} instruments still to go — click again to continue.',
  },
  'prices.updated': '{symbol}: {bars} new bar(s) from {provider}.',
  'prices.alreadyFresh': '{symbol}: already up to date.',
  'prices.notMapped': '{symbol}: no provider mapping, so nothing to fetch.',
  'prices.symbolNotFound': '{symbol}: unknown to {provider}. Check the provider symbol.',
  'prices.rateLimited': '{symbol}: {provider} is rate-limiting. Try again in a few minutes.',
  'prices.planLimited':
    '{symbol}: covered by {provider} only on a paid plan. The symbol is correct — nothing to fix here.',
  'prices.alreadyRunning':
    'A refresh is already running. Two at once double the quota spent for no benefit — wait for the first to finish.',
  'prices.stillUnavailable':
    '{symbol}: still no price data. Already asked today — no configured provider covers this market on its free plan.',
  'prices.noProvider': '{symbol}: no data provider is available.',
  'prices.failed': '{symbol}: retrieval failed via {provider}.',
  'prices.budgetReached': 'Time budget reached, {remaining} instrument(s) left.',
  'prices.noFallbackConfigured':
    'Yahoo is rate-limiting and no fallback provider is configured. Add a free TWELVEDATA_API_KEY to .env (email signup, no card) so refreshes keep working when Yahoo throttles.',
  'table.trend': 'Trend (90d)',
  'mapping.verified': 'verified',
  'mapping.verifiedTooltip': 'A provider returned data for this symbol on {date} ({provider}).',

  // --- Placeholder pages ---------------------------------------------------
  'watchlist.title': 'Watchlist',
  'watchlist.description': 'Instruments you follow without holding them, and entry timing.',
  'gems.title': 'Hidden gems',
  'gems.description': 'Finding promising stocks by screening an index universe.',
  'placeholder.comingIn': 'This page arrives in {phase} of the project.',
  'phase.4': 'phase 4',
  'phase.5': 'phase 5',
}
