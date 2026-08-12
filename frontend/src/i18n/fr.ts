import type { Catalogue } from './types'

export const fr: Catalogue = {
  // --- Shell ---------------------------------------------------------------
  'app.title': 'Stock Analyst',
  'nav.portfolio': 'Portefeuille',
  'nav.watchlist': 'Watchlist',
  'nav.gems': 'Pépites',
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
  'common.loading': 'Chargement…',
  'common.notComputable': 'non calculable',
  'common.none': '—',

  // --- Portfolio page ------------------------------------------------------
  'portfolio.title': 'Portefeuille',
  'portfolio.subtitle': 'Positions détenues et résultat latent.',
  'portfolio.lastImport': 'Dernier import : {date}.',
  'portfolio.openPositions': 'Positions ouvertes',

  'totals.positions': 'Positions',
  'totals.marketValue': 'Valeur de marché ({currency})',
  'totals.unrealized': 'Résultat latent ({currency})',
  'totals.performance': 'Performance',
  'totals.incomplete': {
    one: "{count} position ne fournit pas de valorisation — typiquement une ligne saisie à la main. Elle est exclue des totaux plutôt que comptée à zéro, ce qui donnerait un total faux à l'apparence juste. Les cours de marché arrivent à l'étape suivante du projet.",
    other:
      "{count} positions ne fournissent pas de valorisation — typiquement des lignes saisies à la main. Elles sont exclues des totaux plutôt que comptées à zéro, ce qui donnerait un total faux à l'apparence juste. Les cours de marché arrivent à l'étape suivante du projet.",
  },

  'accounts.title': 'Par compte',
  'accounts.account': 'Compte',
  'accounts.positions': 'Positions',
  'accounts.invested': 'Investi',
  'accounts.value': 'Valeur',
  'accounts.unrealized': 'Latent',
  'accounts.performance': 'Perf.',

  // --- Import panel --------------------------------------------------------
  'import.title': 'Importer un relevé XTB',
  'import.instructions':
    "Dans xStation : Account history → Export → période « All », format Excel. XTB a fermé son API le 14 mars 2025 : l'export de fichier est le seul moyen fiable de récupérer vos positions. Aucun identifiant n'est demandé ni stocké.",
  'import.multiAccount':
    "Un export ne couvre qu'un seul compte. Si vous en avez plusieurs (compte titres et PEA par exemple), exportez-les séparément et importez les deux fichiers : ils cohabitent sans s'écraser.",
  'import.dropzone': 'Glissez le fichier ici, ou choisissez-le manuellement (.xlsx ou .csv)',
  'import.chooseFile': 'Choisir un fichier',
  'import.importing': 'Import en cours…',
  'import.failed': "Échec de l'import : {error}",
  'import.summary':
    '{filename} — {positions} position(s) ouverte(s), {transactions} opération(s) détectée(s), dont {inserted} nouvelle(s).',
  'import.sectionsTitle': 'Feuilles détectées dans le fichier',
  'import.sectionLine': '{sheet} → {count} × {kind} ({rows} lignes source)',

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
  'table.mapping': 'Correspondance',
  'table.quantity': 'Qté',
  'table.avgPrice': 'Prix de revient',
  'table.price': 'Cours',
  'table.value': 'Valeur ({currency})',
  'table.unrealized': 'Latent ({currency})',
  'table.performance': 'Perf.',
  'table.since': 'Depuis',
  'table.account': 'Compte',
  'table.empty': 'Aucune position. Importez un relevé XTB ou ajoutez une ligne manuellement.',
  'table.lots': {
    one: '{count} lot',
    other: '{count} lots',
  },
  'table.short': 'vente à découvert',
  'table.manual': 'manuelle',

  'filters.account': 'Compte',
  'filters.all': 'Tous',
  'filters.sortBy': 'Trier par',
  'sort.value': 'Valeur de marché',
  'sort.unrealized': 'Résultat latent',
  'sort.performance': 'Performance %',
  'sort.symbol': 'Symbole',

  // --- Prices ---------------------------------------------------------------
  'prices.title': 'Cours de marché',
  'prices.subtitle':
    "Les fournisseurs gratuits limitent fortement les requêtes : un rafraîchissement traite la liste dans un budget de temps et indique ce qu'il reste. Les données déjà en cache ne sont jamais redemandées.",
  'prices.refresh': 'Rafraîchir les cours',
  'prices.refreshing': 'Rafraîchissement…',
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
  'prices.noProvider': "{symbol} : aucun fournisseur de données n'est disponible.",
  'prices.failed': '{symbol} : échec de la récupération via {provider}.',
  'prices.budgetReached': 'Budget de temps atteint, {remaining} instrument(s) restant(s).',
  'prices.noFallbackConfigured':
    "Yahoo limite les requêtes et aucun fournisseur de repli n'est configuré. Ajoutez une clé gratuite TWELVEDATA_API_KEY dans .env (inscription par e-mail, sans carte) pour que le rafraîchissement continue de fonctionner.",
  'table.trend': 'Tendance (90j)',
  'mapping.verified': 'vérifiée',
  'mapping.verifiedTooltip': 'Un fournisseur a renvoyé des données pour ce symbole le {date} ({provider}).',

  // --- Placeholder pages ---------------------------------------------------
  'watchlist.title': 'Watchlist',
  'watchlist.description': "Titres suivis mais non détenus, et analyse du moment d'entrée.",
  'gems.title': 'Pépites',
  'gems.description':
    "Recherche de titres prometteurs par filtrage sur un univers d'indices.",
  'placeholder.comingIn': 'Cette page arrive avec la {phase} du projet.',
  'phase.4': 'phase 4',
  'phase.5': 'phase 5',
}
