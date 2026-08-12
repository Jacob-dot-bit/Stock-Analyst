# Stock Analyst

Application locale de suivi et d'analyse d'un portefeuille d'actions : décider de
**conserver ou vendre** ses positions, d'**entrer ou attendre** sur les titres suivis, et
repérer des **pépites** — en croisant plusieurs sources de données publiques.

> Cet outil produit des indicateurs à partir de données publiques. Ce ne sont pas des
> conseils en investissement, et les décisions restent les vôtres.

📓 Le [journal de développement](DEVLOG.md) retrace les étapes, les décisions et leurs
raisons, ainsi que les bugs rencontrés et leurs causes. Ce README décrit l'état *actuel* du
projet ; le journal explique *comment on y est arrivé*.

---

## À lire en premier : l'API XTB n'existe plus

XTB a **définitivement fermé son API le 14 mars 2025**. Leur centre d'aide est explicite :
« *API access is no longer available. The service was discontinued on March 14, 2025.* »
([source](https://www.xtb.com/int/help-center/our-platforms-6-4/does-xtb-offer-investment-automation-tools-4))

Concrètement :

- les hôtes `xapi.xtb.com` et `ws.xtb.com` sont coupés ;
- le domaine de documentation `developers.xstore.pro` ne résout même plus en DNS ;
- les bibliothèques communautaires ont été archivées (ex. [`pawelkn/xapi-python`](https://github.com/pawelkn/xapi-python), archivée le 26/08/2025) ;
- XTB ne propose **aucun remplaçant** : ni API, ni trading automatisé, ni copy trading.

**Aucune synchronisation automatique du compte n'est donc possible.** L'application est
alimentée par l'**export de fichier** depuis xStation. C'est la seule voie fiable et
conforme aux conditions d'utilisation — et elle a l'avantage de ne demander aucun
identifiant : rien de sensible n'est stocké par l'application.

### Exporter ses données depuis xStation

1. Ouvrir [xStation 5](https://xstation5.xtb.com/) ;
2. onglet **Account history** → bouton **Export** ;
3. période **All**, format **Excel** ;
4. déposer le fichier obtenu dans la page Portefeuille de l'application.

Le fichier produit contient trois feuilles — *Open Positions*, *Closed Positions*,
*Cash Operations* — toutes traitées en un seul import.

**Un export ne couvre qu'un compte à la fois.** Si vous avez plusieurs comptes (compte
titres et PEA, par exemple), exportez-les séparément et importez les deux fichiers :
ils cohabitent sans s'écraser, chacun identifié par sa colonne *Product*.

L'import est **idempotent** : réimporter le même fichier, ou une période qui se
chevauche, ne crée aucun doublon. Les positions ouvertes sont un instantané et
remplacent le précédent import **du même compte uniquement** ; les positions saisies à
la main sont toujours préservées.

---

## Démarrage

Prérequis : Python 3.13+, Node 20+.

### Backend

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

```bash
cd backend && .venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

Documentation interactive de l'API : <http://127.0.0.1:8000/docs>

### Frontend

```bash
cd frontend && npm install && npm run dev
```

Interface : <http://localhost:5173>. Le serveur de développement relaie `/api` vers le
backend, il n'y a donc rien à configurer côté CORS.

### Configuration

Copier `.env.example` vers `.env` à la racine. **Toutes les clés sont optionnelles** :
l'application démarre sans aucune d'elles, et les fonctionnalités concernées se
désactivent proprement plutôt que de faire échouer le démarrage.

| Variable | Usage | Coût |
|---|---|---|
| `BASE_CURRENCY` | Devise des totaux du portefeuille | — |
| `FINNHUB_API_KEY` | Actualités, profils (60 appels/min en gratuit) | gratuit |
| `SEC_USER_AGENT` | Fondamentaux officiels US via SEC EDGAR. Format `Nom Prénom email@exemple.com` — la SEC rejette les requêtes anonymes | gratuit |
| `PERPLEXITY_API_KEY` | Synthèse qualitative | **payant** |

### Tests

```bash
cd backend && .venv/bin/python -m pytest
```

Les tests réseau sont marqués `@pytest.mark.network` et exclus par défaut.

---

## Architecture

```
backend/app/
├── config.py            Configuration via .env, aucune clé en dur
├── models.py            ORM SQLAlchemy (SQLite local)
├── ingest/
│   ├── xtb_import.py    Parsing de l'export xStation
│   └── service.py       Persistance, déduplication, idempotence
├── symbols/mapping.py   Correspondance symboles XTB ↔ fournisseurs
├── routers/             Endpoints HTTP
├── providers/           Sources de données (phase 2)
└── analysis/            Indicateurs et scoring (phase 3)

frontend/src/
├── api/                 Client HTTP typé
├── components/          Composants réutilisables
└── pages/               Portefeuille, Watchlist, Pépites
```

### Deux partis pris à connaître

**1. Le parser est tolérant, jamais silencieux.** Le format de l'export xStation n'est pas
documenté publiquement et varie selon la langue de l'interface. Les colonnes sont donc
reconnues par alias normalisés (français et anglais) et les tables classées par *signature
de colonnes* plutôt que par titre de section. Tout ce qui n'est pas compris remonte dans
les avertissements de l'import, et la ligne source est conservée intégralement en base
(champ `raw`) pour pouvoir tout recalculer sans redemander le fichier.

Si un export ne passe pas, c'est `COLUMN_ALIASES` dans
[`xtb_import.py`](backend/app/ingest/xtb_import.py) qu'il faut compléter.

Quatre pièges du format réel, tous vérifiés sur des exports de production et couverts par
des tests — ils valent d'être connus avant toute modification du parser :

| Piège | Conséquence si ignoré |
|---|---|
| Le classeur déclare une dimension `A1:A1` erronée | En mode `read_only`, openpyxl s'y fie et le fichier paraît **vide** |
| `Ticker` porte le symbole, `Instrument` la raison sociale | « Canadian Pacific » serait pris pour un symbole boursier |
| Les positions ouvertes sont sur **deux niveaux** : une ligne agrégée par titre, puis une ligne par lot | Chaque position serait comptée **deux fois** |
| Le `Position ID` des positions fermées n'est **pas unique** (clôtures partielles : 223 lignes pour 220 identifiants) | Violation de contrainte d'unicité à l'import |

**2. Une donnée absente n'est jamais traitée comme un zéro.** Une position dont les
montants manquent est **exclue des totaux** et signalée, plutôt que comptée à zéro — ce
qui donnerait un total faux avec l'apparence d'un total juste. Le même principe
s'appliquera au scoring : un pilier sans données est retiré du calcul et les poids
renormalisés, avec un score marqué « partiel ».

### Cohérence des montants

L'export ne fournit pas de « valeur d'achat » pour les positions ouvertes : elle est
déduite exactement par `valeur de marché − résultat latent`, les deux étant exprimés dans
la devise du compte. Le cours affiché provient des lignes de lots et reste dans la devise
de l'instrument — il n'est **pas** recalculé par `valeur / quantité`, ce qui donnerait un
prix en euros incomparable au prix de revient.

Aucune conversion de change n'est appliquée. Les totaux se vérifient au centime près
contre les lignes de synthèse du fichier XTB.

### Correspondance des symboles

XTB suffixe par pays (`AAPL.US`, `TTE.FR`), Yahoo par place de cotation (`AAPL`, `TTE.PA`).
Il n'existe aucune table officielle : l'application convertit les suffixes, ce qui couvre
la grande majorité des cas.

**Limite importante** : la conversion ne touche que le suffixe, jamais la racine du
symbole. `ERICB.SE` devient ainsi `ERICB.ST` alors que Yahoo attend `ERIC-B.ST`. Une
correspondance automatique est donc affichée comme **« non vérifiée »** tant qu'aucune
donnée n'a été récupérée avec elle, et se corrige d'un clic depuis le tableau des
positions. Les corrections sont persistées et réappliquées aux imports suivants.

La décision repose sur la **catégorie fournie par le courtier** (`STOCK`, `ETF`, `CFD`),
et non sur une heuristique de nommage. C'est important : `GOLD.US` est *Barrick Gold*,
une action parfaitement analysable, qu'un filtre sur le mot « GOLD » rejetterait à tort.
Les CFD (`US500`, `BITCOIN`, `NATGAS`…) sont laissés sans correspondance — ils n'ont pas
de fondamentaux — et ne sont pas signalés comme une anomalie, puisque c'est le
comportement attendu.

---

## État d'avancement

| Phase | Contenu | État |
|---|---|---|
| 1 | Socle, import XTB, page Portefeuille | ✅ terminée |
| 2 | Couche providers, cours de marché, graphiques | à venir |
| 3 | Moteur de scoring (5 piliers, `scoring.yaml`) | à venir |
| 4 | Watchlist et timing d'entrée | à venir |
| 5 | Page Pépites (screener) | à venir |
| 6 | Synthèse qualitative Perplexity | à venir |

### Sources de données prévues (phase 2)

| Source | Rôle | Portée | Remarque |
|---|---|---|---|
| yfinance | Cours + fondamentaux de base | mondiale | Seule source gratuite réellement mondiale. Non officielle : **cassera périodiquement**, d'où la chaîne de repli |
| Stooq | Cours de repli (EOD) | US + Europe | Sans clé, très stable |
| SEC EDGAR | Fondamentaux officiels (XBRL) | **US uniquement** | Gratuit, officiel, sans clé |
| Finnhub | Actualités, profils | mondiale | 60 appels/min en gratuit |
| Perplexity | Synthèse qualitative | mondiale | **Payant** — sur demande, un titre à la fois, mis en cache |

Asymétrie assumée : la couverture fondamentale est excellente sur les valeurs américaines
et nettement plus lacunaire ailleurs en gratuit. L'interface affiche systématiquement la
couverture des données et la source réellement utilisée.

### Réserves

- **Aucune donnée en temps réel** : les cours gratuits sont différés. L'outil vise
  l'analyse de fond, pas le trading intraday.
- **Objectifs de cours et notes d'analystes** sont très largement passés en payant ; le
  pilier sentiment reposera surtout sur le flux d'actualités.
- Pas de scraping de Finviz, TradingView ou Yahoo (hors yfinance) : contraire à leurs
  conditions d'utilisation.
