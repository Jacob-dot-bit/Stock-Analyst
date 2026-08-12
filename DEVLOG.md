# Journal de développement

Historique des étapes, décisions, bugs et résultats du projet Stock Analyst.

**Rôle de ce document.** Le [README](README.md) décrit l'état *actuel* du projet — ce qu'il
fait et comment l'utiliser. Ce journal décrit *comment on y est arrivé* : ce qu'on a
essayé, ce qui a cassé, pourquoi, et ce qu'on en a conclu. Il évite de refaire deux fois
la même erreur et de revenir sans le savoir sur une décision déjà tranchée.

## Conventions

Une entrée par événement notable, la plus récente en bas de sa section.

- **Décision** — contexte, choix retenu, raison, conséquences. Une décision annulée n'est
  jamais effacée : elle est marquée ~~barrée~~ avec un renvoi vers celle qui la remplace.
- **Bug** — symptôme observé, cause réelle, correctif, vérification. La cause compte plus
  que le correctif : c'est elle qui empêche la récidive.
- **Étape** — ce qui a été livré et comment ça a été vérifié.

Consigner un bug **au moment où on le comprend**, pas après coup : la cause s'oublie vite.

**Aucune donnée personnelle dans le dépôt.** Numéros de compte, montants de portefeuille
et fichiers d'export n'y figurent pas. Les exemples chiffrés sont fictifs mais cohérents,
et signalés comme tels. Les fixtures de test utilisent des numéros de compte inventés.

---

# Phase 0 — Cadrage (2026-08-11)

## Étape — Recherche de faisabilité

Objectif initial : brancher l'application sur l'API XTB pour suivre le portefeuille
automatiquement.

## Décision 0.1 — Abandon de l'API XTB, architecture par import de fichier

**Contexte.** La recherche a établi que **l'API XTB n'existe plus**. Elle a été coupée le
**14 mars 2025**.

Sources :
- Centre d'aide XTB : « *API access is no longer available. The service was discontinued
  on March 14, 2025.* »
  ([xtb.com](https://www.xtb.com/int/help-center/our-platforms-6-4/does-xtb-offer-investment-automation-tools-4))
- Le domaine de documentation `developers.xstore.pro` ne résout plus en DNS.
- Les wrappers communautaires sont archivés
  ([`pawelkn/xapi-python`](https://github.com/pawelkn/xapi-python), archivé le 26/08/2025).
- XTB ne propose **aucun remplaçant** : ni API, ni trading automatisé, ni copy trading.

**Décision.** L'application est alimentée par l'**export de fichier xStation**, et conçue
comme **broker-agnostique**.

**Alternative écartée.** Scraper la plateforme web avec les identifiants du compte :
quasi certainement contraire aux CGU, risque de blocage du compte, et obligerait à stocker
des identifiants financiers. Écartée sans hésitation.

**Conséquences.**
- Pas de synchronisation automatique : l'utilisateur dépose un fichier.
- Aucun identifiant n'est demandé ni stocké — surface de risque nulle de ce côté.
- L'outil survit à un changement de courtier.
- Le parsing devient le point de fragilité principal du projet → d'où l'effort de
  robustesse et de tests investi en phase 1.

## Décision 0.2 — Stack et périmètre

| Sujet | Choix | Raison |
|---|---|---|
| Backend | FastAPI + SQLite | Python pour l'analyse (pandas) ; SQLite suffit en local mono-utilisateur |
| Frontend | React + Vite + TypeScript | Dashboard multi-pages interactif demandé |
| Rafraîchissement | À la demande | Pas de tâche de fond à maintenir |
| Marchés | Mondial | Portefeuille US + Europe |
| Sources | Gratuites uniquement | Contrainte posée d'entrée |
| Synthèse qualitative | API Perplexity | Seule dépense acceptée |

## Décision 0.3 — Encadrement de l'usage de Perplexity

**Contexte.** Tarification Sonar : coût aux tokens **plus** un frais de **5 à 14 $ par
1000 requêtes**. Un screening de masse sur quelques milliers de titres coûterait des
dizaines d'euros par passage.

**Décision.** Perplexity est réservé à l'analyse qualitative **d'un titre à la fois, sur
demande explicite**, avec mise en cache (TTL 7 jours). Jamais de screening de masse. Le
LLM **ne participe pas au score** : il le commente.

**Conséquence.** Le screening des « pépites » doit être conçu en deux étages — filtrage
local sur cache, puis enrichissement réseau du seul top N.

---

# Phase 1 — Socle, import XTB, page Portefeuille (2026-08-11)

## Étape 1.1 — Squelette et modèle de données

Livré : arborescence backend/frontend, modèles SQLAlchemy, parser d'export, couche de
correspondance des symboles, page Portefeuille, 81 tests.

## Décision 1.1 — Conserver la ligne source de chaque import

Chaque transaction et position stocke la ligne d'origine du fichier en JSON (champ `raw`).

**Raison.** Permet de recalculer ou corriger a posteriori sans redemander le fichier à
l'utilisateur. Le coût de stockage est négligeable à cette échelle.

**Résultat.** Décision payante dès la phase 1b : les colonnes de taux de change, d'abord
non exploitées, étaient déjà en base.

## Décision 1.2 — Une donnée absente n'est jamais un zéro

Une position sans valorisation est **exclue des totaux** et signalée, jamais comptée à
zéro.

**Raison.** Un total faux ayant l'apparence d'un total juste est plus dangereux qu'un
total explicitement partiel. Le même principe s'appliquera au scoring : un pilier sans
données est retiré du calcul et les poids renormalisés.

## Bug 1.1 — `parse_number("1 234,56 EUR")` retournait `None`

**Symptôme.** Test en échec sur un montant suivi de sa devise.

**Cause.** Le nettoyage filtrait caractère par caractère avec `[^\d,.\-+eE]`, en gardant
`e`/`E` pour la notation scientifique. Le « E » de « EUR » survivait, produisant
`"1234.56E"`, invalide.

**Correctif.** Extraction du premier nombre par expression régulière (`_NUMBER_TOKEN`) au
lieu d'un filtrage. La notation scientifique est explicitement abandonnée : absente des
exports courtier, elle rendait ambiguë la détection des devises accolées.

**Bénéfice imprévu.** Le passage à l'extraction a permis d'ajouter gratuitement la
notation comptable `(1 234,56)` → `-1234.56`.

## Bug 1.2 — FastAPI refusait de démarrer sur la route `DELETE`

**Symptôme.** `AssertionError: Status code 204 must not have a response body` au
chargement du module.

**Cause.** Un `status_code=204` sans `response_class` explicite : FastAPI tente de
sérialiser un corps de réponse, interdit sur un 204.

**Correctif.** `response_class=Response` et retour d'un `Response(status_code=204)`.

## Bug 1.3 — Tables absentes dans les tests d'API

**Symptôme.** `no such table: instruments`, alors que `create_all` avait été appelé.

**Cause.** `create_engine("sqlite://")` ouvre une base en mémoire **distincte par
connexion**. Les tables créées sur une connexion sont invisibles depuis le thread qui sert
les requêtes HTTP. Les tests du service passaient par chance (même thread, même
connexion réutilisée), ce qui masquait le problème.

**Correctif.** `poolclass=StaticPool` sur les moteurs de test.

**Leçon.** Un test qui passe « par chance » sur un pool de connexions est un faux positif.

## Décision 1.3 — Afficher les correspondances automatiques comme « non vérifiées »

**Contexte.** La conversion de suffixe (`.FR` → `.PA`) ne transforme que le suffixe,
jamais la racine du symbole. `ERICB.SE` devient `ERICB.ST` alors que Yahoo attend
`ERIC-B.ST` — le résultat est faux mais paraît valide.

**Décision.** Une correspondance automatique s'affiche **« non vérifiée »** en gris, et non
en vert comme une validation. Seule une correction manuelle donne « confirmée ». Un bouton
« corriger » est disponible sur chaque ligne, y compris celles déjà résolues.

**Raison.** Afficher en vert une hypothèse jamais confrontée à un fournisseur donne une
assurance que rien ne justifie.

**Suite prévue.** En phase 2, une correspondance ayant effectivement servi à récupérer des
cours pourra passer en « vérifiée ».

## Résultat de phase — 81 tests, import de bout en bout fonctionnel

Vérifié dans le navigateur sur un fichier synthétique. **Réserve à ce stade** : le format
réel n'avait pas encore été confronté. C'était le risque n°1 identifié, d'où la demande
d'un export réel à l'utilisateur.

---

# Phase 1b — Confrontation aux fichiers réels (2026-08-12)

Deux exports de production fournis par l'utilisateur : un compte titres et un PEA.
**Retour initial : « 0 position, 0 opération, aucune table reconnue ».**

Cette confrontation a révélé **sept bugs** que le fichier synthétique ne pouvait pas
exposer — la structure supposée était fausse sur presque tous les points.

## Bug 1b.1 — Le classeur paraissait entièrement vide *(cause du symptôme signalé)*

**Symptôme.** Aucune table reconnue ; `max_row = 1` sur les trois feuilles.

**Cause.** Les exports XTB déclarent une dimension `A1:A1` **erronée** dans leurs
métadonnées. En mode `read_only`, openpyxl fait confiance à cette déclaration sans
inspecter les données, et ne renvoie qu'une seule cellule.

**Correctif.** Chargement du classeur en mode normal (`read_only=False`). Le surcoût
mémoire est négligeable : quelques centaines de lignes par fichier.

**Leçon.** `read_only=True` est une optimisation qui suppose des métadonnées correctes.
Sur des fichiers produits par un tiers, cette hypothèse ne tient pas.

## Bug 1b.2 — La raison sociale était prise pour un symbole boursier

**Symptôme.** Aucun symbole exploitable même une fois les données lues.

**Cause.** Confusion de colonnes. Dans le format réel, **`Ticker` porte le symbole**
(`CP.US`) et **`Instrument` la raison sociale** (`Canadian Pacific`). L'alias `instrument`
était mappé sur `symbol`.

**Correctif.** `ticker` → `symbol`, `instrument` → `name`, avec priorité explicite de
`ticker`. La raison sociale est désormais exploitée et affichée sous le symbole.

## Bug 1b.3 — Les positions auraient été comptées deux fois

**Symptôme.** Détecté à l'analyse de structure, avant de produire un total faux.

**Cause.** Les positions ouvertes sont sur **deux niveaux** :

```
My Trades | ASML       | ASML.NL | STOCK |     | 1.0 | ...   <- ligne agrégée
My Trades | 1636247573 | ASML.NL |       | BUY | 1.0 | ...   <- lot
```

Un titre = une ligne agrégée + N lignes de lots. Sur les fichiers réels, **38 positions
occupent 153 lignes**. Les traiter uniformément aurait **doublé le portefeuille**.

**Règle de distinction retenue.** Ligne agrégée = `Type` vide et `Category` renseignée ;
lot = l'inverse. Vérifiée sur l'intégralité des deux fichiers : 38 lignes agrégées et
115 lots, **aucune ambiguïté**.

**Correctif.** Seules les lignes agrégées deviennent des positions. Les lots servent à
dater l'entrée (la plus ancienne), compter les tranches, déduire le sens et récupérer le
cours. Un repli traite les lots comme des positions si aucun niveau agrégé n'existe — pour
ne rien perdre sur une variante de format.

## Bug 1b.4 — Violation de contrainte d'unicité à l'import

**Symptôme.** `IntegrityError: UNIQUE constraint failed: transactions.external_id,
transactions.type` sur le fichier du compte titres. Le premier import échouait
silencieusement côté client (réponse vide).

**Cause — double.**

1. Ma première inspection tronquait l'affichage à 16 colonnes, d'où la conclusion erronée
   que les positions fermées n'avaient pas d'identifiant. Elles en ont un : `Position ID`,
   colonne 24 sur 25.
2. Cet identifiant **n'est pas unique**. Une position soldée en plusieurs fois produit
   plusieurs lignes portant le même `Position ID` : **223 lignes pour 220 identifiants**.

**Correctif.** La clé de déduplication combine l'identifiant **et** les détails
d'exécution (symbole, dates d'ouverture et de clôture, volume, prix), plus un compteur
d'occurrences pour les lignes rigoureusement identiques. Stable d'un import à l'autre,
unique par ligne.

**Leçon.** Ne jamais conclure sur la structure d'un fichier depuis un affichage tronqué.
Le script d'inspection affiche désormais toutes les colonnes.

## Bug 1b.5 — Doublons non détectés au sein d'un même import

**Symptôme.** Découvert en corrigeant 1b.4 : la contrainte sautait malgré le contrôle
d'existence.

**Cause.** Le contrôle faisait un `SELECT` en base, mais les objets ajoutés à la session
et non encore *flushés* sont invisibles d'une requête. Deux lignes de clé identique dans
le même fichier passaient donc toutes deux le contrôle, avant de faire échouer la
contrainte au flush.

**Correctif.** Un ensemble `seen` en mémoire complète le contrôle en base pour couvrir les
doublons intra-import.

## Bug 1b.6 — Identifiants numériques rendus en flottants

**Symptôme.** `external_id` valant `"1677685567.0"` au lieu de `"1677685567"`.

**Cause.** openpyxl renvoie les entiers d'un classeur en `float`.

**Correctif.** Helper `_clean_id` qui normalise les entiers flottants.

**Pourquoi ça comptait.** Un identifiant mal formaté reste fonctionnel pour la
déduplication tant qu'il est *cohérent*, mais casse tout rapprochement futur avec une
autre source, et fait mauvais effet en base.

## Bug 1b.7 — Colonne « Cours » vide sur toutes les lignes

**Symptôme.** Constaté visuellement dans l'interface après un import réussi.

**Cause.** `Current price` n'est renseigné que sur les lignes de lots, pas sur la ligne
agrégée.

**Correctif.** Le cours est repris du premier lot disponible.

**Piège évité.** Le déduire par `valeur de marché / quantité` aurait été tentant et
**faux** : la valeur de marché est en devise du compte (EUR), le prix de revient en devise
de l'instrument (USD). Le tableau aurait affiché côte à côte deux prix incomparables.

## Décision 1b.1 — La catégorie du courtier prime sur toute heuristique de nommage

**Contexte.** Mon heuristique classait `GOLD.US` en matière première à cause du mot
« GOLD » dans le symbole. **`GOLD.US` est Barrick Gold**, une action minière cotée au NYSE,
parfaitement analysable. Elle était exclue à tort de toute analyse future.

**Décision.** La colonne `Category` de l'export (`STOCK`, `ETF`, `CFD`) fait autorité.
L'heuristique sur le symbole n'est plus qu'un repli pour les saisies manuelles, où aucune
catégorie n'est disponible.

**Conséquence.** Les CFD ne sont plus signalés comme des anomalies : leur absence de
correspondance est le comportement attendu, pas un problème à corriger. Les alertes ne
listent plus que les vrais cas douteux.

**Résultat mesuré.** Symboles signalés : passés de 7 à 1 sur les fichiers réels. Le seul
restant, `US592CVR0133`, est un CVR — un droit conditionnel sans cotation suivie, donc
légitimement non résolu.

## Décision 1b.2 — L'instantané de positions est remplacé compte par compte

**Contexte.** Un export XTB ne couvre **qu'un seul compte**. L'utilisateur en a deux
(compte titres « My Trades » et « PEA »), donc deux fichiers distincts.

**Problème identifié avant qu'il ne cause un dégât.** La logique initiale supprimait
*toutes* les positions issues d'un import avant d'insérer les nouvelles. Importer le
relevé PEA aurait donc **effacé les positions du compte titres**.

**Décision.** La suppression est limitée aux comptes présents dans le fichier, identifiés
par la colonne `Product`. Repli sur un remplacement global si le fichier ne porte aucune
information de compte.

**Vérification.** Test dédié : importer A, puis B, puis à nouveau A — les positions de B
restent intactes.

## Décision 1b.3 — La valeur d'achat est déduite, pas approximée

**Contexte.** L'export ne fournit pas de colonne « valeur d'achat » pour les positions
ouvertes (elle n'existe que sur les positions fermées).

**Décision.** `valeur d'achat = valeur de marché − résultat latent`. Les deux grandeurs
sont dans la devise du compte, la déduction est donc **exacte**, pas approchée.

**Alternative écartée.** `quantité × prix de revient` : ces deux grandeurs sont en devise
de l'instrument, ce qui aurait mélangé USD et EUR dans un même total.

## Résultat de phase — validation au centime près

> Montants ci-dessous **anonymisés** : ce sont des valeurs d'illustration, cohérentes
> entre elles mais fictives. Les chiffres réels ne figurent pas dans le dépôt.

```
TOTAL         38 positions | valeur 8 730,40 € | latent +2 420,40 € | +38,36 %
  My Trades   27 positions | investi 4 210,00 € | valeur 6 315,40 € | +50,01 %
  PEA         11 positions | investi 2 100,00 € | valeur 2 415,00 € | +15,00 %
```

**La méthode de validation, elle, est bien réelle** : chaque feuille « Open Positions »
contient ses propres lignes de synthèse (`Product | Value` et `Product | Profit`),
calculées par XTB indépendamment du détail des positions. Les totaux reconstruits par
l'application correspondent **exactement**, au centime, à ces lignes — pour les deux
comptes.

C'est la meilleure validation disponible : une source de vérité présente dans le fichier
lui-même, qu'aucune erreur de parsing ne peut reproduire par hasard. Un doublement des
positions (bug 1b.3) ou une mauvaise déduction de la valeur d'achat (décision 1b.3)
auraient sauté immédiatement.

Autres vérifications : 1 395 transactions importées, 223 positions fermées, **0 position
exclue** faute de données, réimport des deux fichiers → **0 insertion** (idempotence
confirmée sur données réelles).

**128 tests passent.** Les fixtures reproduisent désormais le format réel : 25 colonnes,
structure à deux niveaux, clôtures partielles partageant un identifiant, lignes « Total »
à écarter.

## Note technique — pas de migrations de schéma

Le schéma évolue par `create_all`, sans outil de migration. À chaque changement de modèle,
la base de développement est **supprimée et reconstruite par réimport**. Acceptable tant
que la source de vérité reste les fichiers d'export.

**À revoir si** des données non reconstructibles apparaissent (watchlist saisie à la main,
historique de scores, notes personnelles) : il faudra alors introduire Alembic. La
watchlist arrive en phase 4 — c'est le déclencheur à surveiller.

---

# À suivre

| Phase | Contenu | État |
|---|---|---|
| 2 | Couche providers, cours de marché, graphiques | à faire |
| 3 | Moteur de scoring (5 piliers, `scoring.yaml`) | à faire |
| 4 | Watchlist et timing d'entrée | à faire |
| 5 | Page Pépites (screener) | à faire |
| 6 | Synthèse qualitative Perplexity | à faire |

**Points ouverts à traiter en phase 2**

- Faire passer les correspondances de « non vérifiée » à « vérifiée » une fois qu'un
  fournisseur a effectivement servi des données pour ce symbole.
- Les taux de change (`Open/Close Conversion Rate`) sont capturés mais pas encore
  exploités — utiles pour ventiler la performance entre effet titre et effet devise.
- `yfinance` cassera périodiquement (endpoints non officiels) : la chaîne de repli vers
  Stooq doit être testée pour de bon, pas seulement écrite.
- Introduire Alembic avant la phase 4 si la watchlist doit survivre aux changements de
  schéma.
