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
  'nav.transactions': 'Transactions',
  'nav.watchlist': 'Watchlist',
  'nav.gems': 'Hidden gems',
  'nav.taxPrep': 'Tax prep',
  'nav.risk': 'Risk',
  'nav.journal': 'Journal',
  'alerts.tooltip': {
    one: '{count} watchlist item at or below its target price',
    other: '{count} watchlist items at or below their target price',
  },
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
  'common.edit': 'Edit',
  'common.loading': 'Loading…',
  'common.notComputable': 'not computable',
  'common.notApplicable': 'not applicable',
  'common.none': '—',

  // --- Portfolio page ------------------------------------------------------
  'portfolio.title': 'Portfolio',
  'portfolio.subtitle': 'Holdings and unrealised result.',
  'portfolio.lastImport': 'Last import: {date}.',
  'portfolio.lastRefresh': 'Prices updated on {date} at {time}',
  'portfolio.openPositions': 'Open positions',
  'portfolio.manageData': 'Manage data',

  'totals.positions': 'Positions',
  'totals.marketValue': 'Market value ({currency})',
  'totals.unrealized': 'Unrealised result ({currency})',
  'totals.unrealizedTooltip':
    'Gap between the value at the last available price and your average purchase cost. Only becomes a realised result after a sale.',
  'totals.realized': 'Realised result ({currency})',
  'totals.performance': 'Performance',
  'totals.performanceTooltip': 'Unrealised result expressed as a percentage of invested value — not an annualised return.',
  'totals.incomplete': {
    one: '{count} position cannot be valued right now — price not fetched yet, unknown currency, or no FX rate available. It is excluded from the totals rather than counted as zero, which would give a wrong total that looks correct. Clicking "Refresh" may fix it.',
    other:
      '{count} positions cannot be valued right now — price not fetched yet, unknown currency, or no FX rate available. They are excluded from the totals rather than counted as zero, which would give a wrong total that looks correct. Clicking "Refresh" may fix it.',
  },
  'totals.staleDeclaredValuations':
    'The total includes one or more old declared valuations (Mintos, Amundi ESR…) — these positions are fully counted in the total, but their value may no longer reflect the current portfolio. See Data health for the detail.',

  'accounts.title': 'By account',
  'accounts.account': 'Account',
  'accounts.positions': 'Positions',
  'accounts.invested': 'Invested',
  'accounts.investedTooltip': "Cost basis as reported by the broker — does not move with the market.",
  'accounts.value': 'Value',
  'accounts.unrealized': 'Unrealised',
  'accounts.performance': 'Perf.',

  // --- Performance approximation caveats (DEVLOG "Decision 3u.47") ---------
  'performance.mintosInterestIncome':
    'Net gain = interest and bonuses received minus fees/tax, since {since} — a measure of real income, not a price gain like a stock.',
  'performance.amundiApproximateGain':
    'Approximate gain: a proportional share of "{account}"\'s gain, based on known deposits/employer match/profit-sharing since {since} — any year never imported is not counted, which can overstate this figure.',
  'performance.amundiRealGainSinceSnapshot':
    "This fund's real gain since {since}: computed from the last statement that disclosed its gain, since the quantity held hasn't changed since then.",

  // --- Declared valuation freshness (DEVLOG "Decision 3u.50") --------------
  'valuation.declaredFresh':
    'Value declared by {provider} as of {date} — the latest imported statement, within the expected window for this kind of source.',
  'valuation.declaredStale':
    'Value declared by {provider} as of {date} — the latest imported statement, but older than the expected window for this kind of source. It still counts toward the total; it may simply no longer reflect the current portfolio. Re-import a more recent statement to refresh it.',

  // --- Import panel --------------------------------------------------------
  'import.xtb.title': 'Import an XTB statement',
  'import.xtb.instructions':
    'In xStation: Account history → Export → period "All", Excel format. XTB shut down its API on 14 March 2025, so exporting a file is the only reliable way to retrieve your positions. No credentials are asked for or stored.',
  'import.xtb.multiAccount':
    'One export covers a single account. If you hold several (brokerage and PEA, for instance), export them separately and import both files: they coexist without overwriting each other.',
  'import.xtb.dropzone': 'Drop the file here, or pick it manually (.xlsx or .csv)',
  'import.mintos.title': 'Import a Mintos statement',
  'import.mintos.instructions':
    "Portfolio → Account Statement, one PDF per calendar quarter. No cumulative export exists: import every quarterly statement separately (order doesn't matter).",
  'import.mintos.multiAccount':
    'The statement covers two distinct portfolios: "Core ETF 90" ETFs become regular positions, and the "Mintos Core" loan portfolio becomes a single aggregate valued by Mintos itself.',
  'import.mintos.dropzone': 'Drop the file here, or pick it manually (.pdf)',
  'import.mintos-investments.title': 'Update the Mintos value (Investments export)',
  'import.mintos-investments.instructions':
    "On Mintos: My investments → Export (.xlsx). Unlike the quarterly PDF statement, this export gives the loan portfolio's real value as of the export date — useful for refreshing the amount without waiting for the next quarter.",
  'import.mintos-investments.multiAccount':
    'A more recent export always wins the displayed value, whether it comes from this file or the quarterly PDF statement — whichever of the two is newer is always the one shown.',
  'import.mintos-investments.dropzone': 'Drop the file here, or pick it manually (.xlsx)',
  'import.amundi.title': 'Import an Amundi ESR statement',
  'import.amundi.instructions':
    'Your amundi-ee.com account → annual statement (PDF). Each statement is a yearly snapshot, not a dated transaction history — import each year separately.',
  'import.amundi.multiAccount':
    "An older statement imported after a newer one never overwrites your current positions — it stays browsable in the import history below.",
  'import.amundi.dropzone': 'Drop the file here, or pick it manually (.pdf)',
  'import.amundi-synthese.title': 'Update the Amundi value (Synthese export)',
  'import.amundi-synthese.instructions':
    "On your amundi-ee.com account: 'Synthese' export (.xlsb). Unlike the annual PDF statement, this export gives each fund's real value as of the export date — useful for refreshing the amount without waiting for the next annual statement.",
  'import.amundi-synthese.multiAccount':
    'A more recent export always wins the displayed value, whether it comes from this file or the annual PDF statement — whichever of the two is newer is always the one shown.',
  'import.amundi-synthese.dropzone': 'Drop the file here, or pick it manually (.xlsb)',
  'import.chooseFile': 'Choose a file',
  'import.importing': 'Importing…',
  'import.failed': 'Import failed: {error}',
  'import.summary':
    '{filename} — {positions} open position(s), {transactions} operation(s) detected, {inserted} of them new.',
  'import.sectionsTitle': 'Sheets detected in the file',
  'import.sectionLine': '{sheet} → {count} × {kind} ({rows} source rows)',
  'import.previewTitle': "Preview — nothing has been saved yet.",
  'import.confirm': 'Confirm import',
  'import.cancel': 'Cancel',
  'import.historyTitle': 'Import history',
  'import.historyLine': '{date} — {filename} ({positions} position(s), {transactions} new operation(s))',
  'import.undo': 'Undo',

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
  'mapping.isinPlaceholder': 'ISIN (e.g. FR0000120271)',
  'mapping.isinHelp':
    'An ISIN unlocks the European price source. Find it on your broker page. It is never guessed: a wrong ISIN would return another company\u2019s prices.',
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
  'table.type': 'Type',
  'table.mapping': 'Mapping',
  'table.quantity': 'Qty',
  'table.avgPrice': 'Average cost',
  'table.avgPriceTooltip': 'Average amount paid per share across the recorded lots (cost basis).',
  'table.avgPriceNotApplicableTooltip':
    "Value declared by Mintos as of {date} — the net invested cost (contributions and auto-reinvested principal mixed together) cannot be isolated from the imported statements, so no cost basis or gain/loss is computed for this aggregate.",
  'table.price': 'Price',
  'table.value': 'Value ({currency})',
  'table.valueNotComputableTooltip': "This position isn't included in the totals until a usable price is available.",
  'table.deleteConfirm': 'Permanently delete the {symbol} position? This action cannot be undone.',
  'table.weight': 'Weight',
  'table.weightTooltip':
    'Share of this position in the currently computable portfolio value — non-priceable positions are excluded from the calculation. Above 15% is highlighted as a concentration risk.',

  // --- Price status badge ---
  'priceStatus.fresh': 'Price data is current.',
  'priceStatus.stale':
    'Price data has not been checked in a while — the value shown may not reflect the current market. Refresh to update.',
  'priceStatus.error': 'No provider has ever returned data for this symbol.',
  'priceStatus.not_priceable': 'This instrument has no market price by nature — see the position detail for the precise reason.',
  'priceStatus.unmapped': 'No data provider mapping yet — fix it below to enable price tracking.',
  'priceStatus.viaProvider': 'Verified via {provider} on {date}.',

  // --- Portfolio breakdown ---
  'breakdown.title': 'Portfolio breakdown',
  'breakdown.dimension.category': 'Asset class',
  'breakdown.dimension.currency': 'Currency',
  'breakdown.dimension.country': 'Country',
  'breakdown.dimension.sector': 'Sector',
  'breakdown.enrichSectors': 'Fetch sector data (FMP + Wikidata)',
  'breakdown.enriching': 'Fetching sectors…',
  'breakdown.enrichResult': '{enriched} enriched, {skipped} had no sector, {failed} failed.',
  'breakdown.empty': 'Not enough valued positions to compute a breakdown.',
  'breakdown.unknown': 'Unknown',
  'breakdown.other': 'Other',

  // --- ISIN duplicate detection (watchlist/screener) ------------------------
  'duplicates.backfillIsins': 'Look up missing company IDs',
  'duplicates.backfilling': 'Looking up…',
  'duplicates.backfillResult': '{checked} checked, {updated} updated.',
  'duplicates.backfillFigis': 'Look up missing OpenFIGI identity',
  'duplicates.backfillFigisResultMore': '{checked} checked, {remaining} remaining — click again to continue.',
  'duplicates.backfillFigisResultDone': '{checked} checked, none remaining.',

  // --- Position/watchlist signals -------------------------------------------
  // A fixed combination of the composite score and the allocation/target-price
  // gap — descriptive, never a trade instruction (see DEVLOG "Decision 3u.19").
  // Deliberately facts, not verbs — "Reinforce"/"Reduce" still read as
  // instructions even without saying "Buy"/"Sell" (see DEVLOG "Decision
  // 3u.19" addendum). Both convergence cases name the two conditions that
  // are true; neither tells you what to do about them.
  'signals.positionReinforceFact': 'High score · under-allocated',
  'signals.positionReduceFact': 'Low score · over-allocated',
  'signals.watchlistReinforceFact': 'High score · at/below target',
  'signals.hold': 'Nothing to flag',
  'signals.not_applicable': 'Insufficient data',
  'signals.band.high': 'high',
  'signals.band.mid': 'mid',
  'signals.band.low': 'low',
  'signals.band.none': 'no score',
  'signals.positionTooltip': 'Score {score}/100 ({band}) · {category} allocation: {state}. Compares this holding’s own score with its entire asset class’s allocation gap — not a full evaluation of this specific position.',
  'signals.watchlistTooltip': 'Score {score}/100 ({band}) · {distance} from your target entry price — a combination of two existing indicators, not a recommendation.',
  'breakdown.category.STOCK': 'Stocks',
  'breakdown.category.ETF': 'ETFs',
  'breakdown.category.CFD': 'CFDs',
  'breakdown.category.P2P': 'P2P loans',
  'breakdown.category.FUND': 'Employee savings funds',

  // --- Attention today ---
  'attention.title': 'To review today',
  'attention.allClear': 'Nothing to report right now.',
  'attention.unresolvedInstruments': {
    one: '{count} position has incomplete data',
    other: '{count} positions have incomplete data',
  },
  'attention.priceError': {
    one: '{count} position has no price available',
    other: '{count} positions have no price available',
  },
  'attention.priceStale': {
    one: "{count} position hasn't been refreshed recently",
    other: "{count} positions haven't been refreshed recently",
  },
  'attention.allocationUnder': 'Your {category} target is under-weighted by {gap} points',
  'attention.allocationOver': 'Your {category} target is over-weighted by {gap} points',

  // --- Data health ---
  'dataHealth.title': 'Data health',
  'dataHealth.subtitle':
    "For every held position: where its value comes from, as of what date, and whether its corporate actions are confirmed.",
  'dataHealth.empty': 'No open positions yet.',
  'dataHealth.figiDuplicates.title': 'Possible duplicates (OpenFIGI identity)',
  'dataHealth.figiDuplicates.hint':
    "These rows share the same OpenFIGI (share-class) identifier — probably the same company tracked under two different symbols. A fact, never auto-merged: check and decide for yourself.",
  'dataHealth.figiDuplicates.source.held': 'held',
  'dataHealth.figiDuplicates.source.watchlist': 'watchlist',
  'dataHealth.figiDuplicates.source.screener': 'hidden gems',
  'dataHealth.staleSince': 'last quote: {date}',
  'dataHealth.declaredSince': 'declared valuation as of: {date}',

  'dataHealth.summary.info': { one: '{count} reliable', other: '{count} reliable' },
  'dataHealth.summary.attention': { one: '{count} to watch', other: '{count} to watch' },
  'dataHealth.summary.actionRequired': { one: '{count} action needed', other: '{count} actions needed' },
  'dataHealth.summary.notApplicable': { one: '{count} not applicable', other: '{count} not applicable' },

  'dataHealth.column.instrument': 'Instrument',
  'dataHealth.column.valuation': 'Valuation',
  'dataHealth.column.corporateActions': 'Corporate actions',
  'dataHealth.column.severity': 'Quality',
  'dataHealth.column.recommendedAction': 'Useful action',

  'dataHealth.valuation.kind.market_price': 'Market price',
  'dataHealth.valuation.kind.declared_value': 'Declared value',
  'dataHealth.valuation.kind.unavailable': 'No value available',
  'dataHealth.valuation.freshness.stale': 'outdated',
  'dataHealth.valuation.freshness.unknown': 'never confirmed',

  'dataHealth.corporateActions.status.verified': 'Confirmed',
  'dataHealth.corporateActions.status.no_events': 'None found',
  'dataHealth.corporateActions.status.candidate_single_source': 'Found by one source — to confirm',
  'dataHealth.corporateActions.status.provider_conflict': 'Sources disagree',
  'dataHealth.corporateActions.status.suspect_ticker_reuse': "Symbol's history needs checking",
  'dataHealth.corporateActions.status.incomplete_coverage': 'Alpha Vantage coverage incomplete',
  'dataHealth.corporateActions.status.never_checked': 'Never checked',
  'dataHealth.corporateActions.eventCounts': '{confirmed} confirmed, {outstanding} to confirm',

  'dataHealth.severity.info': 'Information',
  'dataHealth.severity.attention': 'Attention',
  'dataHealth.severity.action_required': 'Action required',
  'dataHealth.severity.not_applicable': 'Not applicable',

  'dataHealth.action.fix_symbol': 'Fix the symbol',
  'dataHealth.action.refresh_quotes': 'Refresh quotes',
  'dataHealth.action.import_recent_statement': 'Import a recent statement',
  'dataHealth.action.resume_alpha_vantage': 'Resume the Alpha Vantage check',
  'dataHealth.action.verify_eodhd': 'Verify with EODHD',

  // --- Getting started checklist ---
  'onboarding.title': 'Getting started',
  'onboarding.dismiss': 'Dismiss',
  'onboarding.step.import': 'Import a transaction statement',
  'onboarding.why.import': 'reconstructs your real buy/sell history',
  'onboarding.step.refresh': 'Refresh prices',
  'onboarding.why.refresh': "updates your positions' current value",
  'onboarding.step.unresolved': 'Check unrecognized positions',
  'onboarding.why.unresolved': "a position with no provider match stays outside every analysis",
  'onboarding.step.fundamentals': 'Fetch fundamentals',
  'onboarding.why.fundamentals': 'lets the Value/Growth/Quality scores be computed',
  'onboarding.step.allocation': 'Set a target allocation',
  'onboarding.why.allocation': 'compares your portfolio against limits you set yourself',
  'onboarding.step.watchlist': 'Add a few instruments to watch',
  'onboarding.why.watchlist': "tracks instruments you're considering, without holding them",

  // --- Target allocation ---
  'allocation.title': 'Target allocation',
  'allocation.description':
    'Current split by asset class vs. a range you set yourself — descriptive only, never a suggestion to buy or sell a specific security.',
  'allocation.empty': 'No valued positions yet to compare against a target.',
  'allocation.category': 'Asset class',
  'allocation.current': 'Current',
  'allocation.target': 'Target range',
  'allocation.gap': 'Status',
  'allocation.gapTooltip': "Comparison against your own allocation targets — not a suggestion to buy or sell.",
  'allocation.amount': 'To reach the minimum',
  'allocation.state.within': 'Within range',
  'allocation.state.under': 'Under',
  'allocation.state.over': 'Over',
  'allocation.state.no_target': 'No target set',
  'allocation.amountToInvest':
    'About {amount} in new contributions would reach the minimum of this range — a static estimate assuming prices and the rest of the portfolio stay as they are now, nothing sold.',
  'allocation.invalidRange': 'Enter a valid range: 0–100, minimum not above maximum.',
  'allocation.setTarget': 'Set target',

  // --- Personal policy ---
  'policy.title': 'Personal policy',
  'policy.subtitle':
    "Your own decision rules — objective, horizon, liquidity, risk tolerance and concentration limits. The tool compares the portfolio against these rules and flags gaps; it never recommends a buy or a sell.",
  'policy.edit': 'Edit my policy',
  'policy.empty': 'No personal policy defined yet. Click "Edit my policy" to set one.',

  'policy.objective': 'Objective',
  'policy.objective.growth': 'Growth',
  'policy.objective.income': 'Income',
  'policy.objective.preservation': 'Capital preservation',
  'policy.objectiveNote': 'Free note',

  'policy.horizon': 'Horizon',
  'policy.horizon.short': 'Short term',
  'policy.horizon.medium': 'Medium term',
  'policy.horizon.long': 'Long term',
  'policy.horizonTargetDate': 'Target date',

  'policy.liquidity': 'Liquidity',
  'policy.liquidityAmount': 'Expected amount',
  'policy.liquidityDate': 'Expected date',
  'policy.liquidityNote': 'Free note',

  'policy.riskTolerance': 'Risk tolerance and loss capacity',
  'policy.riskToleranceNote': 'Tolerance (free text)',
  'policy.lossCapacityPct': 'Maximum acceptable loss (%)',
  'policy.lossCapacityValue': 'maximum acceptable loss: {pct}%',

  'policy.limits.title': 'Personal limits',
  'policy.limits.subtitle':
    'Your own concentration thresholds — by line, sector, country, currency or asset type. A breach is a fact, never a buy or sell instruction.',
  'policy.limits.dimension': 'Dimension',
  'policy.limits.target': 'Target',
  'policy.limits.range': 'Range',
  'policy.limits.min': 'Min %',
  'policy.limits.max': 'Max %',
  'policy.limits.targetPlaceholder.sector': 'Technology',
  'policy.limits.targetPlaceholder.country': 'France',
  'policy.limits.targetPlaceholder.currency': 'USD',
  'policy.limits.targetPlaceholder.category': 'STOCK',

  'policy.dimension.line': 'Per line',
  'policy.dimension.sector': 'Sector',
  'policy.dimension.country': 'Country',
  'policy.dimension.currency': 'Currency',
  'policy.dimension.category': 'Asset type',
  'policy.dimension.declared_valuation': 'Declared valuations',

  'policy.gaps.allWithin': 'All your personal limits are currently satisfied.',
  'policy.gaps.disclaimer': 'These are facts, not a suggestion to buy or sell anything.',
  'policy.gaps.yourLimit': 'your limit: {range}',

  // --- Value history ---
  'history.title': 'Value over time',
  'history.value': 'Value',
  'history.invested': 'Invested',
  'history.benchmark': 'Benchmark',
  'history.caveat':
    "A real reconstruction from your actual buys/sells, not a simulation of today's holdings replayed into the past. CFDs cannot be included (their quantity is a contract count, not a share count).",
  'history.benchmarkCaveat':
    "The dashed line isn't a simple price ratio: it simulates what the same money, invested in the benchmark on the same dates (sales included), would be worth today.",
  'history.capped':
    'History starts on {date} — the depth of cached price history, not the date of your first purchase.',
  'history.empty': 'Not enough data yet (lots or cached prices) to reconstruct a history.',

  'table.unrealized': 'Unrealised ({currency})',
  'table.performance': 'Perf.',
  'table.score': 'Score',
  'table.scoreTooltip':
    'Composite score blending Value (30%), Growth (25%), Quality (25%) and Technical (20%) by default — reweighted per holding when a pillar has no data. Click a badge for this holding’s actual breakdown.',
  'table.signal': 'Signal',
  'table.since': 'Since',
  'table.account': 'Account',
  'table.insights': 'Insights',
  'table.empty': 'No positions. Import an XTB statement or add a row by hand.',
  'table.lots': {
    one: '{count} lot',
    other: '{count} lots',
  },
  'table.short': 'short',
  'table.manual': 'manual',

  'filters.account': 'Account',
  'filters.all': 'All',
  'filters.type': 'Type',
  'filters.dateFrom': 'From',
  'filters.dateTo': 'To',
  'filters.search': 'Search',
  'filters.priceMin': 'Min price',
  'filters.priceMax': 'Max price',
  'filters.capMin': 'Min market cap',
  'filters.capMax': 'Max market cap',
  'filters.debtMax': 'Max debt/equity',
  'filters.historyMin': 'Min history (years)',
  'filters.dividendMin': 'Min dividend yield (%)',
  'filters.scoreMin': 'Min composite score',
  'table.columns': 'Columns',

  // --- Transactions ----------------------------------------------------------
  'transactions.title': 'Transactions',
  'transactions.subtitle':
    'Dividends, fees, buys/sells and cash movements as imported — the summary below reflects the active filters, not the all-time total.',
  'transactions.viewDividends': 'View dividends by account and year →',
  'transactions.date': 'Date',
  'transactions.type': 'Type',
  'transactions.instrument': 'Instrument',
  'transactions.account': 'Account',
  'transactions.amount': 'Amount',
  'transactions.comment': 'Comment',
  'transactions.empty': 'No transactions for these filters.',
  'transactions.summary.netDividends': 'Net dividends',
  'transactions.summary.grossAndTax': 'Gross {gross} · withholding tax {tax}',
  'transactions.summary.fees': 'Total fees',
  'transactions.summary.realizedPl': 'Realised P&L',
  'transactions.summary.effectSplit': 'Instrument effect {instrument} · Currency & fees {currency}',
  'transactions.summary.effectCoverage':
    '({resolved} of {total} closed trades — the rest, mostly CFDs, have no conversion-rate data to split)',
  'transactions.instrumentEffect': 'Instrument effect',
  'transactions.instrumentEffectTooltip':
    'The instrument’s own price move, at the exchange rate when the trade opened — one of the two halves of the realized P&L. Only shown for closed trades.',
  'transactions.currencyEffect': 'Currency & fees',
  'transactions.currencyEffectTooltip':
    'The rest of the P&L once the instrument’s own price move (at the exchange rate when the trade opened) is set aside — mostly the exchange-rate move since then, plus commission/swap. Only shown for closed trades where the broker export included both conversion rates.',
  'transactions.group.all': 'All',
  'transactions.group.dividends': 'Dividends',
  'transactions.group.trades': 'Buys/sells',
  'transactions.group.fees': 'Fees',
  'transactions.group.cash': 'Cash',
  'transactions.type.BUY': 'Buy',
  'transactions.type.SELL': 'Sell',
  'transactions.type.CLOSED_TRADE': 'Closed position',
  'transactions.type.DIVIDEND': 'Dividend',
  'transactions.type.TAX': 'Withholding tax',
  'transactions.type.FEE': 'Fee',
  'transactions.type.DEPOSIT': 'Deposit',
  'transactions.type.WITHDRAWAL': 'Withdrawal',
  'transactions.type.INTEREST': 'Interest',
  'transactions.type.OTHER': 'Other',
  // Mintos Core (P2P) aggregate flows — deliberately distinct from the
  // regular DEPOSIT/WITHDRAWAL/INTEREST labels above, since these are
  // internal auto-invest movements, not cash the investor put in or took
  // out. See DEVLOG "Decision 3u.39"/"Decision 3u.77".
  'transactions.type.P2P_INVESTMENT': 'P2P loan (reinvested)',
  'transactions.type.P2P_PRINCIPAL_REPAYMENT': 'Principal repayment (P2P)',
  'transactions.type.P2P_INTEREST': 'P2P interest',
  'transactions.type.P2P_FEE': 'P2P fee',
  'transactions.type.P2P_SNAPSHOT': 'P2P valuation (statement)',
  'transactions.actions': 'Actions',
  'transactions.manual.title': 'Hand-entered transaction',
  'transactions.manual.subtitle':
    'A dividend, fee or cash movement missing from an import — never a buy/sell (see note below).',
  'transactions.manual.newTitle': 'New transaction',
  'transactions.manual.note':
    "Buys, sells and closed positions aren't offered here — add or correct a holding instead, from the Portfolio page.",
  'transactions.invalidAmount': 'Enter a valid amount.',

  // --- Prices ---------------------------------------------------------------
  'prices.title': 'Price update',
  'prices.subtitle':
    'Free providers throttle heavily, so each click works through the list within a time budget and reports what is left. One button updates the history (trend charts below), then live quotes — the portfolio totals above update along with it. Only the cost basis (Invested) still comes from your broker.',
  'prices.phaseHistory': 'Step 1/2 — Price history',
  'prices.phaseLive': 'Step 2/2 — Live quotes',
  'prices.refresh': 'Refresh',
  'prices.refreshing': 'Refreshing…',
  'prices.progress': '{done} / {total} instruments processed',
  'prices.retryFailed': {
    one: 'Retry the failed instrument ({count})',
    other: 'Retry failed instruments ({count})',
  },
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
  'prices.needsIsin':
    '{symbol}: no price source could even try — none of them has an identifier for it. Add its ISIN on the row (find it on your broker\u2019s instrument page) and it will be attempted on the next refresh.',
  'prices.notPriceable':
    '{symbol}: no market price exists for this instrument. A non-transferable right from a corporate action cannot be bought or sold, so no source anywhere quotes it.',
  'prices.noProvider': '{symbol}: no data provider is available.',
  'prices.failed': '{symbol}: retrieval failed via {provider}.',
  'prices.budgetReached': 'Time budget reached, {remaining} instrument(s) left.',
  'prices.noFallbackConfigured':
    'Yahoo is rate-limiting and no fallback provider is configured. Add a free TWELVEDATA_API_KEY to .env (email signup, no card) so refreshes keep working when Yahoo throttles.',

  'fundamentals.updated': '{symbol}: {concepts} figure(s) fetched from {provider}.',
  'fundamentals.alreadyFresh': '{symbol}: already up to date.',
  'fundamentals.notApplicable': '{symbol}: not a company — no fundamentals exist for it.',
  'fundamentals.noProvider': '{symbol}: SEC EDGAR is not configured (missing SEC_USER_AGENT).',
  'fundamentals.symbolNotFound': '{symbol}: not found in the SEC filer index.',
  'fundamentals.rateLimited': '{symbol}: SEC EDGAR is rate-limiting. Try again shortly.',
  'fundamentals.failed': '{symbol}: retrieval failed ({error}).',

  'table.trend': 'Trend (90d)',
  'mapping.verified': 'verified',
  'mapping.verifiedTooltip': 'A provider returned data for this symbol on {date} ({provider}).',

  // --- Settings page -------------------------------------------------------
  'settings.title': 'Settings',
  'settings.subtitle': 'Manage API keys and data sources.',
  'settings.groupPortfolioData.title': 'Portfolio data',
  'settings.groupPortfolioData.subtitle':
    'Import, complete, and refresh the data used in your tracking.',
  'settings.groupIntegrity.title': 'Integrity and corrections',
  'settings.groupIntegrity.subtitle':
    'Correct symbols or record corporate actions that affect the historical record.',
  'settings.groupBackup.title': 'Backup',
  'settings.groupDataSources.title': 'Data sources',
  'settings.groupDataSources.subtitle':
    'Configure the providers used for prices, fundamentals, and exchange rates.',
  'settings.description':
    'These API keys are stored locally in your .env file and never sent anywhere. Add keys to enable additional price providers and maximize redundancy if one source rate-limits.',
  'settings.providerStatus': 'Data provider status',
  'settings.apiKey': 'API key',
  'settings.secEdgarName': 'SEC EDGAR',
  'settings.contactInfo': 'Contact info',
  'settings.contactInfoSet': 'Already configured',
  'settings.noContactInfo': 'Your name and email',
  'settings.contactInfoFormat':
    'Format: your name, a space, then an email — e.g. "Jane Doe jane@example.com". Sent to SEC on every request (their requirement, not this app’s); any real address works, a disposable one is fine.',
  'settings.test': 'Test',
  'settings.testing': 'Testing…',
  'settings.getFreeKey': 'Get a free key',
  'settings.learnMore': 'Learn more',
  'settings.keylessNote': 'Also active, no setup needed: {names}.',
  'settings.noKey': 'Not configured',
  'settings.enabled': 'Enabled',
  'settings.disabled': 'Disabled',
  'settings.saved': 'Settings saved successfully. The backend has reloaded your configuration.',
  'settings.error': 'Failed to save settings: {error}',
  'settings.supportsFree': 'Free tier: {limit}',
  'settings.coolingDown': 'Rate-limited',
  'settings.coolingDownTooltip':
    'This source hit its rate limit recently and is temporarily paused — it clears itself after a short wait.',
  'settings.coverage': '{served}/{total} of your holdings',
  'settings.quotaUsed': '{used}/{limit} used {period}',
  'settings.periodDay': 'today',
  'settings.periodMonth': 'this month',
  'settings.periodMinute': 'this minute',

  // Descriptions for each provider
  'provider.description.yahoo': 'Yahoo Finance — worldwide, no key required',
  'provider.description.polygon': 'Polygon.io — US + crypto, 5 req/min',
  'provider.description.alpha_vantage': 'Alpha Vantage — worldwide, 5 req/min',
  'provider.description.boursorama': 'Boursorama — Euronext Paris, no key required',
  'provider.description.frankfurt': 'Boerse Frankfurt — European ISIN, no key required',
  'provider.description.twelvedata': 'Twelve Data — US fallback, 800 req/day',
  'provider.description.fmp': 'Financial Modeling Prep — Euronext, 250 req/day',
  'provider.description.tiingo': 'Tiingo — worldwide, 500 req/day',
  'provider.description.barchart': 'Barchart — worldwide, 400 req/day',
  'provider.description.intrinio': 'Intrinio — US + Canada, 500 req/day',
  'provider.description.eodhd': 'EODHD — 150+ global exchanges, 20 req/day',
  'provider.description.eoddata': 'Eoddata — stocks/crypto/forex, no key required',
  'provider.description.finviz': 'Finviz — US stocks via scraping (fragile)',

  // --- Watchlist ------------------------------------------------------------
  'watchlist.title': 'Watchlist',
  'watchlist.description': 'Instruments you follow without holding them, and entry timing.',
  'watchlist.openItems': 'Watched instruments',
  'watchlist.targetPrice': 'Target entry price',
  'watchlist.distanceToTarget': 'Distance to target',
  'watchlist.distanceToTargetTooltip':
    'Gap between the current price and your own target entry price — not a performance figure: a negative gap means the price is below your target.',
  'watchlist.note': 'Note',
  'watchlist.addedOn': 'Added',
  'watchlist.invalidTarget': 'Enter a valid target price, or leave it blank.',
  'watchlist.empty': 'Nothing on your watchlist yet — add a symbol above to start tracking it.',
  'watchlist.form.title': 'Add to watchlist',
  'watchlist.form.subtitle': "Track a symbol you don't hold yet, with an optional target entry price.",
  'watchlist.form.newTitle': 'New watchlist item',
  'watchlist.form.symbol': 'Symbol',
  'watchlist.form.companyName': 'Company name (optional)',
  'watchlist.form.companyNamePlaceholder': 'e.g. LVMH',
  'watchlist.form.targetPrice': 'Target entry price (optional)',
  'watchlist.form.targetPriceTooltip': 'Your own reference — never suggested by the app.',
  'watchlist.form.note': 'Note (optional)',

  // --- Hidden gems screener (phase 5) ---------------------------------------
  'gems.title': 'Hidden gems',
  'gems.description': 'A hand-picked list of candidates, ranked by score, to spot promising stocks you don’t already own or watch.',
  'gems.priceFilterTitle': 'Price filter',
  'gems.priceFilterHint': 'Applied to every list on this page — Candidates, the S&P 500 universe and Finviz scans.',
  'gems.candidates': 'Candidates',
  'gems.empty': 'No candidates yet — add a symbol above to start screening it.',
  'gems.form.title': 'Add a candidate',
  'gems.form.subtitle': 'Screen a symbol you don’t already hold or watch.',
  'gems.form.newTitle': 'New candidate',
  'gems.form.symbol': 'Symbol',
  'gems.form.companyName': 'Company name (optional)',
  'gems.form.companyNamePlaceholder': 'e.g. LVMH',

  // --- Discovery (automated candidate search, phase 7) ----------------------
  'discovery.title': 'Discovery',
  'discovery.description':
    "Automated candidate search. Each candidate gets an automatic Buy/Hold/Sell verdict, mechanically derived from its existing composite score — not a real investment recommendation.",
  'discovery.empty': 'Nothing to show yet.',
  'discovery.recommendationColumn': 'Verdict',
  'discovery.recommendationTooltip':
    'Mechanically derived from the existing composite score — not a real investment recommendation.',
  'discovery.recommendation.buy': 'Buy',
  'discovery.recommendation.hold': 'Hold',
  'discovery.recommendation.sell': 'Sell',
  'discovery.recommendation.none': 'No data',
  'discovery.verdictFilterLabel': 'Verdict filter',
  'discovery.verdictFilterHint':
    'Applied to the S&P 500 ranking and Finviz scans below — the hand-picked candidates above have no verdict to filter by.',
  'discovery.dataQualityFilterLabel': 'Data quality',
  'discovery.dataQualityFilterOption': 'Only show candidates with reliable data',
  'discovery.dataQualityFilterHint':
    'Requires a computed score, a fresh and correctly mapped price, and no pending corporate-action check.',
  'discovery.marketSectorFilterLabel': 'Country and sector',
  'discovery.marketSectorFilterHint':
    'Applied to the S&P 500 ranking and Finviz scans below — the hand-picked candidates above have no country/sector filter yet. Options reflect what is currently loaded.',
  'discovery.marketCapFilterLabel': 'Market cap',
  'discovery.marketCapFilterHint':
    "Applied to the S&P 500 ranking and Finviz scans below — the hand-picked candidates above have no computed market cap. An approximation (weighted-average diluted shares × price), good enough to filter with, not for accounting use.",
  'discovery.debtRatioFilterLabel': 'Debt',
  'discovery.debtRatioFilterHint':
    'Debt-to-equity ratio, already computed for the Value pillar — long-term debt only. Applied to the S&P 500 ranking and Finviz scans below, not the hand-picked candidates above.',
  'discovery.historyFilterLabel': 'Minimum price history',
  'discovery.historyFilterHint':
    "Roughly how many years of cached price history exist for the instrument — a data-sufficiency requirement, not a judgment of the company itself. Applied to the S&P 500 ranking and Finviz scans below.",
  'discovery.dividendFilterLabel': 'Dividend yield',
  'discovery.dividendFilterHint':
    "Estimated from filed dividends per share divided by price — a company-level estimate, different from the real yield already computed for your held positions. Applied to the S&P 500 ranking and Finviz scans below. Needs \"Backfill dividend data\" clicked at least once for candidates already evaluated.",
  'discovery.scoreFilterLabel': 'Minimum composite score',
  'discovery.scoreFilterHint':
    "Hides candidates whose composite score (0-100) is below this threshold — a candidate with no computed score at all (insufficient data) is hidden too, not shown as if it cleared the bar. Applied to the S&P 500 ranking and Finviz scans below.",
  'discovery.rankByValue': 'Rank by Value',
  'discovery.rankByGrowth': 'Rank by Growth',
  'discovery.valueScore': 'Value',
  'discovery.valueScoreTooltip': 'One pillar of the composite score — not a standalone rating.',
  'discovery.growthScore': 'Growth',
  'discovery.growthScoreTooltip': 'One pillar of the composite score — not a standalone rating.',
  'discovery.marketCap': 'Market cap',
  'discovery.debtRatio': 'Debt/equity',
  'discovery.dividendYield': 'Dividend yield',
  'discovery.backfillDividends': 'Backfill dividend data',
  'discovery.importResult': '{imported} imported, {alreadyPresent} already present.',
  'discovery.refreshResultMore': '{evaluated} evaluated, {remaining} remaining — click again to continue.',
  'discovery.refreshResultDone': '{evaluated} evaluated, none remaining.',
  'discovery.sp500.title': 'S&P 500 universe',
  'discovery.sp500.description':
    'A static list of the S&P 500\'s constituents, scored with the same Value/Growth pillars used everywhere else in this app.',
  'discovery.sp500.import': 'Import the S&P 500 universe',
  'discovery.sp500.refresh': 'Evaluate next batch',
  'discovery.finviz.title': 'Finviz preset scans',
  'discovery.finviz.description':
    'A different, narrower signal — insider buying and technical oversold conditions — never blended into the Value/Growth scores above.',
  'discovery.finviz.insiderBuys': 'Insider buys',
  'discovery.finviz.oversold': 'Oversold',
  'discovery.finviz.slowNotice':
    'Each scan resolves price and fundamentals for every result one by one — can take a few minutes for ~10 candidates.',
  'discovery.finviz.failedCount': '{count} candidate(s) could not be resolved and were skipped.',
  'discovery.finviz.scanningNotice':
    'Scan in progress — free-tier providers can take several minutes. Don\'t close this page.',

  'prediction.title': 'Price history',
  'prediction.description':
    'A real predictive model needs a proper backtest, which needs deeper price history than this app normally keeps. This step pulls several years of daily bars for the instruments already priced — price only, since fundamentals aren\'t stored with a dated history yet and using today\'s score to "predict" a past return would be lookahead bias. See "Backtest" below for what the model does with this data.',
  'prediction.backfill': 'Backfill price history',
  'prediction.running': 'Backfilling…',
  'prediction.alreadyRunning': 'A backfill is already running.',
  'prediction.backfillResult': '{updated} updated, {failed} failed, {barsAdded} new bars stored.',
  'backtest.title': 'Backtest',
  'backtest.description':
    'A simple, price-only technical model (momentum, moving averages, realized volatility), trained fresh on every run and evaluated strictly on data after its training period ends — never a per-instrument prediction, only the model\'s own historical accuracy.',
  'backtest.run': 'Run backtest',
  'backtest.running': 'Running…',
  'backtest.disclaimer':
    'This is one historical evaluation, not proof of a real trading edge. The model sees price only — no fundamentals, no news, no judgment — and past results say nothing certain about the future.',
  'backtest.instrumentsUsed': 'Instruments used',
  'backtest.trainPeriod': 'Training period (samples)',
  'backtest.testPeriod': 'Test period (samples)',
  'backtest.singleClassWarning':
    'The training period moved in only one direction (e.g. an uninterrupted uptrend) — no meaningful model could be fit, so no accuracy is reported.',
  'backtest.testAccuracy': 'Accuracy on the test period',
  'backtest.avgReturnUp': 'Avg. realized return — predicted up',
  'backtest.avgReturnDown': 'Avg. realized return — predicted down',
  'backtest.lowSampleWarning': 'The test period has too few samples to trust this accuracy figure.',

  'factors.title': 'Factor exposure (Carhart four-factor model)',
  'factors.description':
    'Explanatory, not predictive: what has historically driven each holding\'s daily returns — Market, Size, Value, and Momentum — from Kenneth French\'s public factor data. Held positions only, region-matched (a US holding against US factors, a European one against Europe\'s).',
  'factors.import': 'Import factor data',
  'factors.importResult': '{imported} imported, {alreadyPresent} already present.',
  'factors.empty': 'No held position could be region-matched yet.',
  'factors.region': 'Region',
  'factors.alpha': 'Alpha',
  'factors.alphaTooltip': 'Daily excess return unexplained by the four factors — the regression\'s intercept.',
  'factors.betaMkt': 'Market',
  'factors.betaMktTooltip': 'Sensitivity to overall market excess return (Mkt-RF).',
  'factors.betaSmb': 'Size',
  'factors.betaSmbTooltip': 'Sensitivity to small-cap vs large-cap returns (SMB).',
  'factors.betaHml': 'Value',
  'factors.betaHmlTooltip': 'Sensitivity to high vs low book-to-market returns (HML).',
  'factors.betaMom': 'Momentum',
  'factors.betaMomTooltip': 'Sensitivity to recent-winner vs recent-loser returns (Mom/WML).',
  'factors.rSquared': 'R²',
  'factors.rSquaredTooltip': 'Share of daily return variance explained by the four factors together.',
  'factors.observations': 'Days',
  'factors.notApplicable.no_region_match':
    'No published daily factor series covers this instrument\'s country.',
  'factors.notApplicable.insufficient_history':
    'Not enough overlapping price and factor history yet.',

  // --- Scoring engine (phase 3) --------------------------------------------
  'scores.refreshTitle': 'Fundamentals',
  'scores.refreshSubtitle':
    'Fetch company financials from SEC EDGAR (US) and ESEF (Europe) to power the Value/Growth/Quality scores.',
  'scores.refresh': 'Fetch fundamentals',
  'scores.refreshing': 'Fetching…',
  'scores.refreshSummary':
    '{updated} updated, {skipped} already up to date, {notApplicable} not applicable, {failed} not retrieved.',
  'fundamentals.alreadyRunning':
    'A fundamentals refresh is already running. Two at once double the requests spent for no benefit — wait for the first to finish.',
  'scores.compositeTooltip': 'Composite score: {score}/100',
  'scores.notAdvice': "Summarizes the available indicators. This isn't an investment recommendation.",
  'scores.clickForDetail': 'Click to see the criteria, the data used, and anything dropped.',
  'scores.summarySentence': 'Score {score}/100: {band}.',
  'scores.summary.high': 'indicators are broadly favorable based on available data',
  'scores.summary.mid': 'indicators are mixed based on available data',
  'scores.summary.low': 'indicators are broadly unfavorable based on available data',
  'scores.strengths': 'Strengths',
  'scores.watchPoints': 'Watch points',
  'scores.noneIdentified': 'None for now',
  'scores.pillarScore': '{score}/100 ({weight}% of composite)',
  'scores.pillarScoreTooltip': '{pillar}: {score}/100 ({weight}%)',
  'scores.pillarDropped': 'No data',
  'scores.binaryPass': 'Pass',
  'scores.binaryFail': 'Fail',
  'scores.pillar.value': 'Value',
  'scores.pillar.growth': 'Growth',
  'scores.pillar.quality': 'Quality',
  'scores.pillar.technical': 'Technical',
  'scores.metric.pe_ratio': 'P/E ratio',
  'scores.metric.pb_ratio': 'P/B ratio',
  'scores.metric.fcf_yield': 'FCF yield',
  'scores.metric.debt_to_equity': 'Debt/Equity',
  'scores.metric.dividend_yield': 'Dividend yield',
  'scores.metric.revenue_cagr': 'Revenue CAGR',
  'scores.metric.net_income_cagr': 'Net income CAGR',
  'scores.metric.revenue_growth_consistency': 'Growth consistency',
  'scores.metric.roa_positive': 'Return on assets > 0',
  'scores.metric.cfo_positive': 'Operating cash flow > 0',
  'scores.metric.accruals_quality': 'Cash-backed earnings',
  'scores.metric.leverage_not_increasing': 'Leverage not rising',
  'scores.metric.no_significant_dilution': 'No significant dilution',
  'scores.metric.price_vs_sma200': 'Price vs 200-day average',
  'scores.metric.momentum_12_1': '12-month momentum',
  'scores.metric.sma50_vs_sma200': '50-day vs 200-day average',
  'scores.droppedReason.missing_concept': 'Missing data',
  'scores.droppedReason.non_positive_value': 'Value must be positive',
  'scores.droppedReason.missing_fx_rate': 'Exchange rate unavailable',
  'scores.droppedReason.insufficient_history': 'Not enough history yet',

  // --- Insights: news/sentiment + AI commentary (phase 6) -------------------
  'insights.badgeLabel': 'News & AI',
  'insights.badgeTooltip': 'Show recent news, sentiment and AI commentary',
  'insights.newsTitle': 'News & sentiment',
  'insights.noNews': 'No recent news found for this instrument.',
  'insights.sentimentTooltip': "Tone of this article per its provider (Alpha Vantage) — not the app's own view of this instrument.",
  'insights.sentiment.bullish': 'Clearly favorable tone',
  'insights.sentiment.somewhatBullish': 'Somewhat favorable tone',
  'insights.sentiment.neutral': 'Neutral tone',
  'insights.sentiment.somewhatBearish': 'Somewhat unfavorable tone',
  'insights.sentiment.bearish': 'Clearly unfavorable tone',
  'insights.sentiment.unknown': 'Tone unavailable',
  'insights.commentaryTitle': 'AI commentary',
  'insights.commentaryDisclaimer':
    "Generated from the data available, possibly incomplete — not an investment recommendation.",
  'insights.askPerplexity': 'Get AI commentary',

  'news.updated': '{symbol}: {articles} article(s) found.',
  'news.alreadyFresh': '{symbol}: already up to date ({days}-day cache).',
  'news.empty': '{symbol}: no recent news found.',
  'news.notMapped': '{symbol}: no provider mapping, so nothing to fetch.',
  'news.noProvider': '{symbol}: Alpha Vantage is not configured (missing an API key).',
  'news.rateLimited': '{symbol}: Alpha Vantage is rate-limiting. Try again shortly.',
  'news.failed': '{symbol}: retrieval failed ({error}).',

  'commentary.updated': '{symbol}: commentary fetched.',
  'commentary.alreadyFresh': '{symbol}: already up to date ({days}-day cache).',
  'commentary.noProvider': '{symbol}: Perplexity is not configured (missing an API key).',
  'commentary.rateLimited': '{symbol}: Perplexity is rate-limiting. Try again shortly.',
  'commentary.failed': '{symbol}: retrieval failed ({error}).',

  // --- Dividends -----------------------------------------------------------
  'dividends.title': 'Dividends',
  'dividends.subtitle': 'What was actually received and withheld, by account and calendar year.',
  'dividends.disclaimer':
    "This view summarises imported dividends and withholdings. It does not compute your final tax liability (flat tax, tax brackets, social contributions) and does not replace the documents provided by your broker or tax authority.",
  'dividends.empty': 'No dividends imported yet.',
  'dividends.heroTitle': '{year} dividends — gross',
  'dividends.withholding': 'Withholding tax',
  'dividends.net': 'Net',
  'dividends.gross': 'Gross',
  'dividends.paymentCount': 'Payments',
  'dividends.accountsAnalyzed': 'Accounts analysed',
  'dividends.byYearAccount': 'Yearly view by account',
  'dividends.year': 'Year',
  'dividends.account': 'Account',
  'dividends.unknownAccount': 'Unknown account',
  'dividends.currency': 'Currency',
  'dividends.unknownCurrency': 'Unknown currency',
  'dividends.exportSummaryCsv': 'Export (CSV, by account and year)',
  'dividends.detailTitle': 'Payment detail',
  'dividends.detailEmpty': 'No payments for these filters.',
  'dividends.allYears': 'All years',
  'dividends.allAccounts': 'All accounts',
  'dividends.date': 'Date',
  'dividends.instrument': 'Instrument',
  'dividends.reconciliation': 'Reconciliation',
  'dividends.status.matched': 'Automatic',
  'dividends.status.no_withholding': 'No withholding',
  'dividends.status.unmatched_tax': 'Unattributed withholding',
  'dividends.exportDetailCsv': 'Export (CSV, transaction detail)',

  // --- Tax prep ---------------------------------------------------------
  'taxPrep.title': 'Annual tax preparation',
  'taxPrep.subtitle': 'Imported flows to reconcile against your own tax documents, by account and year — never a tax calculation.',
  'taxPrep.disclaimer':
    'This summary is based on imported data. It helps reconcile your transactions against available tax documents (IFU, Mintos tax report...), but it does not compute your final tax and does not replace your tax return or personalised tax advice.',
  'taxPrep.empty': 'No dated transactions imported yet.',
  'taxPrep.emptyYear': 'No tax-relevant activity found for this year.',
  'taxPrep.yearLabel': 'Tax year',
  'taxPrep.exportCsv': 'Export (CSV)',

  'taxPrep.envelope.cto': 'Brokerage account',
  'taxPrep.envelope.pea': 'PEA',
  'taxPrep.envelope.p2p': 'P2P',
  'taxPrep.envelope.employee_savings': 'Employee savings',

  'taxPrep.status.to_reconcile': 'To reconcile',
  'taxPrep.status.not_applicable': 'Not applicable',

  'taxPrep.dividendsGross': 'Gross dividends',
  'taxPrep.dividendsWithholding': 'Withholding tax',
  'taxPrep.interest': 'Interest',
  'taxPrep.realizedGains': 'Realized gains',
  'taxPrep.realizedLosses': 'Realized losses',
  'taxPrep.fees': 'Fees',
  'taxPrep.deposits': 'Deposits',
  'taxPrep.withdrawals': 'Withdrawals',
  'taxPrep.otherFlows': 'Other flows (informational)',
  'taxPrep.unmatchedSalesLine':
    '{count} sale(s) detected for {amount} — gain/loss not computed: lot (FIFO) reconciliation unavailable.',

  'taxPrep.noWithdrawalDetected':
    'No withdrawal was imported for this year. Gains stay inside the wrapper and are not taxable while they remain there.',
  'taxPrep.withdrawalDetected':
    'A withdrawal of {amount} was detected. The applicable tax rules (plan age, exit conditions) are not computed automatically by this tool — check them yourself or with a tax advisor.',
  'taxPrep.unmatchedSales': '{count} sale(s) with no computed gain (lot reconciliation unavailable).',
  'taxPrep.notApplicable': 'No tax-relevant operation detected in this wrapper for this year.',

  // --- Portfolio risk (DEVLOG "Decision 3u.67") -------------------------------
  'risk.title': 'Portfolio risk',
  'risk.subtitle': "What your portfolio is actually exposed to — independent of any limit you've configured.",
  'risk.disclaimer':
    "These facts describe your portfolio's current exposure — not a limit, and not a buy/sell recommendation.",
  'concentration.title': 'Position concentration',
  'concentration.empty': 'Not enough valued positions to compute concentration.',
  'concentration.value': 'Value',
  'liquidity.title': 'Declared valuations',
  'liquidity.subtitle': 'Share of the portfolio valued from a broker statement rather than a live market price.',
  'liquidity.total': 'Total declared valuations',
  'liquidity.empty': 'No declared-valuation positions.',
  'liquidity.source': 'Source',
  'liquidity.positionsCount': 'Positions',
  'drawdown.title': 'Historical maximum drawdown',
  'drawdown.maxDrawdown': 'Max drawdown',
  'drawdown.peak': 'Peak',
  'drawdown.trough': 'Trough',
  'drawdown.recovery': 'Recovery',
  'drawdown.recoveredOn': 'Reached its prior peak again on {date}',
  'drawdown.notRecovered': 'Not yet recovered',
  'drawdown.noneObserved': 'No decline observed in the available history.',
  'drawdown.insufficientHistory': 'Not enough history to compute a max drawdown.',

  // --- Decision journal (DEVLOG "Decision 3u.68") -----------------------------
  'journal.title': 'Decision journal',
  'journal.subtitle': 'Your own written reasoning behind a trade, or a general note — never computed or scored.',
  'journal.empty': 'No journal entries yet.',
  'journal.general': 'General',
  'journal.entryDate': 'Written on',
  'journal.reviewDate': 'Review by',
  'journal.dueForReview': 'Due for review',
  'journal.form.title': 'Write a decision',
  'journal.form.subtitle': 'Record the reasoning now, while it is still fresh.',
  'journal.form.symbol': 'Symbol (optional)',
  'journal.form.thesis': 'Thesis',
  'journal.form.reviewDate': 'Review date (optional)',
  'journal.outcome.title': 'Outcome',
  'journal.outcome.add': 'Add outcome',
  'journal.outcome.save': 'Save outcome',

  // --- Backup ----------------------------------------------------------------
  'backup.title': 'Backup',
  'backup.description':
    "A timestamped copy of the local database — portfolio, transactions, corrections, target allocations. Nothing else is ever read or written: API keys (.env) are never included. The 10 most recent backups are kept, older ones are pruned automatically.",
  'backup.create': 'Create a backup',
  'backup.created': 'Backup created: {filename}',
  'backup.empty': 'No backups yet.',
  'backup.date': 'Date',
  'backup.size': 'Size',
  'backup.restore': 'Restore',
  'backup.confirmRestore': 'Confirm restore',
  'backup.restored': 'Database restored from {filename}.',
  'backup.restoreWarning':
    "Type the exact filename to confirm — restoring fully replaces the current database and cannot be undone.",

  // --- Corporate actions (splits / reverse splits) ----------------------------
  'corporateActions.title': 'Stock splits',
  'corporateActions.description':
    'Recorded splits and reverse splits. Raw price and lot data are never changed — every historical chart and calculation applies this at read time instead. Descriptive only, scoped to instruments already tracked by this app.',
  'corporateActions.detect': 'Run a full check (all sources)',
  'corporateActions.coverageTitle': 'Automatic coverage',
  'corporateActions.detectionChecked': '{checked} instrument(s) checked out of {candidates}.',
  'corporateActions.coveragePercent': '{percent}% coverage',

  // --- Persistent coverage (Phase 4, DEVLOG "Step 3u.57") -------------------
  // Strict instrument/event distinction: one instrument can carry several
  // events (e.g. BIVI.US and its three reverse splits).
  'corporateActions.coverage.instrumentsEligible': '{count} instrument(s) eligible for automatic checking.',
  'corporateActions.coverage.instrumentsChecked': '{checked} instrument(s) already checked, {unchecked} remaining.',
  'corporateActions.coverage.instrumentsExcluded': {
    one: "{count} non-listed asset or symbol-less holding is excluded from coverage — that's not an error.",
    other: "{count} non-listed assets or symbol-less holdings are excluded from coverage — that's not an error.",
  },
  'corporateActions.coverage.verifiedEvents': {
    one: '1 corporate action confirmed by several sources.',
    other: '{count} corporate actions confirmed by several sources.',
  },
  'corporateActions.coverage.candidateEvents': {
    one: '1 corporate action found by a single source still needs confirming.',
    other: '{count} corporate actions found by a single source still need confirming.',
  },
  'corporateActions.coverage.conflictEvents': {
    one: '1 corporate action has disagreeing sources — needs a look.',
    other: '{count} corporate actions have disagreeing sources — need a look.',
  },
  'corporateActions.coverage.suspectEvents': {
    one: "1 event wasn't applied — this symbol's history needs a look.",
    other: "{count} events weren't applied — this symbol's history needs a look.",
  },

  // --- Confidence badges (distinct from provenance) -------------------------
  'corporateActions.confidence.verified_three_sources': 'Confirmed by 3 sources',
  'corporateActions.confidence.verified_cross_source': 'Confirmed by several sources',
  'corporateActions.confidence.candidate_single_source': 'Found by one source — to confirm',
  'corporateActions.confidence.provider_conflict': 'Sources disagree — needs a look',
  'corporateActions.confidence.suspect_ticker_reuse': "Not applied — this symbol's history needs a look",
  'corporateActions.confidence.manual_promotion': 'Confirmed manually',
  'corporateActions.confidence.manual': 'Added manually',

  // --- Provenance detail (on click) -----------------------------------------
  'corporateActions.provenance.title': 'Verification',
  'corporateActions.provenance.foundOn': '{provider} — event found on {date} ({ratio})',
  'corporateActions.provenance.notUsedFmp': "FMP — not currently used in the confidence calculation",
  'corporateActions.provenance.notCheckedEodhd': 'EODHD — not checked (targeted, on-demand source)',

  // --- Alpha Vantage resume (manual button) ---------------------------------
  'corporateActions.resume.title': 'Alpha Vantage',
  'corporateActions.resume.description':
    "Checks up to 20 instruments that haven't yet received a usable answer from this source. This uses the provider's daily quota.",
  'corporateActions.resume.button': 'Resume Alpha Vantage verification',
  'corporateActions.resume.running': 'Checking…',
  'corporateActions.resume.remaining': {
    one: '1 instrument still needs checking with Alpha Vantage.',
    other: '{count} instruments still need checking with Alpha Vantage.',
  },
  'corporateActions.resume.upToDate': 'Every eligible instrument has already been checked with Alpha Vantage.',
  'corporateActions.resume.lastRun': 'Last batch: {date}',
  'corporateActions.resume.lastRunSummary':
    '{checked} instrument(s) checked — {verified} cross-source confirmation(s), {candidates} candidate(s) found, {noEvents} with nothing returned.',
  'corporateActions.resume.rateLimited':
    "The provider rate-limited this batch — checking will resume later. This is not an absence of coverage.",
  'corporateActions.resume.paused': 'The daily automatic resume is paused.',
  'corporateActions.resume.neverRun': 'No resume has run yet.',

  // --- Candidates to confirm (unapplied events) -----------------------------
  'corporateActions.outstanding.title': 'Candidates to confirm',
  'corporateActions.outstanding.description':
    'Corporate actions found by a single source, or with disagreeing sources — never auto-applied. Confirm them with a targeted EODHD check if needed.',
  'corporateActions.outstanding.empty': 'No candidates waiting for confirmation.',
  'corporateActions.outstanding.providers': 'Source(s): {providers}',
  'corporateActions.detectionIncomplete':
    'The provider is rate-limiting requests; {count} instrument(s) were not checked. No conclusion can be drawn for those — try again later.',
  'corporateActions.detectionFailedSummary': "{count} instrument(s) couldn't be checked automatically with FMP.",
  'corporateActions.detectionFailedCaveat':
    "An unavailable check doesn't mean no split happened. Check an instrument with another source, or add an event manually if needed.",
  'corporateActions.detectionSkippedSummary': '{count} instrument(s) skipped — no usable provider symbol',
  'corporateActions.historyTitle': 'Recorded history',
  'corporateActions.historyCount': {
    one: '1 known corporate action.',
    other: '{count} known corporate actions.',
  },
  'corporateActions.historyNewEvents': {
    one: '1 new event added by the last detection run.',
    other: '{count} new events added by the last detection run.',
  },
  'corporateActions.historyNoNewEvents': 'No new event added by the last detection run.',
  'corporateActions.addManually': 'Add manually',
  'corporateActions.selectInstrument': 'Select an instrument…',
  'corporateActions.newShares': 'New shares',
  'corporateActions.oldShares': 'Old shares',
  'corporateActions.empty': 'No splits recorded yet.',
  'corporateActions.instrument': 'Instrument',
  'corporateActions.type': 'Type',
  'corporateActions.date': 'Effective date',
  'corporateActions.ratio': 'Ratio',
  'corporateActions.source': 'Source',
  'corporateActions.priceHistoryStatus': 'Price history',
  'corporateActions.type.split': 'Split',
  'corporateActions.type.reverse_split': 'Reverse split',
  'corporateActions.source.fmp': 'FMP (automatic)',
  'corporateActions.source.eodhd': 'EODHD (on demand)',
  'corporateActions.source.yahoo': 'Yahoo (automatic)',
  'corporateActions.source.alpha_vantage': 'Alpha Vantage (automatic)',
  'corporateActions.source.polygon': 'Polygon (automatic)',
  'corporateActions.source.manual': 'Manual entry',
  'corporateActions.confidence': 'Confidence',
  'corporateActions.details': 'Detail',
  'corporateActions.status.raw': 'Corrected at read time',
  'corporateActions.status.already_adjusted': 'Already adjusted by provider',
  'corporateActions.status.not_applicable': 'No cached history to check',
  'corporateActions.status.unknown': 'Undetermined',
  'corporateActions.detectOne.title': 'Check one instrument with another source',
  'corporateActions.detectOne.description':
    'Use this one-off check when an instrument needs a further look. It queries EODHD for the selected instrument and spends its request quota.',
  'corporateActions.detectOne.button': 'Check with EODHD',
  'corporateActions.detectOne.created': {
    one: '1 corporate action recorded via EODHD.',
    other: '{count} corporate actions recorded via EODHD.',
  },
  'corporateActions.detectOne.alreadyKnown': 'Already known — nothing new from EODHD.',
  'corporateActions.detectOne.noEvents': 'EODHD returned no corporate actions for this instrument.',
  'corporateActions.detectOne.failed': 'Could not check this instrument with EODHD.',

  // --- Position detail panel --------------------------------------------------
  'positionDetail.summary': 'Summary',
  'positionDetail.allocation': 'Allocation',
  'positionDetail.categoryShare': 'Share of this asset class',
  'positionDetail.noAllocationData': 'No allocation data for this position.',
  'positionDetail.analysis': 'Analysis',
  'positionDetail.noScoreData': 'No score yet for this instrument.',
  'positionDetail.income': 'Income',
  'positionDetail.loadError': 'Could not load this section.',
  'positionDetail.history': 'History',
  'positionDetail.openLots': 'Open lots',
  'positionDetail.noLots': 'No lots on record.',
  'positionDetail.lotOpenedAt': 'Opened',
  'positionDetail.closedLots': 'Closed lots',
  'positionDetail.lotClosedAt': 'Closed',
  'positionDetail.closePrice': 'Close price',
  'positionDetail.relatedTransactions': 'Related transactions',
  'positionDetail.noTransactions': 'No transactions on record.',
  'positionDetail.dataQuality': 'Data quality',
  'positionDetail.priceStatus': 'Price status',
  'positionDetail.verifiedProvider': 'Verified via',
  'positionDetail.mappingStatus': 'Symbol mapping',
  'positionDetail.mappingStatusValue.RESOLVED': 'Resolved automatically, never tested',
  'positionDetail.mappingStatusValue.VERIFIED': 'Verified — a provider has returned data',
  'positionDetail.mappingStatusValue.MANUAL': 'Corrected by hand',
  'positionDetail.mappingStatusValue.UNRESOLVED': 'Unresolved',
  'positionDetail.notPriceableReason': 'Not priceable because',
  'positionDetail.notPriceableReasonValue.corporate_action':
    'Residue of a corporate action (a right, a fraction from a reverse split…) — this instrument will never be quoted.',
  'positionDetail.notPriceableReasonValue.unknown': 'This instrument is not priceable, for no precisely identified reason.',
  'positionDetail.notPriceableReasonValue.p2p_aggregate':
    'Mintos P2P loan aggregate — dozens of loan fragments with no individual quote, valued only as one overall balance declared by Mintos.',
  'positionDetail.notPriceableReasonValue.employee_savings_fund':
    "Amundi employee savings fund — no market quote; its value comes only from Amundi's annual statement.",
}
