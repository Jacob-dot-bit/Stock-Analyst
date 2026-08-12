"""Parsing de l'export de compte xStation (XLSX / CSV).

Contexte : l'API XTB a été supprimée le 14 mars 2025. L'export de fichier est
désormais le seul moyen fiable et légal de récupérer ses positions. Chemin dans
xStation : *Account history* → *Export*.

Structure réelle observée sur des exports 2026 (une feuille par section) ::

    Feuille « Open Positions »
        Account number | 1234567
        Open Positions
        Data as of report generated | ...
        Product | Metric | Amount | Currency        <- petit tableau de synthèse
        My Trades | Value | 9344.16 | EUR
        ...
        Product | Instrument/Position | Ticker | Category | Type | Volume | ...
        My Trades | ASML       | ASML.NL | STOCK |      | 1.0 | ...   <- ligne agrégée
        My Trades | 1636247573 | ASML.NL |       | BUY  | 1.0 | ...   <- lot

Trois pièges que ce module traite explicitement :

1. **Dimension XLSX erronée.** Ces fichiers déclarent ``A1:A1``. En mode
   ``read_only`` openpyxl fait confiance à cette métadonnée et ne renvoie qu'une
   seule cellule — le classeur paraît vide. Le classeur est donc chargé en mode
   normal.
2. **``Ticker`` est le symbole, ``Instrument`` est la raison sociale.** Confondre
   les deux fait passer « Canadian Pacific » pour un symbole boursier.
3. **Les positions ouvertes sont sur deux niveaux** : une ligne agrégée par titre,
   suivie d'une ligne par lot. Les additionner compterait chaque position deux
   fois. Seules les lignes agrégées deviennent des positions ; les lots servent à
   dater l'entrée et à compter les tranches.

Le parser reste tolérant : colonnes reconnues par alias normalisés (français et
anglais), tables classées par signature de colonnes plutôt que par titre, et tout
ce qui n'est pas compris est remonté dans ``warnings`` avec la ligne source
conservée dans ``raw``. Si un export ne passe pas, c'est ``COLUMN_ALIASES`` qu'il
faut compléter.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from app.models import TxType

# --- Colonnes canoniques et leurs alias -------------------------------------
# Comparaison après normalisation : minuscules, sans accents, sans ponctuation.
# « % » devient « pct » pour distinguer « Net Profit » de « Net Profit % ».

COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    # Identité de l'instrument
    # ATTENTION : « Ticker » est le symbole, « Instrument » la raison sociale.
    "symbol": ("ticker", "symbol", "symbole"),
    "name": ("instrument", "instrumentposition", "nom", "libelle", "designation"),
    "category": ("category", "categorie", "classe"),
    "account": ("product", "produit", "compte", "account"),
    # Identifiants
    "position_id": ("positionid", "position", "ticket", "idposition"),
    "cash_id": ("id", "idoperation", "operationid"),
    # Sens et taille
    "type": ("type", "direction", "side", "sens", "typedoperation"),
    "volume": ("volume", "quantite", "quantity", "qty", "lots", "nombredeparts"),
    # Prix et dates
    "open_time": ("opentime", "opentimeutc", "heuredouverture", "dateouverture", "ouverture"),
    "open_price": ("openprice", "prixdouverture", "coursdouverture", "prixouverture"),
    "close_time": ("closetime", "closetimeutc", "heuredefermeture", "datefermeture", "fermeture"),
    "close_price": ("closeprice", "prixdefermeture", "coursdecloture", "prixfermeture"),
    "market_price": ("currentprice", "marketprice", "prixdumarche", "coursactuel"),
    # Montants
    "market_value": ("value", "valeur", "valeurdemarche", "marketvalue"),
    "purchase_value": ("purchasevalue", "valeurdachat", "montantachat"),
    "sale_value": ("salevalue", "valeurdevente", "montantvente"),
    "gross_pl": ("grossprofit", "grosspl", "profitbrut", "plbrut", "resultatbrut"),
    "net_pl": ("netprofit", "profitloss", "netpl", "profitnet", "plnet", "resultatnet", "profit"),
    "net_pl_pct": ("netprofitpct", "profitpct", "plpct", "rendement"),
    "amount": ("amount", "montant"),
    "commission": ("commission", "opencommission", "commissions", "frais"),
    "swap": ("swap", "swaps", "pointsdeswap"),
    "margin": ("margin", "marge"),
    "rollover": ("rollover",),
    # Taux de change appliqués par le courtier : indispensables pour rapprocher un
    # prix libellé en devise de l'instrument d'un montant en devise du compte.
    "open_fx_rate": ("openconversionrate", "tauxdechangeouverture"),
    "close_fx_rate": ("closeconversionrate", "tauxdechangefermeture"),
    "close_origin": ("closeorigin", "originefermeture"),
    # Divers
    "sl": ("sl", "stoploss"),
    "tp": ("tp", "takeprofit"),
    "time": ("time", "timeutc", "heure", "date", "dateheure", "datetime"),
    "comment": ("comment", "commentaire", "description", "remarque"),
    "currency": ("currency", "devise"),
    "metric": ("metric", "metrique", "indicateur"),
}

#: Alias ambigus entre plusieurs colonnes canoniques, réarbitrés par table.
_AMBIGUOUS = {"id", "position"}


def _normalize(value: Any) -> str:
    """Minuscules, sans accents, sans ponctuation. « % » est conservé en « pct »."""
    if value is None:
        return ""
    text = str(value).strip().lower().replace("%", "pct")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", text)


_ALIAS_LOOKUP: dict[str, str] = {}
for _canonical, _aliases in COLUMN_ALIASES.items():
    for _alias in _aliases:
        _ALIAS_LOOKUP.setdefault(_normalize(_alias), _canonical)


def _match_column(header: Any) -> str | None:
    return _ALIAS_LOOKUP.get(_normalize(header))


# --- Conversions de valeurs --------------------------------------------------

#: Isole le premier nombre de la chaîne, séparateurs de milliers compris.
#: On extrait plutôt que de filtrer caractère par caractère : sinon « 1 234,56 EUR »
#: laisse traîner le « E » de la devise et la conversion échoue.
_NUMBER_TOKEN = re.compile(r"[-+]?\d[\d\s.,]*")


def parse_number(value: Any) -> float | None:
    """Convertit un nombre en tolérant les formats français et anglais.

    Gère « 1 234,56 », « 1,234.56 », les espaces insécables, les devises accolées
    et la notation comptable entre parenthèses. Retourne ``None`` plutôt que de
    lever : une cellule illisible ne doit pas faire échouer tout l'import.

    La notation scientifique n'est volontairement pas gérée : absente des exports
    courtier, elle rendrait ambiguë la détection des devises accolées.
    """
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).replace("\xa0", " ").replace(" ", " ").strip()
    if not text:
        return None

    # Notation comptable : « (1 234,56) » vaut -1234,56
    negated = text.startswith("(") and text.endswith(")")
    if negated:
        text = text[1:-1].strip()

    match = _NUMBER_TOKEN.search(text)
    if match is None:
        return None

    text = match.group(0).replace(" ", "").rstrip(".,")
    if not text or text in {"-", "+"}:
        return None

    has_comma, has_dot = "," in text, "." in text
    if has_comma and has_dot:
        # Le séparateur décimal est celui qui apparaît en dernier.
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif has_comma:
        # Virgule seule : décimale (« 12,5 ») ou séparateur de milliers (« 1,234 ») ?
        if re.fullmatch(r"-?\d{1,3}(,\d{3})+", text):
            text = text.replace(",", "")
        else:
            text = text.replace(",", ".")

    try:
        number = float(text)
    except ValueError:
        return None

    return -number if negated else number


_DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%Y %H:%M",
    "%d.%m.%Y",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y",
)


def parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value

    text = str(value).strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


# --- Classification des opérations de caisse --------------------------------
# L'ordre compte : « Free funds interest tax » doit tomber en TAX, pas en INTEREST.

_CASH_TYPE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (TxType.TAX, ("withholdingtax", "tax", "impot", "taxe", "prelevement", "stampduty", "ifft", "iftt")),
    (TxType.DIVIDEND, ("dividend", "dividende")),
    (TxType.BUY, ("purchase", "achat", "buy")),
    (TxType.SELL, ("sell", "sale", "vente")),
    (TxType.CLOSED_TRADE, ("closetrade", "closedtrade")),
    (TxType.FEE, ("fee", "commission", "frais", "swap", "rollover")),
    (TxType.INTEREST, ("interest", "interet")),
    (TxType.DEPOSIT, ("deposit", "depot", "versement")),
    (TxType.WITHDRAWAL, ("withdrawal", "retrait")),
)

#: Libellés de lignes de total/sous-total à écarter : ce ne sont pas des opérations.
_TOTAL_LABELS = {"total", "totaux", "sum", "somme", "profitloss", "profitperte"}


def classify_cash_type(label: Any) -> str:
    normalized = _normalize(label)
    if not normalized:
        return TxType.OTHER
    for tx_type, keywords in _CASH_TYPE_RULES:
        if any(keyword in normalized for keyword in keywords):
            return tx_type
    return TxType.OTHER


def is_total_row(label: Any) -> bool:
    return _normalize(label) in _TOTAL_LABELS


# --- Structures de résultat --------------------------------------------------


@dataclass
class ParsedTable:
    kind: str  # "open_positions" | "closed_positions" | "cash_operations" | "unknown"
    sheet: str
    columns: dict[int, str]
    unmapped_columns: list[str]
    rows: list[dict[str, Any]]


@dataclass
class ParsedExport:
    open_positions: list[dict[str, Any]] = field(default_factory=list)
    closed_positions: list[dict[str, Any]] = field(default_factory=list)
    cash_operations: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    detected_sections: list[str] = field(default_factory=list)
    #: Comptes (colonne « Product ») présents dans les positions ouvertes.
    #: Sert à ne remplacer que l'instantané des comptes réellement réimportés.
    accounts: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.open_positions or self.closed_positions or self.cash_operations)


# --- Détection de la nature d'une table -------------------------------------


def _classify_table(columns: set[str], sheet_name: str) -> str:
    """Détermine la nature d'une table à partir de ses colonnes.

    La signature de colonnes prime sur le nom de la feuille : elle ne dépend pas
    de la langue de l'export.
    """
    sheet = _normalize(sheet_name)

    if "symbol" in columns and ("open_price" in columns or "volume" in columns):
        closed_by_columns = "close_price" in columns or "close_time" in columns
        closed_by_sheet = any(word in sheet for word in ("closed", "ferme", "cloture"))
        return "closed_positions" if (closed_by_columns or closed_by_sheet) else "open_positions"

    if "amount" in columns and "type" in columns:
        return "cash_operations"

    return "unknown"


def _resolve_ambiguous_columns(columns: dict[int, str], raw_headers: dict[int, str]) -> dict[int, str]:
    """Réarbitre les alias ambigus (« ID », « Position ») selon les autres colonnes."""
    values = set(columns.values())
    is_position_table = "open_price" in values or "close_price" in values

    resolved = dict(columns)
    for index in columns:
        if _normalize(raw_headers.get(index)) in _AMBIGUOUS:
            resolved[index] = "position_id" if is_position_table else "cash_id"
    return resolved


# --- Lecture des fichiers ----------------------------------------------------


def _rows_from_xlsx(content: bytes) -> list[tuple[str, list[list[Any]]]]:
    # read_only=False délibérément : les exports XTB déclarent une dimension
    # « A1:A1 » erronée, à laquelle le mode lecture seule fait confiance.
    workbook = load_workbook(io.BytesIO(content), data_only=True)
    sheets = [
        (worksheet.title, [list(row) for row in worksheet.iter_rows(values_only=True)])
        for worksheet in workbook.worksheets
    ]
    workbook.close()
    return sheets


def _rows_from_csv(content: bytes) -> list[tuple[str, list[list[Any]]]]:
    text = content.decode("utf-8-sig", errors="replace")
    sample = text[:4096]
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=";,\t|").delimiter
    except csv.Error:
        delimiter = ";" if sample.count(";") >= sample.count(",") else ","

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    return [("csv", [list(row) for row in reader])]


def _is_blank(row: list[Any]) -> bool:
    return all(cell is None or str(cell).strip() == "" for cell in row)


def _extract_tables(sheet_name: str, rows: list[list[Any]]) -> list[ParsedTable]:
    """Balaye une feuille et en extrait toutes les tables reconnaissables."""
    tables: list[ParsedTable] = []
    index = 0

    while index < len(rows):
        row = rows[index]
        if _is_blank(row):
            index += 1
            continue

        matched_columns = {i: name for i, cell in enumerate(row) if (name := _match_column(cell))}

        # Une ligne d'en-tête doit reconnaître assez de colonnes ET produire une
        # table exploitable. Sinon on la traite comme une ligne de préambule
        # (« Account number | 1234567 ») ou de synthèse, et on continue.
        raw_headers = {i: str(cell) for i, cell in enumerate(row) if cell is not None}
        columns = _resolve_ambiguous_columns(matched_columns, raw_headers)
        kind = _classify_table(set(columns.values()), sheet_name)

        if len(matched_columns) < 4 or kind == "unknown":
            index += 1
            continue

        unmapped = [
            str(cell).strip()
            for i, cell in enumerate(row)
            if cell is not None and str(cell).strip() and i not in matched_columns
        ]

        data_rows: list[dict[str, Any]] = []
        cursor = index + 1
        while cursor < len(rows):
            data_row = rows[cursor]
            if _is_blank(data_row):
                break
            # Un nouvel en-tête interrompt la table courante.
            if sum(1 for cell in data_row if _match_column(cell)) >= 4:
                break

            record: dict[str, Any] = {}
            raw: dict[str, Any] = {}
            for col_index, cell in enumerate(data_row):
                header = raw_headers.get(col_index)
                if header is not None and cell is not None:
                    raw[header] = cell if isinstance(cell, (int, float, str)) else str(cell)
                canonical = columns.get(col_index)
                if canonical:
                    record[canonical] = cell
            record["_raw"] = raw
            data_rows.append(record)
            cursor += 1

        tables.append(
            ParsedTable(
                kind=kind,
                sheet=sheet_name,
                columns=columns,
                unmapped_columns=unmapped,
                rows=data_rows,
            )
        )
        index = cursor

    return tables


# --- Point d'entrée ----------------------------------------------------------


def parse_xtb_export(content: bytes, filename: str) -> ParsedExport:
    """Analyse un export xStation et retourne les enregistrements normalisés."""
    result = ParsedExport()
    suffix = Path(filename).suffix.lower()

    try:
        if suffix in {".xlsx", ".xlsm"}:
            sheets = _rows_from_xlsx(content)
        elif suffix in {".csv", ".txt"}:
            sheets = _rows_from_csv(content)
        else:
            result.warnings.append(
                f"Extension « {suffix or 'inconnue'} » non prise en charge. "
                "Exportez depuis xStation au format Excel (.xlsx) ou CSV."
            )
            return result
    except Exception as exc:  # noqa: BLE001 - on remonte l'erreur à l'utilisateur
        result.warnings.append(f"Fichier illisible : {exc}")
        return result

    tables: list[ParsedTable] = []
    for sheet_name, rows in sheets:
        tables.extend(_extract_tables(sheet_name, rows))

    if not tables:
        result.warnings.append(
            "Aucune table reconnue dans le fichier. Vérifiez qu'il s'agit bien d'un "
            "rapport exporté depuis Account history (Positions ouvertes, Positions "
            "fermées ou Opérations de trésorerie)."
        )
        return result

    for table in tables:
        if table.unmapped_columns:
            result.warnings.append(
                f"Colonnes non reconnues dans « {table.sheet} » : "
                f"{', '.join(table.unmapped_columns)}. "
                "Leurs valeurs sont conservées mais non exploitées."
            )

        if table.kind == "open_positions":
            positions = _build_open_positions(table, result)
            result.open_positions.extend(positions)
            result.detected_sections.append(
                f"{table.sheet} → {len(positions)} position(s) ouverte(s) "
                f"({len(table.rows)} lignes dont lots)"
            )
        elif table.kind == "closed_positions":
            closed = _build_closed_positions(table, result)
            result.closed_positions.extend(closed)
            result.detected_sections.append(f"{table.sheet} → {len(closed)} position(s) fermée(s)")
        elif table.kind == "cash_operations":
            operations = _build_cash_operations(table)
            result.cash_operations.extend(operations)
            result.detected_sections.append(f"{table.sheet} → {len(operations)} opération(s)")

    result.accounts = sorted({p["account"] for p in result.open_positions if p.get("account")})

    if result.is_empty:
        result.warnings.append("Aucune position ni opération exploitable n'a été trouvée.")

    return result


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clean_id(value: Any) -> str | None:
    """Normalise un identifiant numérique.

    openpyxl renvoie les entiers du classeur en flottants : sans cela, l'identifiant
    1677685567 deviendrait la chaîne « 1677685567.0 ».
    """
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    if re.fullmatch(r"\d+\.0", text):
        return text[:-2]
    return text or None


def _synthetic_id(*parts: Any) -> str:
    """Clé de déduplication stable, dérivée du contenu de la ligne.

    Indispensable car l'identifiant du courtier ne suffit pas toujours : sur les
    positions fermées, un même « Position ID » couvre plusieurs lignes quand la
    position a été soldée en plusieurs fois (constaté : 223 lignes pour 220
    identifiants). Utiliser l'identifiant seul comme clé unique fait échouer
    l'insertion ; l'ignorer ferait doublonner à chaque réimport.
    """
    payload = "|".join("" if p is None else str(p) for p in parts)
    return "syn-" + hashlib.sha1(payload.encode("utf-8")).hexdigest()[:20]


def _build_open_positions(table: ParsedTable, result: ParsedExport) -> list[dict[str, Any]]:
    """Reconstruit les positions à partir des lignes agrégées.

    L'export liste, pour chaque titre, une ligne agrégée (catégorie renseignée,
    sens et heure d'ouverture vides) puis une ligne par lot (sens et heure
    renseignés, catégorie vide). Seules les lignes agrégées deviennent des
    positions ; additionner les deux niveaux compterait chaque titre deux fois.
    """
    aggregates: list[dict[str, Any]] = []
    lots_by_key: dict[tuple[str | None, str], list[dict[str, Any]]] = {}

    for row in table.rows:
        symbol = _clean(row.get("symbol"))
        if not symbol:
            continue
        symbol = symbol.upper()
        account = _clean(row.get("account"))

        is_lot = _clean(row.get("type")) is not None
        if is_lot:
            lots_by_key.setdefault((account, symbol), []).append(row)
        else:
            aggregates.append(row)

    # Repli : certains exports ne comportent pas de niveau agrégé. Chaque lot
    # devient alors une position à part entière plutôt que d'être perdu.
    if not aggregates and lots_by_key:
        for (account, symbol), lots in lots_by_key.items():
            for lot in lots:
                aggregates.append(lot)
        lots_by_key = {}

    positions: list[dict[str, Any]] = []

    for row in aggregates:
        symbol = str(_clean(row.get("symbol"))).upper()
        account = _clean(row.get("account"))
        volume = parse_number(row.get("volume"))
        open_price = parse_number(row.get("open_price"))

        if volume is None or open_price is None:
            result.warnings.append(
                f"Position « {symbol} » ignorée : volume ou prix d'ouverture illisible."
            )
            continue

        lots = lots_by_key.get((account, symbol), [])
        lot_times = [parse_datetime(lot.get("open_time")) for lot in lots]
        lot_times = [t for t in lot_times if t is not None]

        # Le cours actuel n'est porté que par les lots. Il est repris tel quel — dans
        # la devise de l'instrument — plutôt que déduit de « valeur / quantité », qui
        # donnerait un prix en devise du compte et fausserait la comparaison avec le
        # prix de revient.
        market_price = parse_number(row.get("market_price"))
        if market_price is None:
            lot_prices = [parse_number(lot.get("market_price")) for lot in lots]
            market_price = next((p for p in lot_prices if p is not None), None)

        # La ligne agrégée ne porte pas de sens : on le déduit des lots.
        directions = {_normalize(lot.get("type")) for lot in lots}
        if directions and directions <= {"sell", "vente", "short"}:
            volume = -abs(volume)

        positions.append(
            {
                "external_id": _clean_id(row.get("position_id"))
                or _synthetic_id(account, symbol, "open"),
                "broker_symbol": symbol,
                "name": _clean(row.get("name")),
                "category": _clean(row.get("category")),
                "account": account,
                "quantity": volume,
                "avg_price": open_price,
                "market_value": parse_number(row.get("market_value")),
                "market_price": market_price,
                "opened_at": min(lot_times) if lot_times else parse_datetime(row.get("open_time")),
                "lots_count": len(lots) or 1,
                "gross_pl": parse_number(row.get("gross_pl")),
                "net_pl": parse_number(row.get("net_pl")),
                "net_pl_pct": parse_number(row.get("net_pl_pct")),
                "purchase_value": parse_number(row.get("purchase_value")),
                "commission": parse_number(row.get("commission")),
                "swap": parse_number(row.get("swap")),
                "currency": _clean(row.get("currency")),
                "comment": _clean(row.get("comment")),
                "raw": row.get("_raw", {}),
            }
        )

    return positions


def _build_closed_positions(table: ParsedTable, result: ParsedExport) -> list[dict[str, Any]]:
    closed: list[dict[str, Any]] = []
    #: Compteur d'occurrences par clé de contenu : deux clôtures partielles
    #: rigoureusement identiques restent alors deux enregistrements distincts.
    seen_keys: dict[str, int] = {}

    for row in table.rows:
        symbol = _clean(row.get("symbol"))
        if not symbol or is_total_row(row.get("name")) or is_total_row(symbol):
            continue
        symbol = symbol.upper()

        volume = parse_number(row.get("volume"))
        open_price = parse_number(row.get("open_price"))
        if volume is None or open_price is None:
            result.warnings.append(
                f"Position fermée « {symbol} » ignorée : volume ou prix d'ouverture illisible."
            )
            continue

        opened_at = parse_datetime(row.get("open_time"))
        closed_at = parse_datetime(row.get("close_time"))
        close_price = parse_number(row.get("close_price"))
        position_id = _clean_id(row.get("position_id"))

        # Le « Position ID » ne suffit pas comme clé : une position soldée en
        # plusieurs fois produit plusieurs lignes portant le même identifiant.
        # La clé combine donc l'identifiant et les détails de l'exécution.
        content_key = _synthetic_id(
            position_id, symbol, opened_at, closed_at, volume, open_price, close_price
        )
        occurrence = seen_keys.get(content_key, 0)
        seen_keys[content_key] = occurrence + 1
        external_id = content_key if occurrence == 0 else f"{content_key}-{occurrence}"

        closed.append(
            {
                "external_id": external_id,
                "position_id": position_id,
                "broker_symbol": symbol,
                "name": _clean(row.get("name")),
                "category": _clean(row.get("category")),
                "account": _clean(row.get("account")),
                "quantity": volume,
                "avg_price": open_price,
                "opened_at": opened_at,
                "closed_at": closed_at,
                "close_price": close_price,
                "purchase_value": parse_number(row.get("purchase_value")),
                "sale_value": parse_number(row.get("sale_value")),
                "open_fx_rate": parse_number(row.get("open_fx_rate")),
                "close_fx_rate": parse_number(row.get("close_fx_rate")),
                "gross_pl": parse_number(row.get("gross_pl")),
                "net_pl": parse_number(row.get("net_pl")),
                "commission": parse_number(row.get("commission")),
                "swap": parse_number(row.get("swap")),
                "currency": _clean(row.get("currency")),
                "comment": _clean(row.get("comment")),
                "raw": row.get("_raw", {}),
            }
        )

    return closed


def _build_cash_operations(table: ParsedTable) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []

    for row in table.rows:
        raw_type = row.get("type")
        # Les lignes « Total » sont des sous-totaux, pas des opérations.
        if is_total_row(raw_type):
            continue

        symbol = _clean(row.get("symbol"))
        executed_at = parse_datetime(row.get("time") or row.get("open_time"))
        amount = parse_number(row.get("amount"))

        operations.append(
            {
                "external_id": _clean_id(row.get("cash_id"))
                or _synthetic_id(raw_type, symbol, executed_at, amount),
                "type": classify_cash_type(raw_type),
                "raw_type": _clean(raw_type),
                "broker_symbol": symbol.upper() if symbol else None,
                "name": _clean(row.get("name")),
                "category": _clean(row.get("category")),
                "account": _clean(row.get("account")),
                "executed_at": executed_at,
                "amount": amount,
                "comment": _clean(row.get("comment")),
                "raw": row.get("_raw", {}),
            }
        )

    return operations
