import type { Catalogue } from './types'

export const fr: Catalogue = {
  // --- Shell ---------------------------------------------------------------
  'app.title': 'Stock Analyst',
  'nav.portfolio': 'Portefeuille',
  'nav.transactions': 'Transactions',
  'nav.watchlist': 'Watchlist',
  'nav.gems': 'Pépites',
  'nav.taxPrep': 'Préparation fiscale',
  'nav.risk': 'Risques',
  'nav.journal': 'Journal',
  'alerts.tooltip': {
    one: '{count} élément de la watchlist a atteint son prix cible',
    other: '{count} éléments de la watchlist ont atteint leur prix cible',
  },
  'language.label': 'Langue',
  'app.disclaimer':
    "Cet outil produit des indicateurs à partir de données publiques ; ce ne sont pas des conseils en investissement. Les décisions restent les vôtres.",

  // --- Common --------------------------------------------------------------
  'common.ok': 'OK',
  'common.cancel': 'Annuler',
  'common.save': 'Enregistrer',
  'common.saving': 'Enregistrement…',
  'common.add': 'Ajouter',
  'common.delete': 'Supprimer',
  'common.edit': 'Modifier',
  'common.loading': 'Chargement…',
  'common.notComputable': 'non calculable',
  'common.notApplicable': 'non applicable',
  'common.none': '—',

  // --- Portfolio page ------------------------------------------------------
  'portfolio.title': 'Portefeuille',
  'portfolio.subtitle': 'Positions détenues et résultat latent.',
  'portfolio.lastImport': 'Dernier import : {date}.',
  'portfolio.lastRefresh': 'Prix mis à jour le {date} à {time}',
  'portfolio.openPositions': 'Positions ouvertes',
  'portfolio.manageData': 'Gérer les données',

  'totals.positions': 'Positions',
  'totals.marketValue': 'Valeur de marché ({currency})',
  'totals.unrealized': 'Résultat latent ({currency})',
  'totals.unrealizedTooltip':
    "Écart entre la valeur au dernier cours disponible et votre prix moyen d'achat. Le résultat n'est réalisé qu'après une vente.",
  'totals.realized': 'Résultat réalisé ({currency})',
  'totals.performance': 'Performance',
  'totals.performanceTooltip':
    "Résultat latent exprimé en pourcentage de la valeur investie — pas un rendement annualisé.",
  'totals.incomplete': {
    one: "{count} position ne peut pas être valorisée pour l'instant — prix pas encore récupéré, devise inconnue ou taux de change indisponible. Elle est exclue des totaux plutôt que comptée à zéro, ce qui donnerait un total faux à l'apparence juste. Un clic sur \"Actualiser\" peut résoudre ça.",
    other:
      "{count} positions ne peuvent pas être valorisées pour l'instant — prix pas encore récupéré, devise inconnue ou taux de change indisponible. Elles sont exclues des totaux plutôt que comptées à zéro, ce qui donnerait un total faux à l'apparence juste. Un clic sur \"Actualiser\" peut résoudre ça.",
  },
  'totals.staleDeclaredValuations':
    "Le total inclut une ou plusieurs valorisations déclarées anciennes (Mintos, Amundi ESR…) — ces positions sont bien comptées dans le total, mais leur valeur peut ne plus refléter le portefeuille actuel. Voir Santé des données pour le détail.",

  'accounts.title': 'Par compte',
  'accounts.account': 'Compte',
  'accounts.positions': 'Positions',
  'accounts.invested': 'Investi',
  'accounts.investedTooltip': "Coût d'acquisition déclaré par le courtier — ne bouge pas avec le marché.",
  'accounts.value': 'Valeur',
  'accounts.unrealized': 'Latent',
  'accounts.performance': 'Perf.',

  // --- Performance approximation caveats (DEVLOG "Decision 3u.47") ---------
  'performance.mintosInterestIncome':
    "Gain net = intérêts et bonus perçus moins frais/taxes, depuis le {since} — une mesure de revenu réel, pas une plus-value de prix comme pour une action.",
  'performance.amundiApproximateGain':
    "Gain approché : part proportionnelle du gain du compte « {account} », basé sur les versements/abondement/intéressement connus depuis {since} — les années non importées ne comptent pas dans ce total, ce qui peut surestimer ce gain.",
  'performance.amundiRealGainSinceSnapshot':
    "Gain réel de ce fonds depuis le {since} : calculé à partir du dernier relevé ayant communiqué son gain, la quantité détenue n'ayant pas changé depuis.",

  // --- Fraîcheur des valorisations déclarées (DEVLOG "Decision 3u.50") -----
  'valuation.declaredFresh':
    'Valeur déclarée par {provider} au {date} — le dernier relevé importé, dans le délai attendu pour ce type de source.',
  'valuation.declaredStale':
    "Valeur déclarée par {provider} au {date} — le dernier relevé importé, mais plus ancien que le délai attendu pour ce type de source. Elle reste comptée dans le total ; elle peut simplement ne plus refléter le portefeuille actuel. Réimportez un relevé plus récent pour l'actualiser.",

  // --- Import panel --------------------------------------------------------
  'import.xtb.title': 'Importer un relevé XTB',
  'import.xtb.instructions':
    "Dans xStation : Account history → Export → période « All », format Excel. XTB a fermé son API le 14 mars 2025 : l'export de fichier est le seul moyen fiable de récupérer vos positions. Aucun identifiant n'est demandé ni stocké.",
  'import.xtb.multiAccount':
    "Un export ne couvre qu'un seul compte. Si vous en avez plusieurs (compte titres et PEA par exemple), exportez-les séparément et importez les deux fichiers : ils cohabitent sans s'écraser.",
  'import.xtb.dropzone': 'Glissez le fichier ici, ou choisissez-le manuellement (.xlsx ou .csv)',
  'import.mintos.title': 'Importer un relevé Mintos',
  'import.mintos.instructions':
    "Portfolio → Account Statement, un fichier PDF par trimestre. Aucun export cumulatif n'existe : importez chaque relevé trimestriel séparément (l'ordre n'a pas d'importance).",
  'import.mintos.multiAccount':
    "Le relevé couvre deux portefeuilles distincts : les ETF « Core ETF 90 » deviennent des positions normales, et le portefeuille de prêts « Mintos Core » devient un agrégat unique valorisé par Mintos.",
  'import.mintos.dropzone': 'Glissez le fichier ici, ou choisissez-le manuellement (.pdf)',
  'import.mintos-investments.title': 'Mettre à jour la valeur Mintos (export Investments)',
  'import.mintos-investments.instructions':
    "Sur Mintos : My investments → Export (.xlsx). Contrairement au relevé trimestriel PDF, cet export donne la valeur réelle du portefeuille de prêts au jour de l'export — utile pour rafraîchir le montant sans attendre le prochain trimestre.",
  'import.mintos-investments.multiAccount':
    "Un export plus récent remplace toujours l'affichage, qu'il vienne de ce fichier ou du relevé PDF trimestriel — le plus récent des deux est toujours celui montré.",
  'import.mintos-investments.dropzone': 'Glissez le fichier ici, ou choisissez-le manuellement (.xlsx)',
  'import.amundi.title': 'Importer un relevé Amundi ESR',
  'import.amundi.instructions':
    "Votre espace amundi-ee.com → Relevé annuel de situation (PDF). Chaque relevé est une photo annuelle, pas un historique de transactions daté — importez chaque année séparément.",
  'import.amundi.multiAccount':
    "Un relevé plus ancien importé après un plus récent n'écrase jamais vos positions actuelles — il reste consultable dans l'historique des imports ci-dessous.",
  'import.amundi.dropzone': 'Glissez le fichier ici, ou choisissez-le manuellement (.pdf)',
  'import.amundi-synthese.title': 'Mettre à jour la valeur Amundi (export Synthèse)',
  'import.amundi-synthese.instructions':
    "Sur votre espace amundi-ee.com : export « Synthèse » (.xlsb). Contrairement au relevé annuel PDF, cet export donne la valeur réelle de chaque fonds au jour de l'export — utile pour rafraîchir le montant sans attendre le prochain relevé annuel.",
  'import.amundi-synthese.multiAccount':
    "Un export plus récent remplace toujours l'affichage, qu'il vienne de ce fichier ou du relevé PDF annuel — le plus récent des deux est toujours celui montré.",
  'import.amundi-synthese.dropzone': 'Glissez le fichier ici, ou choisissez-le manuellement (.xlsb)',
  'import.chooseFile': 'Choisir un fichier',
  'import.importing': 'Import en cours…',
  'import.failed': "Échec de l'import : {error}",
  'import.summary':
    '{filename} — {positions} position(s) ouverte(s), {transactions} opération(s) détectée(s), dont {inserted} nouvelle(s).',
  'import.sectionsTitle': 'Feuilles détectées dans le fichier',
  'import.sectionLine': '{sheet} → {count} × {kind} ({rows} lignes source)',
  'import.previewTitle': "Aperçu — rien n'a encore été enregistré.",
  'import.confirm': "Confirmer l'import",
  'import.cancel': 'Annuler',
  'import.historyTitle': 'Historique des imports',
  'import.historyLine':
    '{date} — {filename} ({positions} position(s), {transactions} nouvelle(s) opération(s))',
  'import.undo': 'Annuler cet import',

  'section.open_positions': 'position ouverte',
  'section.closed_positions': 'position fermée',
  'section.cash_operations': 'opération de trésorerie',
  'section.unknown': 'bloc non reconnu',

  // --- Backend message codes ----------------------------------------------
  'import.unsupportedFileType':
    "Type de fichier « {extension} » non pris en charge. Exportez depuis xStation au format Excel (.xlsx) ou CSV.",
  'import.fileUnreadable': 'Fichier illisible : {error}',
  'import.noTableRecognised':
    "Aucune table reconnue dans ce fichier. Vérifiez qu'il s'agit bien d'un rapport exporté depuis Account history.",
  'import.nothingImportable': "Aucune position ni opération exploitable n'a été trouvée.",
  'import.unmappedColumns':
    'Colonnes non reconnues dans « {sheet} » : {columns}. Leurs valeurs sont conservées mais non exploitées.',
  'import.positionSkipped':
    "Position « {symbol} » ignorée : volume ou prix d'ouverture illisible.",
  'import.closedPositionSkipped':
    "Position fermée « {symbol} » ignorée : volume ou prix d'ouverture illisible.",
  'import.unresolvedSymbols': {
    one: '{count} symbole sans correspondance fournisseur : {symbols}. Corrigez-le ci-dessous pour activer son analyse.',
    other:
      '{count} symboles sans correspondance fournisseur : {symbols}. Corrigez-les ci-dessous pour activer leur analyse.',
  },

  // --- Symbol mapping ------------------------------------------------------
  'unresolved.title': {
    one: 'Symbole sans correspondance ({count})',
    other: 'Symboles sans correspondance ({count})',
  },
  'unresolved.description':
    "Ces instruments n'ont pas de correspondance automatique chez les fournisseurs de données : tant qu'ils ne sont pas corrigés, ils ne seront pas analysés. Les CFD sur indices, matières premières et devises n'ont pas de fondamentaux — il est normal qu'ils restent sans correspondance.",
  'unresolved.brokerSymbol': 'Symbole XTB',
  'unresolved.providerSymbol': 'Symbole fournisseur (format Yahoo)',

  'mapping.confirmed': 'confirmée',
  'mapping.unverified': 'non vérifiée',
  'mapping.toFix': 'à corriger',
  'mapping.fix': 'corriger',
  'mapping.unverifiedTooltip':
    "Conversion automatique du suffixe de place. La racine du symbole n'a pas été vérifiée auprès d'un fournisseur.",
  'mapping.isinPlaceholder': 'ISIN (ex. FR0000120271)',
  'mapping.isinHelp':
    "L'ISIN débloque la source de cours européenne. Vous le trouverez sur la fiche du titre chez votre courtier. Il n'est jamais deviné : un ISIN erroné renverrait les cours d'une autre société.",
  'mapping.placeholder': 'ex. ERIC-B.ST',

  'symbol.manualOverride': 'Correspondance définie manuellement.',
  'symbol.suffixConverted': 'Suffixe .{suffix} converti en « {providerSuffix} ».',
  'symbol.derivative':
    "Produit dérivé ({category}) : pas de fondamentaux, l'analyse ne s'y applique pas.",
  'symbol.unknownFormat':
    "Symbole hors du format « RACINE.PAYS » attendu, ou place de cotation inconnue. Indiquez le symbole fournisseur à la main si le titre est suivi.",
  'symbol.notAnEquity':
    "Non reconnu comme une action (indice, matière première, FX ou crypto). L'analyse fondamentale ne s'y applique pas.",

  // --- Manual position -----------------------------------------------------
  'manual.title': 'Position saisie manuellement',
  'manual.subtitle': "Pour un titre absent de l'export, ou détenu chez un autre courtier.",
  'manual.newTitle': 'Nouvelle position',
  'manual.symbol': 'Symbole XTB',
  'manual.quantity': 'Quantité',
  'manual.avgPrice': 'Prix de revient',
  'manual.currency': 'Devise',
  'manual.note':
    "Une position manuelle n'a pas de valorisation fournie par le courtier : elle ne comptera pas dans les totaux tant que les cours de marché ne sont pas branchés.",

  // --- Positions table -----------------------------------------------------
  'table.instrument': 'Titre',
  'table.type': 'Type',
  'table.mapping': 'Correspondance',
  'table.quantity': 'Qté',
  'table.avgPrice': 'Prix de revient',
  'table.avgPriceTooltip': "Montant moyen payé par action pour les lots enregistrés (PRU).",
  'table.avgPriceNotApplicableTooltip':
    'Valeur déclarée par Mintos au {date} — le coût investi net (versements et réinvestissements automatiques mêlés) ne peut pas être isolé dans les relevés importés, donc aucun PRU ni gain/perte ne sont calculés pour cet agrégat.',
  'table.price': 'Cours',
  'table.value': 'Valeur ({currency})',
  'table.valueNotComputableTooltip':
    "Cette position n'est pas incluse dans les totaux tant qu'aucun cours utilisable n'est disponible.",
  'table.deleteConfirm':
    'Supprimer définitivement la position {symbol} ? Cette action ne peut pas être annulée.',
  'table.weight': 'Poids',
  'table.weightTooltip':
    "Part de cette position dans la valeur actuellement calculable du portefeuille — les positions non valorisables sont exclues du calcul. Au-delà de 15%, la position est mise en évidence comme risque de concentration.",

  // --- Badge de statut du prix ---
  'priceStatus.fresh': 'Les données de prix sont à jour.',
  'priceStatus.stale':
    "Les données de prix n'ont pas été vérifiées récemment — la valeur affichée peut ne pas refléter le marché actuel. Rafraîchissez pour actualiser.",
  'priceStatus.error': "Aucun fournisseur n'a jamais renvoyé de données pour ce symbole.",
  'priceStatus.not_priceable':
    "Cet instrument n'a par nature aucun cours de marché — voir le détail de la position pour la raison précise.",
  'priceStatus.unmapped': "Pas encore de correspondance fournisseur — corrigez-la ci-dessous pour activer le suivi des prix.",
  'priceStatus.viaProvider': 'Vérifié via {provider} le {date}.',

  // --- Répartition du portefeuille ---
  'breakdown.title': 'Répartition du portefeuille',
  'breakdown.dimension.category': "Classe d'actif",
  'breakdown.dimension.currency': 'Devise',
  'breakdown.dimension.country': 'Pays',
  'breakdown.dimension.sector': 'Secteur',
  'breakdown.enrichSectors': 'Récupérer les secteurs (FMP + Wikidata)',
  'breakdown.enriching': 'Récupération des secteurs…',
  'breakdown.enrichResult': '{enriched} enrichis, {skipped} sans secteur, {failed} échoués.',
  'breakdown.empty': 'Pas assez de positions valorisées pour calculer une répartition.',
  'breakdown.unknown': 'Inconnu',
  'breakdown.other': 'Autres',

  // --- Détection de doublons par ISIN (watchlist/pépites) -------------------
  'duplicates.backfillIsins': 'Rechercher les identifiants manquants',
  'duplicates.backfilling': 'Recherche en cours…',
  'duplicates.backfillResult': '{checked} vérifiés, {updated} mis à jour.',
  'duplicates.backfillFigis': "Rechercher l'identité OpenFIGI manquante",
  'duplicates.backfillFigisResultMore': '{checked} vérifiés, {remaining} restants — clique à nouveau pour continuer.',
  'duplicates.backfillFigisResultDone': '{checked} vérifiés, aucun restant.',

  // --- Signaux position/watchlist -------------------------------------------
  // Combinaison fixe du score composite et de l'écart d'allocation/prix cible
  // — descriptif, jamais une consigne de trade (voir DEVLOG "Decision 3u.19").
  // Volontairement des faits, pas des verbes — « Renforcer »/« Réduire »
  // restent des instructions même sans dire « Acheter »/« Vendre » (voir
  // l'addendum de la DEVLOG "Decision 3u.19"). Les deux cas de convergence
  // nomment les deux conditions vraies, sans jamais dire quoi en faire.
  'signals.positionReinforceFact': 'Score élevé · sous-pondéré',
  'signals.positionReduceFact': 'Score faible · surpondéré',
  'signals.watchlistReinforceFact': 'Score élevé · prix sous la cible',
  'signals.hold': 'Rien à signaler',
  'signals.not_applicable': 'Données insuffisantes',
  'signals.band.high': 'élevé',
  'signals.band.mid': 'moyen',
  'signals.band.low': 'faible',
  'signals.band.none': 'sans score',
  'signals.positionTooltip': "Score {score}/100 ({band}) · Allocation {category} : {state}. Compare le score propre à ce titre avec l'écart global de toute sa classe d'actifs — pas une évaluation complète de cette position précise.",
  'signals.watchlistTooltip': "Score {score}/100 ({band}) · {distance} par rapport à ton prix d'entrée cible — une combinaison de deux indicateurs existants, pas une recommandation.",

  'breakdown.category.STOCK': 'Actions',
  'breakdown.category.ETF': 'ETF',
  'breakdown.category.CFD': 'CFD',
  'breakdown.category.P2P': 'Prêts P2P',
  'breakdown.category.FUND': 'Fonds épargne salariale',

  // --- À regarder aujourd'hui ---
  'attention.title': "À regarder aujourd'hui",
  'attention.allClear': 'Rien à signaler pour le moment.',
  'attention.unresolvedInstruments': {
    one: '{count} position a des données incomplètes',
    other: '{count} positions ont des données incomplètes',
  },
  'attention.priceError': {
    one: "{count} position n'a pas de prix disponible",
    other: "{count} positions n'ont pas de prix disponible",
  },
  'attention.priceStale': {
    one: "{count} position n'a pas été actualisée récemment",
    other: "{count} positions n'ont pas été actualisées récemment",
  },
  'attention.allocationUnder': 'Votre cible {category} est sous-pondérée de {gap} points',
  'attention.allocationOver': 'Votre cible {category} est surpondérée de {gap} points',

  // --- Santé des données ---
  'dataHealth.title': 'Santé des données',
  'dataHealth.subtitle':
    "Pour chaque position détenue : d'où vient sa valeur, à quelle date elle est valable, et si ses corporate actions sont confirmées.",
  'dataHealth.empty': 'Aucune position détenue pour le moment.',
  'dataHealth.figiDuplicates.title': 'Doublons possibles (identité OpenFIGI)',
  'dataHealth.figiDuplicates.hint':
    "Ces lignes partagent le même identifiant OpenFIGI (par action) — probablement la même entreprise suivie sous deux symboles différents. Un fait, jamais fusionné automatiquement : à vous de vérifier et de décider.",
  'dataHealth.figiDuplicates.source.held': 'détenue',
  'dataHealth.figiDuplicates.source.watchlist': 'watchlist',
  'dataHealth.figiDuplicates.source.screener': 'pépites',
  'dataHealth.staleSince': 'dernière cotation : {date}',
  'dataHealth.declaredSince': 'valorisation déclarée le : {date}',

  'dataHealth.summary.info': { one: '{count} donnée fiable', other: '{count} données fiables' },
  'dataHealth.summary.attention': { one: '{count} à surveiller', other: '{count} à surveiller' },
  'dataHealth.summary.actionRequired': { one: '{count} action requise', other: '{count} actions requises' },
  'dataHealth.summary.notApplicable': { one: '{count} non applicable', other: '{count} non applicables' },

  'dataHealth.column.instrument': 'Instrument',
  'dataHealth.column.valuation': 'Valorisation',
  'dataHealth.column.corporateActions': 'Corporate actions',
  'dataHealth.column.severity': 'Qualité',
  'dataHealth.column.recommendedAction': 'Action utile',

  'dataHealth.valuation.kind.market_price': 'Cours de marché',
  'dataHealth.valuation.kind.declared_value': 'Valeur déclarée',
  'dataHealth.valuation.kind.unavailable': 'Valeur non disponible',
  'dataHealth.valuation.freshness.stale': 'ancienne',
  'dataHealth.valuation.freshness.unknown': 'jamais confirmée',

  'dataHealth.corporateActions.status.verified': 'Confirmées',
  'dataHealth.corporateActions.status.no_events': 'Aucune trouvée',
  'dataHealth.corporateActions.status.candidate_single_source': 'Trouvée par une source — à confirmer',
  'dataHealth.corporateActions.status.provider_conflict': 'Les sources ne concordent pas',
  'dataHealth.corporateActions.status.suspect_ticker_reuse': 'Historique du symbole à vérifier',
  'dataHealth.corporateActions.status.incomplete_coverage': 'Couverture Alpha Vantage incomplète',
  'dataHealth.corporateActions.status.never_checked': 'Jamais vérifiées',
  'dataHealth.corporateActions.eventCounts': '{confirmed} confirmé(s), {outstanding} à confirmer',

  'dataHealth.severity.info': 'Information',
  'dataHealth.severity.attention': 'Attention',
  'dataHealth.severity.action_required': 'Action requise',
  'dataHealth.severity.not_applicable': 'Non applicable',

  'dataHealth.action.fix_symbol': 'Corriger le symbole',
  'dataHealth.action.refresh_quotes': 'Actualiser les cours',
  'dataHealth.action.import_recent_statement': 'Importer un relevé récent',
  'dataHealth.action.resume_alpha_vantage': 'Relancer la vérification Alpha Vantage',
  'dataHealth.action.verify_eodhd': 'Vérifier avec EODHD',

  // --- Checklist de démarrage ---
  'onboarding.title': 'Bien démarrer',
  'onboarding.dismiss': 'Masquer',
  'onboarding.step.import': 'Importer un relevé de transactions',
  'onboarding.why.import': 'reconstruit votre historique réel d’achats et de ventes',
  'onboarding.step.refresh': 'Actualiser les cours',
  'onboarding.why.refresh': 'met à jour la valeur actuelle de vos positions',
  'onboarding.step.unresolved': 'Vérifier les positions non reconnues',
  'onboarding.why.unresolved': 'une position sans correspondance fournisseur reste hors de toute analyse',
  'onboarding.step.fundamentals': 'Récupérer les fondamentaux',
  'onboarding.why.fundamentals': 'permet de calculer les scores Value, Growth et Quality',
  'onboarding.step.allocation': 'Définir une allocation cible',
  'onboarding.why.allocation': 'compare votre portefeuille à vos propres limites',
  'onboarding.step.watchlist': 'Ajouter quelques titres à surveiller',
  'onboarding.why.watchlist': 'suit les titres que vous envisagez, sans les posséder',

  // --- Allocation cible ---
  'allocation.title': 'Allocation cible',
  'allocation.description':
    "Répartition actuelle par classe d'actifs comparée à une plage que tu définis toi-même — purement descriptif, jamais une suggestion d'achat ou de vente d'un titre précis.",
  'allocation.empty': "Pas encore de positions valorisées à comparer à une cible.",
  'allocation.category': "Classe d'actifs",
  'allocation.current': 'Actuel',
  'allocation.target': 'Plage cible',
  'allocation.gap': 'État',
  'allocation.gapTooltip':
    "Comparaison avec vos propres objectifs de répartition — ce n'est pas une suggestion d'achat ou de vente.",
  'allocation.amount': 'Pour atteindre le minimum',
  'allocation.state.within': 'Dans la cible',
  'allocation.state.under': 'Sous-pondéré',
  'allocation.state.over': 'Surpondéré',
  'allocation.state.no_target': 'Aucune cible définie',
  'allocation.amountToInvest':
    "Environ {amount} de nouveaux versements permettraient d'atteindre le minimum de cette plage — une estimation statique qui suppose des cours et un reste de portefeuille inchangés, sans rien vendre.",
  'allocation.invalidRange': 'Entre une plage valide : 0–100, minimum pas supérieur au maximum.',
  'allocation.setTarget': 'Définir une cible',

  // --- Politique personnelle ---
  'policy.title': 'Politique personnelle',
  'policy.subtitle':
    "Vos propres règles de décision — objectif, horizon, liquidité, tolérance au risque et limites de concentration. L'outil compare le portefeuille à ces règles et signale les écarts ; il ne recommande jamais un achat ou une vente.",
  'policy.edit': 'Modifier ma politique',
  'policy.empty': "Aucune politique personnelle définie pour le moment. Cliquez sur « Modifier ma politique » pour la définir.",

  'policy.objective': 'Objectif',
  'policy.objective.growth': 'Croissance',
  'policy.objective.income': 'Revenu',
  'policy.objective.preservation': 'Préservation du capital',
  'policy.objectiveNote': 'Précision libre',

  'policy.horizon': 'Horizon',
  'policy.horizon.short': 'Court terme',
  'policy.horizon.medium': 'Moyen terme',
  'policy.horizon.long': 'Long terme',
  'policy.horizonTargetDate': 'Date cible',

  'policy.liquidity': 'Liquidité',
  'policy.liquidityAmount': 'Montant prévu',
  'policy.liquidityDate': 'Échéance prévue',
  'policy.liquidityNote': 'Précision libre',

  'policy.riskTolerance': 'Tolérance et capacité de perte',
  'policy.riskToleranceNote': 'Tolérance (texte libre)',
  'policy.lossCapacityPct': 'Perte maximale acceptable (%)',
  'policy.lossCapacityValue': 'perte maximale acceptable : {pct}%',

  'policy.limits.title': 'Limites personnelles',
  'policy.limits.subtitle':
    "Vos propres seuils de concentration — par ligne, secteur, pays, devise ou type d'actif. Un dépassement est un constat, jamais une instruction d'achat ou de vente.",
  'policy.limits.dimension': 'Dimension',
  'policy.limits.target': 'Cible',
  'policy.limits.range': 'Plage',
  'policy.limits.min': 'Min %',
  'policy.limits.max': 'Max %',
  'policy.limits.targetPlaceholder.sector': 'Technology',
  'policy.limits.targetPlaceholder.country': 'France',
  'policy.limits.targetPlaceholder.currency': 'USD',
  'policy.limits.targetPlaceholder.category': 'STOCK',

  'policy.dimension.line': 'Par ligne',
  'policy.dimension.sector': 'Secteur',
  'policy.dimension.country': 'Pays',
  'policy.dimension.currency': 'Devise',
  'policy.dimension.category': "Type d'actif",
  'policy.dimension.declared_valuation': 'Valorisations déclarées',

  'policy.gaps.allWithin': 'Toutes vos limites personnelles sont respectées actuellement.',
  'policy.gaps.disclaimer': "Ces constats ne constituent pas une suggestion d'achat ou de vente.",
  'policy.gaps.yourLimit': 'votre limite : {range}',

  // --- Historique de valeur ---
  'history.title': 'Évolution de la valeur',
  'history.value': 'Valeur',
  'history.invested': 'Investi',
  'history.benchmark': 'Indice de référence',
  'history.caveat':
    "Reconstruction réelle à partir de vos achats/ventes effectifs, pas une simulation de vos positions actuelles rejouées dans le passé. Les CFD ne peuvent pas être inclus (leur quantité est un nombre de contrats, pas d'actions).",
  'history.benchmarkCaveat':
    "La ligne en pointillés n'est pas un simple ratio de cours : elle simule ce que la même somme, investie dans l'indice de référence aux mêmes dates (y compris les ventes), vaudrait aujourd'hui.",
  'history.capped':
    "L'historique commence le {date} — limite de profondeur des cours en cache, pas la date de votre premier achat.",
  'history.empty': "Pas encore assez de données (lots ou cours en cache) pour reconstruire un historique.",

  'table.unrealized': 'Latent ({currency})',
  'table.performance': 'Perf.',
  'table.score': 'Score',
  'table.scoreTooltip':
    'Score composite combinant Value (30%), Growth (25%), Quality (25%) et Technique (20%) par défaut — repondéré pour chaque position quand un pilier n’a pas de données. Cliquez sur le badge pour le détail réel de cette position.',
  'table.signal': 'Signal',
  'table.since': 'Depuis',
  'table.account': 'Compte',
  'table.insights': 'Analyses',
  'table.empty': 'Aucune position. Importez un relevé XTB ou ajoutez une ligne manuellement.',
  'table.lots': {
    one: '{count} lot',
    other: '{count} lots',
  },
  'table.short': 'vente à découvert',
  'table.manual': 'manuelle',

  'filters.account': 'Compte',
  'filters.all': 'Tous',
  'filters.type': 'Type',
  'filters.dateFrom': 'Du',
  'filters.dateTo': 'Au',
  'filters.search': 'Recherche',
  'filters.priceMin': 'Prix min.',
  'filters.priceMax': 'Prix max.',
  'filters.capMin': 'Capitalisation min.',
  'filters.capMax': 'Capitalisation max.',
  'filters.debtMax': 'Dette/capitaux propres max.',
  'filters.historyMin': 'Historique min. (années)',
  'filters.dividendMin': 'Rendement dividende min. (%)',
  'filters.scoreMin': 'Score composite min.',
  'table.columns': 'Colonnes',

  // --- Transactions ----------------------------------------------------------
  'transactions.title': 'Transactions',
  'transactions.subtitle':
    "Dividendes, frais, achats/ventes et mouvements de trésorerie tels qu'importés — le résumé ci-dessous reflète les filtres actifs, pas le cumul depuis toujours.",
  'transactions.viewDividends': 'Voir les dividendes par compte et par année →',
  'transactions.date': 'Date',
  'transactions.type': 'Type',
  'transactions.instrument': 'Titre',
  'transactions.account': 'Compte',
  'transactions.amount': 'Montant',
  'transactions.comment': 'Commentaire',
  'transactions.empty': 'Aucune transaction pour ces filtres.',
  'transactions.summary.netDividends': 'Dividendes nets',
  'transactions.summary.grossAndTax': 'Bruts {gross} · retenue à la source {tax}',
  'transactions.summary.fees': 'Frais totaux',
  'transactions.summary.realizedPl': 'P&L réalisé',
  'transactions.summary.effectSplit': 'Effet titre {instrument} · Devise & frais {currency}',
  'transactions.summary.effectCoverage':
    '({resolved} sur {total} trades clôturés — les autres, surtout des CFD, n’ont pas de taux de conversion à répartir)',
  'transactions.instrumentEffect': 'Effet titre',
  'transactions.instrumentEffectTooltip':
    "Le mouvement du cours du titre lui-même, au taux de change du jour d'ouverture — un des deux volets du P&L réalisé. Affiché uniquement pour les trades clôturés.",
  'transactions.currencyEffect': 'Devise & frais',
  'transactions.currencyEffectTooltip':
    "Le reste du P&L une fois mis de côté le mouvement du cours du titre lui-même (au taux de change du jour d'ouverture) — surtout le mouvement du taux de change depuis, plus commission/swap. Affiché uniquement pour les trades clôturés dont l'export du courtier contenait les deux taux de conversion.",
  'transactions.group.all': 'Tout',
  'transactions.group.dividends': 'Dividendes',
  'transactions.group.trades': 'Achats/ventes',
  'transactions.group.fees': 'Frais',
  'transactions.group.cash': 'Trésorerie',
  'transactions.type.BUY': 'Achat',
  'transactions.type.SELL': 'Vente',
  'transactions.type.CLOSED_TRADE': 'Position clôturée',
  'transactions.type.DIVIDEND': 'Dividende',
  'transactions.type.TAX': 'Retenue à la source',
  'transactions.type.FEE': 'Frais',
  'transactions.type.DEPOSIT': 'Dépôt',
  'transactions.type.WITHDRAWAL': 'Retrait',
  'transactions.type.INTEREST': 'Intérêts',
  'transactions.type.OTHER': 'Autre',
  'transactions.actions': 'Actions',
  'transactions.manual.title': 'Transaction saisie à la main',
  'transactions.manual.subtitle':
    "Un dividende, des frais ou un mouvement de trésorerie absent d'un import — jamais un achat/vente (voir la note ci-dessous).",
  'transactions.manual.newTitle': 'Nouvelle transaction',
  'transactions.manual.note':
    "Les achats, ventes et positions clôturées ne sont pas proposés ici — ajoutez ou corrigez une position depuis la page Portefeuille.",
  'transactions.invalidAmount': 'Entrez un montant valide.',

  // --- Prices ---------------------------------------------------------------
  'prices.title': 'Actualisation des prix',
  'prices.subtitle':
    "Les fournisseurs gratuits limitent fortement les requêtes : chaque clic traite la liste dans un budget de temps et indique ce qu'il reste. Un seul bouton met à jour l'historique (graphiques de tendance) puis les cotations en direct — les totaux du portefeuille ci-dessus s'actualisent avec. Seul le coût d'acquisition (Investi) reste celui déclaré par votre courtier.",
  'prices.phaseHistory': 'Étape 1/2 — Historique des cours',
  'prices.phaseLive': 'Étape 2/2 — Cours en direct',
  'prices.refresh': 'Actualiser',
  'prices.refreshing': 'Actualisation…',
  'prices.progress': '{done} / {total} instruments traités',
  'prices.retryFailed': {
    one: "Réessayer l'instrument en échec ({count})",
    other: 'Réessayer les instruments en échec ({count})',
  },
  'prices.summary': '{updated} mis à jour, {skipped} déjà à jour, {failed} non récupérés.',
  'prices.remaining': {
    one: '{count} instrument restant — cliquez à nouveau pour continuer.',
    other: '{count} instruments restants — cliquez à nouveau pour continuer.',
  },
  'prices.updated': '{symbol} : {bars} nouvelle(s) barre(s) via {provider}.',
  'prices.alreadyFresh': '{symbol} : déjà à jour.',
  'prices.notMapped': '{symbol} : pas de correspondance fournisseur, rien à récupérer.',
  'prices.symbolNotFound': '{symbol} : inconnu de {provider}. Vérifiez le symbole fournisseur.',
  'prices.rateLimited': '{symbol} : {provider} limite les requêtes. Réessayez dans quelques minutes.',
  'prices.planLimited':
    "{symbol} : couvert par {provider} uniquement sur une offre payante. Le symbole est correct — rien à corriger ici.",
  'prices.alreadyRunning':
    "Un rafraîchissement est déjà en cours. Deux en parallèle consomment le double de quota sans rien apporter — attendez la fin du premier.",
  'prices.stillUnavailable':
    "{symbol} : toujours aucun cours. Déjà demandé aujourd'hui — aucun fournisseur configuré ne couvre ce marché dans son offre gratuite.",
  'prices.needsIsin':
    "{symbol} : aucune source n'a même pu essayer — aucune ne dispose d'un identifiant pour ce titre. Saisissez son ISIN sur la ligne (il figure sur la fiche du titre chez votre courtier) et il sera tenté au prochain rafraîchissement.",
  'prices.notPriceable':
    "{symbol} : aucun cours de marché n'existe pour cet instrument. Un droit non transférable issu d'une opération sur titres ne peut être ni acheté ni vendu — aucune source au monde ne le cote.",
  'prices.noProvider': "{symbol} : aucun fournisseur de données n'est disponible.",
  'prices.failed': '{symbol} : échec de la récupération via {provider}.',
  'prices.budgetReached': 'Budget de temps atteint, {remaining} instrument(s) restant(s).',
  'prices.noFallbackConfigured':
    "Yahoo limite les requêtes et aucun fournisseur de repli n'est configuré. Ajoutez une clé gratuite TWELVEDATA_API_KEY dans .env (inscription par e-mail, sans carte) pour que le rafraîchissement continue de fonctionner.",

  'fundamentals.updated': '{symbol} : {concepts} donnée(s) récupérée(s) depuis {provider}.',
  'fundamentals.alreadyFresh': '{symbol} : déjà à jour.',
  'fundamentals.notApplicable': "{symbol} : pas une entreprise — aucune donnée fondamentale n'existe.",
  'fundamentals.noProvider': "{symbol} : SEC EDGAR n'est pas configuré (SEC_USER_AGENT manquant).",
  'fundamentals.symbolNotFound': "{symbol} : introuvable dans l'index des émetteurs SEC.",
  'fundamentals.rateLimited': '{symbol} : SEC EDGAR limite les requêtes. Réessayez sous peu.',
  'fundamentals.failed': '{symbol} : échec de la récupération ({error}).',

  'table.trend': 'Tendance (90j)',
  'mapping.verified': 'vérifiée',
  'mapping.verifiedTooltip': 'Un fournisseur a renvoyé des données pour ce symbole le {date} ({provider}).',

  // --- Settings page -------------------------------------------------------
  'settings.title': 'Paramètres',
  'settings.subtitle': 'Gérez vos clés API et sources de données.',
  'settings.groupPortfolioData.title': 'Données du portefeuille',
  'settings.groupPortfolioData.subtitle':
    'Importez, complétez et actualisez les données utilisées dans votre suivi.',
  'settings.groupIntegrity.title': 'Intégrité et corrections',
  'settings.groupIntegrity.subtitle':
    "Corrigez les symboles ou enregistrez les opérations sur capital qui influencent l'historique.",
  'settings.groupBackup.title': 'Sauvegarde',
  'settings.groupDataSources.title': 'Sources de données',
  'settings.groupDataSources.subtitle':
    'Configurez les fournisseurs utilisés pour les prix, les fondamentaux et les taux de change.',
  'settings.description':
    'Ces clés API sont stockées localement dans votre fichier .env et ne sont jamais envoyées ailleurs. Ajoutez des clés pour activer des fournisseurs de prix supplémentaires et maximiser la redondance si une source rate-limite.',
  'settings.providerStatus': 'État des fournisseurs de données',
  'settings.apiKey': 'Clé API',
  'settings.secEdgarName': 'SEC EDGAR',
  'settings.contactInfo': 'Contact',
  'settings.contactInfoSet': 'Déjà configuré',
  'settings.noContactInfo': 'Votre nom et votre email',
  'settings.contactInfoFormat':
    'Format : votre nom, un espace, puis un email — ex. « Jean Dupont jean@exemple.com ». Envoyé à la SEC à chaque requête (leur exigence, pas celle de cette appli) ; une adresse jetable convient très bien.',
  'settings.test': 'Tester',
  'settings.testing': 'Test en cours…',
  'settings.getFreeKey': 'Obtenir une clé gratuite',
  'settings.learnMore': 'En savoir plus',
  'settings.keylessNote': 'Également actifs sans configuration : {names}.',
  'settings.noKey': 'Non configurée',
  'settings.enabled': 'Activée',
  'settings.disabled': 'Désactivée',
  'settings.saved': 'Paramètres enregistrés avec succès. Le backend a rechargé votre configuration.',
  'settings.error': 'Erreur lors de l\'enregistrement des paramètres : {error}',
  'settings.supportsFree': 'Plan gratuit : {limit}',
  'settings.coolingDown': 'Limite atteinte',
  'settings.coolingDownTooltip':
    "Cette source a atteint sa limite de requêtes récemment et est mise en pause temporairement — elle se rétablit d'elle-même après un court délai.",
  'settings.coverage': '{served}/{total} de vos positions',
  'settings.quotaUsed': '{used}/{limit} utilisées {period}',
  'settings.periodDay': "aujourd'hui",
  'settings.periodMonth': 'ce mois-ci',
  'settings.periodMinute': 'cette minute',

  // Descriptions for each provider
  'provider.description.yahoo': 'Yahoo Finance — mondial, pas de clé requise',
  'provider.description.polygon': 'Polygon.io — US + crypto, 5 req/min',
  'provider.description.alpha_vantage': 'Alpha Vantage — mondial, 5 req/min',
  'provider.description.boursorama': 'Boursorama — Euronext Paris, pas de clé requise',
  'provider.description.frankfurt': 'Boerse Frankfurt — ISIN européen, pas de clé requise',
  'provider.description.twelvedata': 'Twelve Data — US fallback, 800 req/jour',
  'provider.description.fmp': 'Financial Modeling Prep — Euronext, 250 req/jour',
  'provider.description.tiingo': 'Tiingo — mondial, 500 req/jour',
  'provider.description.barchart': 'Barchart — mondial, 400 req/jour',
  'provider.description.intrinio': 'Intrinio — US + Canada, 500 req/jour',
  'provider.description.eodhd': 'EODHD — 150+ bourses mondiales, 20 req/jour',
  'provider.description.eoddata': 'Eoddata — actions/crypto/forex, pas de clé requise',
  'provider.description.finviz': 'Finviz — actions US via web scraping (fragile)',

  // --- Watchlist ------------------------------------------------------------
  'watchlist.title': 'Watchlist',
  'watchlist.description': "Titres suivis mais non détenus, et analyse du moment d'entrée.",
  'watchlist.openItems': 'Titres suivis',
  'watchlist.targetPrice': "Prix d'entrée cible",
  'watchlist.distanceToTarget': "Écart à l'entrée",
  'watchlist.distanceToTargetTooltip':
    "Écart entre le cours actuel et votre propre prix d'entrée cible — pas une performance : un écart négatif veut dire que le cours est sous votre cible.",
  'watchlist.note': 'Note',
  'watchlist.addedOn': 'Ajouté le',
  'watchlist.invalidTarget': 'Entre un prix cible valide, ou laisse le champ vide.',
  'watchlist.empty': "Rien sur votre watchlist pour l'instant — ajoutez un symbole ci-dessus pour commencer.",
  'watchlist.form.title': 'Ajouter à la watchlist',
  'watchlist.form.subtitle': "Suivre un symbole que vous ne détenez pas encore, avec un prix d'entrée cible optionnel.",
  'watchlist.form.newTitle': 'Nouveau titre suivi',
  'watchlist.form.symbol': 'Symbole',
  'watchlist.form.companyName': 'Nom de la société (optionnel)',
  'watchlist.form.companyNamePlaceholder': 'ex. LVMH',
  'watchlist.form.targetPrice': "Prix d'entrée cible (optionnel)",
  'watchlist.form.targetPriceTooltip': "Votre propre référence, jamais suggérée par l'application.",
  'watchlist.form.note': 'Note (optionnelle)',

  // --- Filtre de pépites (phase 5) ------------------------------------------
  'gems.title': 'Pépites',
  'gems.description':
    "Une liste de candidats choisis à la main, classés par score, pour repérer des titres prometteurs que tu ne détiens ou ne surveilles pas déjà.",
  'gems.priceFilterTitle': 'Filtre de prix',
  'gems.priceFilterHint':
    'Appliqué à toutes les listes de la page — Candidats, univers S&P 500 et scans Finviz.',
  'gems.candidates': 'Candidats',
  'gems.empty': 'Aucun candidat pour le moment — ajoute un symbole ci-dessus pour commencer à le filtrer.',
  'gems.form.title': 'Ajouter un candidat',
  'gems.form.subtitle': 'Filtrer un symbole que tu ne détiens ni ne surveilles déjà.',
  'gems.form.newTitle': 'Nouveau candidat',
  'gems.form.symbol': 'Symbole',
  'gems.form.companyName': 'Nom de la société (optionnel)',
  'gems.form.companyNamePlaceholder': 'ex. LVMH',

  // --- Découverte (recherche automatisée de candidats, phase 7) ------------
  'discovery.title': 'Découverte',
  'discovery.description':
    "Recherche automatisée de candidats. Chaque candidat reçoit un verdict Acheter/Conserver/Vendre, calculé automatiquement à partir de son score composite existant — ce n'est pas une recommandation d'investissement réelle.",
  'discovery.empty': 'Rien à afficher pour le moment.',
  'discovery.recommendationColumn': 'Verdict',
  'discovery.recommendationTooltip':
    "Calculé automatiquement à partir du score composite existant — ce n'est pas une recommandation d'investissement réelle.",
  'discovery.recommendation.buy': 'Acheter',
  'discovery.recommendation.hold': 'Conserver',
  'discovery.recommendation.sell': 'Vendre',
  'discovery.recommendation.none': 'Pas de données',
  'discovery.verdictFilterLabel': 'Filtre par verdict',
  'discovery.verdictFilterHint':
    'Appliqué au classement S&P 500 et aux scans Finviz ci-dessous — les candidats choisis à la main plus haut n’ont pas de verdict à filtrer.',
  'discovery.dataQualityFilterLabel': 'Qualité des données',
  'discovery.dataQualityFilterOption': 'N’afficher que les candidats aux données fiables',
  'discovery.dataQualityFilterHint':
    'Nécessite un score calculé, un cours récent et correctement mappé, et aucune vérification de corporate action en attente.',
  'discovery.marketSectorFilterLabel': 'Pays et secteur',
  'discovery.marketSectorFilterHint':
    'Appliqué au classement S&P 500 et aux scans Finviz ci-dessous — les candidats choisis à la main plus haut n’ont pas encore de filtre pays/secteur. Les options reflètent ce qui est actuellement chargé.',
  'discovery.marketCapFilterLabel': 'Capitalisation',
  'discovery.marketCapFilterHint':
    'Appliqué au classement S&P 500 et aux scans Finviz ci-dessous — les candidats choisis à la main plus haut n’ont pas de capitalisation calculée. Approximation (actions diluées moyennes pondérées × cours), suffisante pour filtrer, pas pour un usage comptable.',
  'discovery.debtRatioFilterLabel': 'Endettement',
  'discovery.debtRatioFilterHint':
    'Ratio dette/capitaux propres, déjà calculé pour le pilier Value — n’exclut que la dette à long terme. Appliqué au classement S&P 500 et aux scans Finviz ci-dessous, pas aux candidats choisis à la main plus haut.',
  'discovery.historyFilterLabel': 'Historique de prix minimal',
  'discovery.historyFilterHint':
    'Nombre approximatif d’années de cours en cache pour cet instrument — une exigence de suffisance des données, pas un critère de qualité de l’entreprise. Appliqué au classement S&P 500 et aux scans Finviz ci-dessous.',
  'discovery.dividendFilterLabel': 'Rendement du dividende',
  'discovery.dividendFilterHint':
    'Estimation à partir des dividendes déclarés par action, divisés par le cours — une estimation au niveau de l’entreprise, différente du rendement réel calculé pour vos positions détenues. Appliqué au classement S&P 500 et aux scans Finviz ci-dessous. Nécessite d’avoir cliqué sur « Compléter les données de dividendes » au moins une fois pour les candidats déjà évalués.',
  'discovery.scoreFilterLabel': 'Score composite minimum',
  'discovery.scoreFilterHint':
    'Masque les candidats dont le score composite (0-100) est sous ce seuil — un candidat sans score calculé du tout (données insuffisantes) est également masqué, pas affiché comme s’il passait le seuil. Appliqué au classement S&P 500 et aux scans Finviz ci-dessous.',
  'discovery.rankByValue': 'Classer par Value',
  'discovery.rankByGrowth': 'Classer par Growth',
  'discovery.valueScore': 'Value',
  'discovery.valueScoreTooltip': 'Un des piliers du score composite — pas une note autonome.',
  'discovery.growthScore': 'Growth',
  'discovery.growthScoreTooltip': 'Un des piliers du score composite — pas une note autonome.',
  'discovery.marketCap': 'Capitalisation',
  'discovery.debtRatio': 'Dette/CP',
  'discovery.dividendYield': 'Rendement dividende',
  'discovery.backfillDividends': 'Compléter les données de dividendes',
  'discovery.importResult': '{imported} importés, {alreadyPresent} déjà présents.',
  'discovery.refreshResultMore': '{evaluated} évalués, {remaining} restants — clique à nouveau pour continuer.',
  'discovery.refreshResultDone': '{evaluated} évalués, aucun restant.',
  'discovery.sp500.title': 'Univers S&P 500',
  'discovery.sp500.description':
    "Une liste statique des sociétés du S&P 500, notées avec les mêmes piliers Value/Growth utilisés partout ailleurs dans l'app.",
  'discovery.sp500.import': "Importer l'univers S&P 500",
  'discovery.sp500.refresh': 'Analyser le prochain lot',
  'discovery.finviz.title': 'Scans prédéfinis Finviz',
  'discovery.finviz.description':
    'Un signal différent, plus étroit — achats d\'initiés et conditions techniques de survente — jamais mélangé aux scores Value/Growth ci-dessus.',
  'discovery.finviz.insiderBuys': "Achats d'initiés",
  'discovery.finviz.oversold': 'Survendu',
  'discovery.finviz.slowNotice':
    'Chaque scan résout le cours et les fondamentaux de chaque résultat un par un — peut prendre quelques minutes pour ~10 candidats.',
  'discovery.finviz.failedCount': "{count} candidat(s) n'ont pas pu être résolus et ont été ignorés.",
  'discovery.finviz.scanningNotice':
    'Scan en cours — les fournisseurs gratuits peuvent nécessiter plusieurs minutes. Ne ferme pas cette page.',

  'prediction.title': 'Historique de prix',
  'prediction.description':
    "Un vrai modèle prédictif a besoin d'un vrai backtest, qui a besoin d'un historique de prix plus profond que ce que l'app garde normalement. Cette étape récupère plusieurs années de bougies journalières pour les instruments déjà cotés — prix uniquement, car les fondamentaux ne sont pas encore stockés avec une date de dépôt, et utiliser le score d'aujourd'hui pour « prédire » un rendement passé serait un biais de anticipation. Voir « Backtest » ci-dessous pour ce que le modèle fait de ces données.",
  'prediction.backfill': "Récupérer l'historique de prix",
  'prediction.running': 'Récupération…',
  'prediction.alreadyRunning': 'Une récupération est déjà en cours.',
  'prediction.backfillResult': '{updated} mis à jour, {failed} échecs, {barsAdded} nouvelles bougies stockées.',
  'backtest.title': 'Backtest',
  'backtest.description':
    "Un modèle technique simple, basé uniquement sur le prix (momentum, moyennes mobiles, volatilité réalisée), réentraîné à chaque exécution et évalué strictement sur des données postérieures à sa période d'entraînement — jamais une prédiction par titre, seulement la performance historique du modèle lui-même.",
  'backtest.run': 'Lancer le backtest',
  'backtest.running': 'En cours…',
  'backtest.disclaimer':
    "Ceci est une seule évaluation historique, pas la preuve d'un avantage réel en trading. Le modèle ne voit que le prix — aucun fondamental, aucune actualité, aucun jugement — et les résultats passés ne garantissent rien sur l'avenir.",
  'backtest.instrumentsUsed': 'Instruments utilisés',
  'backtest.trainPeriod': "Période d'entraînement (échantillons)",
  'backtest.testPeriod': 'Période de test (échantillons)',
  'backtest.singleClassWarning':
    "La période d'entraînement n'a évolué que dans une seule direction (ex. une tendance haussière ininterrompue) — aucun modèle utile n'a pu être ajusté, donc aucune précision n'est indiquée.",
  'backtest.testAccuracy': 'Précision sur la période de test',
  'backtest.avgReturnUp': 'Rendement réalisé moyen — hausse prédite',
  'backtest.avgReturnDown': 'Rendement réalisé moyen — baisse prédite',
  'backtest.lowSampleWarning': 'La période de test a trop peu d’échantillons pour faire confiance à cette précision.',

  'factors.title': 'Exposition factorielle (modèle à 4 facteurs de Carhart)',
  'factors.description':
    "Explicatif, pas prédictif : ce qui a historiquement piloté le rendement journalier de chaque position — Marché, Taille, Valeur et Momentum — à partir des données factorielles publiques de Kenneth French. Positions détenues uniquement, appariées par région (un titre américain contre les facteurs US, un titre européen contre ceux d'Europe).",
  'factors.import': 'Importer les données de facteurs',
  'factors.importResult': '{imported} importées, {alreadyPresent} déjà présentes.',
  'factors.empty': "Aucune position détenue n'a encore pu être appariée à une région.",
  'factors.region': 'Région',
  'factors.alpha': 'Alpha',
  'factors.alphaTooltip': "Rendement journalier excédentaire non expliqué par les quatre facteurs — l'ordonnée à l'origine de la régression.",
  'factors.betaMkt': 'Marché',
  'factors.betaMktTooltip': "Sensibilité au rendement excédentaire du marché global (Mkt-RF).",
  'factors.betaSmb': 'Taille',
  'factors.betaSmbTooltip': 'Sensibilité au rendement des petites vs grandes capitalisations (SMB).',
  'factors.betaHml': 'Valeur',
  'factors.betaHmlTooltip': "Sensibilité au rendement des titres à fort vs faible ratio book-to-market (HML).",
  'factors.betaMom': 'Momentum',
  'factors.betaMomTooltip': "Sensibilité au rendement des titres récemment gagnants vs perdants (Mom/WML).",
  'factors.rSquared': 'R²',
  'factors.rSquaredTooltip': 'Part de la variance du rendement journalier expliquée par les quatre facteurs ensemble.',
  'factors.observations': 'Jours',
  'factors.notApplicable.no_region_match':
    "Aucune série factorielle journalière publiée ne couvre le pays de cet instrument.",
  'factors.notApplicable.insufficient_history':
    "Pas encore assez d'historique de prix et de facteurs qui se recoupent.",

  // --- Moteur de scoring (phase 3) -----------------------------------------
  'scores.refreshTitle': 'Fondamentaux',
  'scores.refreshSubtitle':
    'Récupère les données financières via SEC EDGAR (États-Unis) et ESEF (Europe) pour alimenter les scores Value/Growth/Quality.',
  'scores.refresh': 'Récupérer les fondamentaux',
  'scores.refreshing': 'Récupération…',
  'scores.refreshSummary':
    '{updated} mis à jour, {skipped} déjà à jour, {notApplicable} non applicables, {failed} non récupérés.',
  'fundamentals.alreadyRunning':
    "Une récupération des fondamentaux est déjà en cours. Deux en parallèle consomment le double de requêtes sans rien apporter — attendez la fin de la première.",
  'scores.compositeTooltip': 'Score composite : {score}/100',
  'scores.notAdvice': "Résume les indicateurs disponibles. Ce n'est pas une recommandation d'investissement.",
  'scores.clickForDetail': 'Cliquez pour voir les critères, les données utilisées et les éléments écartés.',
  'scores.summarySentence': 'Score {score}/100 : {band}.',
  'scores.summary.high': 'indicateurs globalement favorables selon les données disponibles',
  'scores.summary.mid': 'indicateurs mitigés selon les données disponibles',
  'scores.summary.low': 'indicateurs globalement défavorables selon les données disponibles',
  'scores.strengths': 'Points forts',
  'scores.watchPoints': 'Points à contrôler',
  'scores.noneIdentified': 'Aucun pour l’instant',
  'scores.pillarScore': '{score}/100 ({weight}% du composite)',
  'scores.pillarScoreTooltip': '{pillar} : {score}/100 ({weight}%)',
  'scores.pillarDropped': 'Aucune donnée',
  'scores.binaryPass': 'Réussi',
  'scores.binaryFail': 'Échoué',
  'scores.pillar.value': 'Value',
  'scores.pillar.growth': 'Growth',
  'scores.pillar.quality': 'Quality',
  'scores.pillar.technical': 'Technique',
  'scores.metric.pe_ratio': 'Ratio P/E',
  'scores.metric.pb_ratio': 'Ratio P/B',
  'scores.metric.fcf_yield': 'Rendement du FCF',
  'scores.metric.debt_to_equity': 'Dette/Capitaux propres',
  'scores.metric.dividend_yield': 'Rendement du dividende',
  'scores.metric.revenue_cagr': 'TCAC du chiffre d’affaires',
  'scores.metric.net_income_cagr': 'TCAC du résultat net',
  'scores.metric.revenue_growth_consistency': 'Régularité de la croissance',
  'scores.metric.roa_positive': 'Rentabilité des actifs > 0',
  'scores.metric.cfo_positive': "Flux de trésorerie d'exploitation > 0",
  'scores.metric.accruals_quality': 'Bénéfices adossés au cash',
  'scores.metric.leverage_not_increasing': "Endettement en baisse ou stable",
  'scores.metric.no_significant_dilution': 'Pas de dilution significative',
  'scores.metric.price_vs_sma200': 'Prix vs moyenne 200 jours',
  'scores.metric.momentum_12_1': 'Momentum 12 mois',
  'scores.metric.sma50_vs_sma200': 'Moyenne 50j vs 200j',
  'scores.droppedReason.missing_concept': 'Donnée manquante',
  'scores.droppedReason.non_positive_value': 'La valeur doit être positive',
  'scores.droppedReason.missing_fx_rate': 'Taux de change indisponible',
  'scores.droppedReason.insufficient_history': "Historique insuffisant pour l'instant",

  // --- Analyses : actualités/sentiment + commentaire IA (phase 6) -----------
  'insights.badgeLabel': 'Actus & IA',
  'insights.badgeTooltip': "Afficher l'actualité récente, le sentiment et le commentaire IA",
  'insights.newsTitle': 'Actualités & sentiment',
  'insights.noNews': 'Aucune actualité récente trouvée pour cet instrument.',
  'insights.sentimentTooltip':
    "Ton de cet article selon son fournisseur (Alpha Vantage) — pas un avis de l'application sur ce titre.",
  'insights.sentiment.bullish': 'Ton nettement favorable',
  'insights.sentiment.somewhatBullish': 'Ton plutôt favorable',
  'insights.sentiment.neutral': 'Ton neutre',
  'insights.sentiment.somewhatBearish': 'Ton plutôt défavorable',
  'insights.sentiment.bearish': 'Ton nettement défavorable',
  'insights.sentiment.unknown': 'Ton non disponible',
  'insights.commentaryTitle': 'Commentaire IA',
  'insights.commentaryDisclaimer':
    "Synthèse générée à partir des données disponibles, potentiellement incomplète — ne constitue pas un conseil en investissement.",
  'insights.askPerplexity': 'Obtenir un commentaire IA',

  'news.updated': '{symbol} : {articles} article(s) trouvé(s).',
  'news.alreadyFresh': '{symbol} : déjà à jour (cache de {days} jour(s)).',
  'news.empty': '{symbol} : aucune actualité récente trouvée.',
  'news.notMapped': '{symbol} : aucune correspondance fournisseur, rien à récupérer.',
  'news.noProvider': "{symbol} : Alpha Vantage n'est pas configuré (clé API manquante).",
  'news.rateLimited': '{symbol} : Alpha Vantage limite les requêtes. Réessaie dans un instant.',
  'news.failed': '{symbol} : échec de la récupération ({error}).',

  'commentary.updated': '{symbol} : commentaire récupéré.',
  'commentary.alreadyFresh': '{symbol} : déjà à jour (cache de {days} jour(s)).',
  'commentary.noProvider': "{symbol} : Perplexity n'est pas configuré (clé API manquante).",
  'commentary.rateLimited': '{symbol} : Perplexity limite les requêtes. Réessaie dans un instant.',
  'commentary.failed': '{symbol} : échec de la récupération ({error}).',

  // --- Dividendes --------------------------------------------------------
  'dividends.title': 'Dividendes',
  'dividends.subtitle': 'Ce qui a été réellement perçu et retenu, par compte et par année civile.',
  'dividends.disclaimer':
    "Cette vue récapitule les dividendes et retenues importés. Elle ne calcule pas votre impôt final (PFU, barème, prélèvements sociaux) et ne remplace pas les documents fournis par votre courtier ou l'administration fiscale.",
  'dividends.empty': 'Aucun dividende importé pour le moment.',
  'dividends.heroTitle': 'Dividendes {year} — brut',
  'dividends.withholding': 'Retenue à la source',
  'dividends.net': 'Net',
  'dividends.gross': 'Brut',
  'dividends.paymentCount': 'Versements',
  'dividends.accountsAnalyzed': 'Comptes analysés',
  'dividends.byYearAccount': 'Vue annuelle par compte',
  'dividends.year': 'Année',
  'dividends.account': 'Compte',
  'dividends.unknownAccount': 'Compte inconnu',
  'dividends.currency': 'Devise',
  'dividends.unknownCurrency': 'Devise inconnue',
  'dividends.exportSummaryCsv': 'Exporter (CSV, par compte et par année)',
  'dividends.detailTitle': 'Détail des versements',
  'dividends.detailEmpty': 'Aucun versement pour ces filtres.',
  'dividends.allYears': 'Toutes les années',
  'dividends.allAccounts': 'Tous les comptes',
  'dividends.date': 'Date',
  'dividends.instrument': 'Titre',
  'dividends.reconciliation': 'Rapprochement',
  'dividends.status.matched': 'Automatique',
  'dividends.status.no_withholding': 'Aucune retenue',
  'dividends.status.unmatched_tax': 'Retenue non attribuée',
  'dividends.exportDetailCsv': 'Exporter (CSV, détail des transactions)',

  // --- Préparation fiscale ---------------------------------------------------
  'taxPrep.title': 'Préparation fiscale annuelle',
  'taxPrep.subtitle':
    "Les flux importés à rapprocher de vos documents fiscaux, par compte et par année — jamais un calcul d'impôt.",
  'taxPrep.disclaimer':
    "Cette synthèse est fondée sur les données importées. Elle aide à rapprocher vos opérations des documents fiscaux disponibles (IFU, rapport fiscal Mintos...), mais ne calcule pas votre impôt final et ne remplace pas votre déclaration ni un conseil fiscal personnalisé.",
  'taxPrep.empty': 'Aucune transaction datée importée pour le moment.',
  'taxPrep.emptyYear': 'Aucune activité fiscalement pertinente trouvée pour cette année.',
  'taxPrep.yearLabel': 'Année fiscale',
  'taxPrep.exportCsv': 'Exporter (CSV)',

  'taxPrep.envelope.cto': 'Compte titres',
  'taxPrep.envelope.pea': 'PEA',
  'taxPrep.envelope.p2p': 'P2P',
  'taxPrep.envelope.employee_savings': 'Épargne salariale',

  'taxPrep.status.to_reconcile': 'À rapprocher',
  'taxPrep.status.not_applicable': 'Non applicable',

  'taxPrep.dividendsGross': 'Dividendes bruts',
  'taxPrep.dividendsWithholding': 'Retenue à la source',
  'taxPrep.interest': 'Intérêts',
  'taxPrep.realizedGains': 'Plus-values réalisées',
  'taxPrep.realizedLosses': 'Moins-values réalisées',
  'taxPrep.fees': 'Frais',
  'taxPrep.deposits': 'Versements',
  'taxPrep.withdrawals': 'Retraits',
  'taxPrep.otherFlows': 'Autres flux (informatifs)',
  'taxPrep.unmatchedSalesLine':
    '{count} vente(s) détectée(s) pour {amount} — plus-value non calculée : rapprochement des lots (FIFO) non disponible.',

  'taxPrep.noWithdrawalDetected':
    "Aucun retrait n'a été importé pour cette année. Les gains restent à l'intérieur de l'enveloppe et ne sont pas imposables tant qu'ils y demeurent.",
  'taxPrep.withdrawalDetected':
    'Un retrait de {amount} a été détecté. La fiscalité applicable dépend de règles (ancienneté du plan, conditions de sortie) que cet outil ne calcule pas automatiquement — à vérifier vous-même ou avec un conseil fiscal.',
  'taxPrep.unmatchedSales': '{count} vente(s) sans plus-value calculée (rapprochement des lots non disponible).',
  'taxPrep.notApplicable': "Aucune opération fiscalement pertinente détectée dans cette enveloppe pour cette année.",

  // --- Risques du portefeuille (DEVLOG "Decision 3u.67") --------------------
  'risk.title': 'Risques du portefeuille',
  'risk.subtitle':
    'Ce que votre portefeuille est réellement exposé — indépendamment de toute limite que vous auriez configurée.',
  'risk.disclaimer':
    "Ces éléments décrivent l'exposition actuelle de votre portefeuille — ce ne sont ni des limites, ni des recommandations d'achat ou de vente.",
  'concentration.title': 'Concentration par ligne',
  'concentration.empty': 'Pas assez de positions valorisées pour calculer une concentration.',
  'concentration.value': 'Valeur',
  'liquidity.title': 'Valorisations déclarées',
  'liquidity.subtitle': "Part du portefeuille valorisée à partir d'un relevé du courtier plutôt que d'un cours de marché.",
  'liquidity.total': 'Total valorisations déclarées',
  'liquidity.empty': 'Aucune position à valorisation déclarée.',
  'liquidity.source': 'Source',
  'liquidity.positionsCount': 'Positions',
  'drawdown.title': 'Baisse maximale historique',
  'drawdown.maxDrawdown': 'Baisse maximale',
  'drawdown.peak': 'Sommet',
  'drawdown.trough': 'Point bas',
  'drawdown.recovery': 'Récupération',
  'drawdown.recoveredOn': 'A retrouvé son sommet précédent le {date}',
  'drawdown.notRecovered': 'Pas encore récupérée',
  'drawdown.noneObserved': "Aucune baisse observée sur l'historique disponible.",
  'drawdown.insufficientHistory': 'Historique insuffisant pour calculer une baisse maximale.',

  // --- Journal de décisions (DEVLOG "Decision 3u.68") -----------------------
  'journal.title': 'Journal de décisions',
  'journal.subtitle': "Votre propre raisonnement écrit derrière une décision, ou une note générale — jamais calculé ni noté.",
  'journal.empty': 'Aucune entrée dans le journal pour le moment.',
  'journal.general': 'Générale',
  'journal.entryDate': 'Écrite le',
  'journal.reviewDate': 'À revoir le',
  'journal.dueForReview': 'À revoir',
  'journal.form.title': 'Écrire une décision',
  'journal.form.subtitle': "Notez le raisonnement maintenant, tant qu'il est encore frais.",
  'journal.form.symbol': 'Symbole (optionnel)',
  'journal.form.thesis': 'Thèse',
  'journal.form.reviewDate': 'Date de revue (optionnelle)',
  'journal.outcome.title': 'Résultat',
  'journal.outcome.add': 'Ajouter un résultat',
  'journal.outcome.save': 'Enregistrer le résultat',

  // --- Sauvegarde ----------------------------------------------------------
  'backup.title': 'Sauvegarde',
  'backup.description':
    "Copie horodatée de la base locale — portefeuille, transactions, corrections, allocations cibles. Rien d'autre n'est jamais lu ni écrit : les clés API (.env) ne sont jamais incluses. Les 10 sauvegardes les plus récentes sont conservées, les plus anciennes sont supprimées automatiquement.",
  'backup.create': 'Créer une sauvegarde',
  'backup.created': 'Sauvegarde créée : {filename}',
  'backup.empty': 'Aucune sauvegarde pour le moment.',
  'backup.date': 'Date',
  'backup.size': 'Taille',
  'backup.restore': 'Restaurer',
  'backup.confirmRestore': 'Confirmer la restauration',
  'backup.restored': 'Base restaurée depuis {filename}.',
  'backup.restoreWarning':
    "Tape le nom exact du fichier pour confirmer — la restauration remplace intégralement la base actuelle et ne peut pas être annulée.",

  // --- Splits d'actions --------------------------------------------------------
  'corporateActions.title': 'Divisions d\'actions',
  'corporateActions.description':
    "Divisions (splits) et regroupements (reverse splits) enregistrés. Les prix et lots bruts ne sont jamais modifiés — chaque graphique et calcul historique applique la correction à la lecture. Détectés automatiquement en croisant Alpha Vantage, Polygon et (une fois réadmis) FMP ; EODHD reste une vérification ciblée, à la demande. Purement descriptif, limité aux titres déjà suivis par l'application.",
  'corporateActions.detect': 'Lancer une vérification complète (toutes sources)',
  'corporateActions.coverageTitle': 'Couverture automatique',
  'corporateActions.detectionChecked': '{checked} instrument(s) vérifié(s) sur {candidates}.',
  'corporateActions.coveragePercent': '{percent} % de couverture',

  // --- Couverture persistante (Phase 4, DEVLOG "Step 3u.57") ----------------
  // Distinction stricte instruments / événements : un même instrument peut
  // porter plusieurs opérations (ex. BIVI.US et ses trois regroupements).
  'corporateActions.coverage.instrumentsEligible':
    '{count} instrument(s) éligible(s) à la vérification automatique.',
  'corporateActions.coverage.instrumentsChecked':
    '{checked} instrument(s) déjà vérifié(s), {unchecked} restant(s).',
  'corporateActions.coverage.instrumentsExcluded': {
    one: "{count} actif non coté ou sans symbole de marché est exclu de la couverture — ce n'est pas une erreur.",
    other:
      "{count} actifs non cotés ou sans symbole de marché sont exclus de la couverture — ce n'est pas une erreur.",
  },
  'corporateActions.coverage.verifiedEvents': {
    one: '1 opération sur titre confirmée par plusieurs sources.',
    other: '{count} opérations sur titre confirmées par plusieurs sources.',
  },
  'corporateActions.coverage.candidateEvents': {
    one: '1 opération trouvée par une seule source reste à confirmer.',
    other: '{count} opérations trouvées par une seule source restent à confirmer.',
  },
  'corporateActions.coverage.conflictEvents': {
    one: '1 opération présente des sources en désaccord — à vérifier.',
    other: '{count} opérations présentent des sources en désaccord — à vérifier.',
  },
  'corporateActions.coverage.suspectEvents': {
    one: "1 événement n'a pas été appliqué — historique du symbole à vérifier.",
    other: "{count} événements n'ont pas été appliqués — historique du symbole à vérifier.",
  },

  // --- Badges de confiance (distincts de la provenance) ---------------------
  'corporateActions.confidence.verified_three_sources': 'Confirmé par 3 sources',
  'corporateActions.confidence.verified_cross_source': 'Confirmé par plusieurs sources',
  'corporateActions.confidence.candidate_single_source': 'Trouvé par une source — à confirmer',
  'corporateActions.confidence.provider_conflict': 'Sources divergentes — à vérifier',
  'corporateActions.confidence.suspect_ticker_reuse': 'Non appliqué — historique du symbole à vérifier',
  'corporateActions.confidence.manual_promotion': 'Confirmé manuellement',
  'corporateActions.confidence.manual': 'Ajouté manuellement',

  // --- Détail de provenance (au clic) ---------------------------------------
  'corporateActions.provenance.title': 'Vérification',
  'corporateActions.provenance.foundOn': '{provider} — événement trouvé le {date} ({ratio})',
  'corporateActions.provenance.notUsedFmp': 'FMP — non utilisé dans le calcul de confiance actuellement',
  'corporateActions.provenance.notCheckedEodhd': 'EODHD — non vérifié (source ciblée, à la demande)',

  // --- Reprise Alpha Vantage (bouton manuel) --------------------------------
  'corporateActions.resume.title': 'Alpha Vantage',
  'corporateActions.resume.description':
    "Vérifie jusqu'à 20 instruments qui n'ont pas encore reçu de réponse exploitable de cette source. Cette opération utilise le quota quotidien du fournisseur.",
  'corporateActions.resume.button': 'Relancer la vérification Alpha Vantage',
  'corporateActions.resume.running': 'Vérification en cours…',
  'corporateActions.resume.remaining': {
    one: '1 instrument reste à vérifier avec Alpha Vantage.',
    other: '{count} instruments restent à vérifier avec Alpha Vantage.',
  },
  'corporateActions.resume.upToDate': 'Tous les instruments éligibles ont déjà été vérifiés avec Alpha Vantage.',
  'corporateActions.resume.lastRun': 'Dernier lot : {date}',
  'corporateActions.resume.lastRunSummary':
    '{checked} instrument(s) vérifié(s) — {verified} confirmation(s) croisée(s), {candidates} candidat(s) trouvé(s), {noEvents} sans opération retournée.',
  'corporateActions.resume.rateLimited':
    "Le fournisseur a limité les requêtes pendant ce lot — la vérification reprendra plus tard. Ce n'est pas une absence de couverture.",
  'corporateActions.resume.paused': 'La reprise automatique quotidienne est en pause.',
  'corporateActions.resume.neverRun': "Aucune reprise n'a encore été lancée.",

  // --- Candidats à confirmer (événements non appliqués) ---------------------
  'corporateActions.outstanding.title': 'Candidats à confirmer',
  'corporateActions.outstanding.description':
    "Opérations trouvées par une seule source, ou avec des sources en désaccord — jamais appliquées automatiquement. Confirmez-les via une vérification EODHD ciblée si besoin.",
  'corporateActions.outstanding.empty': 'Aucun candidat en attente de confirmation.',
  'corporateActions.outstanding.providers': 'Source(s) : {providers}',
  'corporateActions.detectionIncomplete':
    "Le fournisseur a limité les requêtes ; {count} instrument(s) n'ont pas été vérifiés. Aucune conclusion ne peut être tirée pour ceux-ci — réessaie plus tard.",
  'corporateActions.detectionFailedSummary': "{count} instrument(s) n'ont pas pu être vérifiés automatiquement avec FMP.",
  'corporateActions.detectionFailedCaveat':
    "Une vérification indisponible ne signifie pas qu'aucun split n'existe. Vérifiez un instrument avec une autre source ou ajoutez une opération manuellement si nécessaire.",
  'corporateActions.detectionSkippedSummary': '{count} instrument(s) ignoré(s), faute de symbole exploitable',
  'corporateActions.historyTitle': 'Historique enregistré',
  'corporateActions.historyCount': {
    one: '1 événement de division connu.',
    other: '{count} événements de division connus.',
  },
  'corporateActions.historyNewEvents': {
    one: '1 nouvel événement ajouté lors de la dernière détection.',
    other: '{count} nouveaux événements ajoutés lors de la dernière détection.',
  },
  'corporateActions.historyNoNewEvents': 'Aucun nouvel événement ajouté lors de la dernière détection.',
  'corporateActions.addManually': 'Ajouter manuellement',
  'corporateActions.selectInstrument': 'Choisir un titre…',
  'corporateActions.newShares': 'Nouvelles actions',
  'corporateActions.oldShares': 'Anciennes actions',
  'corporateActions.empty': 'Aucun split enregistré pour le moment.',
  'corporateActions.instrument': 'Titre',
  'corporateActions.type': 'Type',
  'corporateActions.date': "Date d'effet",
  'corporateActions.ratio': 'Ratio',
  'corporateActions.source': 'Source',
  'corporateActions.priceHistoryStatus': 'Historique de prix',
  'corporateActions.type.split': 'Division',
  'corporateActions.type.reverse_split': 'Regroupement',
  'corporateActions.source.fmp': 'FMP (automatique)',
  'corporateActions.source.eodhd': 'EODHD (à la demande)',
  'corporateActions.source.yahoo': 'Yahoo (automatique)',
  'corporateActions.source.alpha_vantage': 'Alpha Vantage (automatique)',
  'corporateActions.source.polygon': 'Polygon (automatique)',
  'corporateActions.source.manual': 'Saisie manuelle',
  'corporateActions.confidence': 'Confiance',
  'corporateActions.details': 'Détail',
  'corporateActions.status.raw': 'Corrigé à la lecture',
  'corporateActions.status.already_adjusted': 'Déjà ajusté par le fournisseur',
  'corporateActions.status.not_applicable': 'Pas d\'historique en cache à vérifier',
  'corporateActions.status.unknown': 'Indéterminé',
  'corporateActions.detectOne.title': 'Vérifier un instrument avec une autre source',
  'corporateActions.detectOne.description':
    'Utilisez cette vérification ponctuelle lorsqu\'un instrument nécessite un contrôle complémentaire. Elle interroge EODHD pour le titre sélectionné et consomme son quota de requêtes.',
  'corporateActions.detectOne.button': 'Vérifier avec EODHD',
  'corporateActions.detectOne.created': {
    one: '1 division d\'action enregistrée via EODHD.',
    other: '{count} divisions d\'action enregistrées via EODHD.',
  },
  'corporateActions.detectOne.alreadyKnown': 'Division d\'action déjà connue — rien de nouveau via EODHD.',
  'corporateActions.detectOne.noEvents': 'EODHD n\'a retourné aucune division d\'action pour ce titre.',
  'corporateActions.detectOne.failed': 'Vérification EODHD impossible pour ce titre.',

  // --- Panneau détail par position --------------------------------------------
  'positionDetail.summary': 'Résumé',
  'positionDetail.allocation': 'Allocation',
  'positionDetail.categoryShare': 'Part de cette classe d\'actifs',
  'positionDetail.noAllocationData': 'Aucune donnée d\'allocation pour cette position.',
  'positionDetail.analysis': 'Analyse',
  'positionDetail.noScoreData': 'Pas encore de score pour ce titre.',
  'positionDetail.income': 'Revenus',
  'positionDetail.loadError': 'Impossible de charger cette section.',
  'positionDetail.history': 'Historique',
  'positionDetail.openLots': 'Lots ouverts',
  'positionDetail.noLots': 'Aucun lot enregistré.',
  'positionDetail.lotOpenedAt': 'Ouvert le',
  'positionDetail.closedLots': 'Lots clôturés',
  'positionDetail.lotClosedAt': 'Clôturé le',
  'positionDetail.closePrice': 'Prix de clôture',
  'positionDetail.relatedTransactions': 'Transactions liées',
  'positionDetail.noTransactions': 'Aucune transaction enregistrée.',
  'positionDetail.dataQuality': 'Qualité des données',
  'positionDetail.priceStatus': 'État du prix',
  'positionDetail.verifiedProvider': 'Vérifié via',
  'positionDetail.mappingStatus': 'Correspondance du symbole',
  'positionDetail.mappingStatusValue.RESOLVED': 'Résolue automatiquement, jamais testée',
  'positionDetail.mappingStatusValue.VERIFIED': 'Vérifiée — un fournisseur a renvoyé des données',
  'positionDetail.mappingStatusValue.MANUAL': 'Corrigée à la main',
  'positionDetail.mappingStatusValue.UNRESOLVED': 'Non résolue',
  'positionDetail.notPriceableReason': 'Non valorisable car',
  'positionDetail.notPriceableReasonValue.corporate_action':
    "Résidu d'une opération sur titres (droit, fraction issue d'un regroupement…) — cet instrument ne sera jamais coté.",
  'positionDetail.notPriceableReasonValue.unknown': "Cet instrument n'est pas valorisable, sans raison précise identifiée.",
  'positionDetail.notPriceableReasonValue.p2p_aggregate':
    "Agrégat de prêts P2P Mintos — des dizaines de fragments de prêts sans cours individuel, valorisés uniquement par un solde global déclaré par Mintos.",
  'positionDetail.notPriceableReasonValue.employee_savings_fund':
    "Fonds d'épargne salariale Amundi — pas de cotation de marché, sa valeur provient uniquement du relevé annuel Amundi.",
}
