"""Which budget category a bank line belongs to, from its label.

French bank labels are a prefix telling what kind of operation it is
(``PAIEMENT CB``, ``PRLV SEPA``, ``VIR SEPA``, ``RETRAIT DAB``...), then the
counterparty, then references nobody reads (card number, mandate, dates).
`merchant()` keeps the counterparty; `categorize()` matches it against the
rules below, in order, first match wins.

The rules are deliberately plain keywords: when a line lands in ``other``,
the Budget page lists it under "to sort", and the fix is one more keyword
here. The category is never stored, so a new rule applies to every past
line on the next read. See DEVLOG "Step 3u.92".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import DATA_DIR
from app.ingest.bank_import import broker_of

#: What a category counts as. ``investment`` and ``internal`` are money that
#: stays mine (sent to a broker, moved to the savings book): neither spending
#: nor income.
INCOME = "income"
SPENDING = "spending"
INVESTMENT = "investment"
INTERNAL = "internal"

CATEGORY_KIND: dict[str, str] = {
    "salary": INCOME,
    "benefits": INCOME,
    "health_refund": INCOME,
    "interest": INCOME,
    "other_income": INCOME,
    "groceries": SPENDING,
    "restaurants": SPENDING,
    "transport": SPENDING,
    "fuel": SPENDING,
    "housing": SPENDING,
    "utilities": SPENDING,
    "telecom": SPENDING,
    "insurance": SPENDING,
    "subscriptions": SPENDING,
    "shopping": SPENDING,
    "health": SPENDING,
    "leisure": SPENDING,
    "travel": SPENDING,
    "taxes": SPENDING,
    "bank_fees": SPENDING,
    "cash": SPENDING,
    "loan": SPENDING,
    "vehicle": SPENDING,
    "education": SPENDING,
    "transfers_out": SPENDING,
    "other": SPENDING,
    "investment": INVESTMENT,
    "internal": INTERNAL,
}


def _rx(*words: str) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(words) + r")\b")


#: (category, pattern) checked against the upper-cased label, in order.
#: Income-only rules sit in `_CREDIT_RULES` so that a refund from a shop is
#: not mistaken for pay.
_CREDIT_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("interest", _rx(r"INTERETS?", r"REMUNERATION LIVRET")),
    ("benefits", _rx(r"CAF", r"POLE EMPLOI", r"FRANCE TRAVAIL", r"CNAF", r"PRIME D ACTIVITE", r"APL")),
    ("salary", _rx(r"SALAIRE", r"PAIE", r"REMUNERATION", r"PARTICIPATION", r"INTERESSEMENT", r"PRIME")),
    ("health_refund", _rx(r"CPAM", r"AMELI", r"ASSURANCE MALADIE", r"MUTUELLE", r"HARMONIE", r"MGEN", r"ALAN")),
)

_BENEFITS_RE = dict(_CREDIT_RULES)["benefits"]

_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("cash", _rx(r"RETRAIT", r"RETRAIT DAB", r"DAB")),
    ("education", _rx(r"SCOLARITE", r"FRAIS DE SCOLARITE", r"UNIVERSITE", r"ECOLE SUP", r"CVEC", r"LIBRAIRIE UNIVERSITAIRE")),
    ("bank_fees", _rx(r"COTISATION", r"FRAIS", r"COMMISSION", r"AGIOS", r"COMMISSIONS", r"OFFRE GROUPEE")),
    ("taxes", _rx(r"DGFIP", r"IMPOTS?", r"TRESOR PUBLIC", r"FINANCES PUBLIQUES", r"AMENDE", r"ANTAI", r"TAXE")),
    ("loan", _rx(r"ECHEANCE PRET", r"ECH PRET", r"CREDIT IMMOBILIER", r"REMBOURSEMENT PRET", r"COFIDIS", r"CETELEM", r"SOFINCO", r"ONEY")),
    ("housing", _rx(r"LOYER", r"FONCIA", r"NEXITY", r"CITYA", r"SYNDIC", r"COPROPRIETE", r"BAILLEUR", r"HABITAT", r"OPAC", r"OPH")),
    ("utilities", _rx(r"EDF", r"ENGIE", r"TOTALENERGIES ELECTRICITE", r"TOTAL DIRECT ENERGIE", r"EKWATEUR", r"VEOLIA", r"SUEZ", r"EAU", r"GRDF", r"ENEDIS", r"OHM ENERGIE", r"MINT ENERGIE")),
    ("telecom", _rx(r"FREE MOBILE", r"FREE TELECOM", r"FREE", r"ORANGE", r"SFR", r"BOUYGUES TELECOM", r"BOUYGUES TEL", r"SOSH", r"RED BY SFR", r"B AND YOU", r"PRIXTEL", r"SYMA", r"LEBARA")),
    ("insurance", _rx(r"DIRECT ASSURANCE", r"ASSURANCE", r"ASSURANCES", r"MAIF", r"MACIF", r"MATMUT", r"AXA", r"ALLIANZ", r"GMF", r"MMA", r"GROUPAMA", r"LUKO", r"ACHEEL", r"LOVYS", r"GENERALI", r"APRIL")),
    ("subscriptions", _rx(r"NETFLIX", r"SPOTIFY", r"DEEZER", r"DISNEY", r"CANAL", r"PRIME VIDEO", r"AMAZON PRIME", r"AMZN PRIME", r"APPLE COM BILL", r"APPLE\.COM", r"ITUNES", r"GOOGLE", r"YOUTUBE", r"MICROSOFT", r"XBOX", r"PLAYSTATION", r"SONY", r"NINTENDO", r"OPENAI", r"CHATGPT", r"ANTHROPIC", r"CLAUDE\.AI", r"GITHUB", r"PATREON", r"TWITCH", r"DROPBOX", r"ICLOUD", r"PROTON", r"NORDVPN", r"OVH", r"HETZNER", r"SCALEWAY", r"BASIC FIT", r"FITNESS PARK", r"KEEP COOL", r"ON AIR", r"NEONESS")),
    ("groceries", _rx(r"CARREFOUR", r"CRF", r"LECLERC", r"E LECLERC", r"AUCHAN", r"INTERMARCHE", r"ITM", r"SUPER U", r"HYPER U", r"U EXPRESS", r"SYSTEME U", r"MONOPRIX", r"MONOP", r"FRANPRIX", r"CASINO", r"LIDL", r"ALDI", r"NETTO", r"LEADER PRICE", r"PICARD", r"GRAND FRAIS", r"BIOCOOP", r"NATURALIA", r"G20", r"SPAR", r"COCCINELLE", r"PROXI", r"CORA", r"MATCH", r"BOULANGERIE", r"BOUCHERIE", r"PRIMEUR", r"FROMAGERIE", r"SUPERMARCHE", r"EPICERIE", r"MARCHE")),
    ("restaurants", _rx(r"RESTAURANT", r"RESTO", r"BRASSERIE", r"PIZZA", r"PIZZERIA", r"SUSHI", r"KEBAB", r"BURGER", r"MCDONALDS", r"MC DONALDS", r"MCDO", r"BURGER KING", r"KFC", r"QUICK", r"SUBWAY", r"STARBUCKS", r"PAUL", r"BRIOCHE DOREE", r"CAFE", r"BAR", r"BISTROT", r"TRAITEUR", r"UBER EATS", r"UBEREATS", r"DELIVEROO", r"JUST EAT", r"IZLY", r"O TACOS", r"FIVE GUYS")),
    ("vehicle", _rx(r"REPAR", r"REPARATION", r"GARAGE", r"CARROSSERIE", r"NORAUTO", r"FEU VERT", r"SPEEDY", r"MIDAS", r"POINT S", r"EUROMASTER", r"PNEUS?", r"CONTROLE TECHNIQUE", r"DEKRA", r"AUTOSUR", r"SECURITEST", r"AUTO ECOLE", r"AUTO-ECOLE", r"ECF", r"ANTS")),
    ("fuel", _rx(r"TOTALENERGIES", r"TOTAL", r"ESSO", r"SHELL", r"BP", r"AVIA", r"STATION", r"CARBURANT", r"INTERMARCHE CARBU", r"DYNEFF")),
    ("transport", _rx(r"SNCF", r"OUIGO", r"TGV", r"TER", r"RATP", r"NAVIGO", r"TCL", r"TISSEO", r"TAN", r"STAR", r"KEOLIS", r"TRANSDEV", r"UBER", r"BOLT", r"HEETCH", r"G7", r"TAXI", r"BLABLACAR", r"FLIXBUS", r"PEAGE", r"SANEF", r"APRR", r"VINCI AUTOROUTES", r"VINCI", r"ASF", r"COFIROUTE", r"PARKING", r"INDIGO", r"EFFIA", r"LIME", r"DOTT", r"TIER", r"VELIB")),
    ("travel", _rx(r"AIRBNB", r"BOOKING", r"HOTEL", r"HOTELS", r"IBIS", r"ACCOR", r"AIR FRANCE", r"RYANAIR", r"EASYJET", r"TRANSAVIA", r"VUELING", r"WIZZ", r"LOT POLISH", r"LUFTHANSA", r"EXPEDIA", r"TRAINLINE", r"OPODO", r"EDREAMS")),
    ("health", _rx(r"PHARMACIE", r"PHARMA", r"DOCTEUR", r"DR", r"MEDECIN", r"CABINET MEDICAL", r"DENTISTE", r"DENTAIRE", r"OPTICIEN", r"OPTIQUE", r"LABORATOIRE", r"LABO", r"HOPITAL", r"CLINIQUE", r"KINE", r"OSTEO", r"DOCTOLIB")),
    ("leisure", _rx(r"CINEMA", r"UGC", r"PATHE", r"GAUMONT", r"MK2", r"FNAC SPECTACLES", r"TICKETMASTER", r"STEAM", r"STEAMGAMES", r"EPIC GAMES", r"INSTANT GAMING", r"GAMES WORKSHOP", r"WARHAMMER", r"PHILIBERT", r"CULTURA", r"MUSEE", r"CONCERT", r"BOWLING", r"ESCAPE", r"PISCINE", r"DECATHLON", r"GO SPORT", r"INTERSPORT")),
    ("shopping", _rx(r"AMAZON", r"AMZN", r"FNAC", r"DARTY", r"BOULANGER", r"LDLC", r"CDISCOUNT", r"ALIEXPRESS", r"TEMU", r"SHEIN", r"ZALANDO", r"VINTED", r"LEBONCOIN", r"IKEA", r"LEROY MERLIN", r"CASTORAMA", r"BRICO", r"BRICOMARCHE", r"ACTION", r"HEMA", r"PRIMARK", r"H&M", r"H M", r"ZARA", r"KIABI", r"UNIQLO", r"CELIO", r"JULES", r"SEPHORA", r"NOCIBE", r"MARIONNAUD", r"YVES ROCHER", r"GIFI", r"LA POSTE", r"PAYPAL", r"APPLE STORE", r"BACK MARKET", r"RAKUTEN", r"ETSY", r"EBAY")),
)

#: My own keywords: shop names, insurers, places. Kept out of the repository
#: (it is public, and they say where I live and who insures me), in
#: `data/budget_rules.txt`, which `.gitignore` covers. One line per category:
#:
#:     insurance: MY BROKER, MY INSURER
#:     groceries: MY LOCAL SHOP
#:
#: `#` starts a comment; an unknown category is ignored. Checked before the
#: generic rules, re-read whenever the file changes. No re-import needed.
LOCAL_RULES_PATH = DATA_DIR / "budget_rules.txt"
_local_cache: tuple[float, tuple[tuple[str, re.Pattern[str]], ...]] | None = None


def parse_local_rules(text: str) -> tuple[tuple[str, re.Pattern[str]], ...]:
    rules = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        category, words = (part.strip() for part in line.split(":", 1))
        keywords = [re.escape(" ".join(w.upper().split())) for w in words.split(",") if w.strip()]
        if category in CATEGORY_KIND and keywords:
            rules.append((category, re.compile(r"(?:^|\b)(?:" + "|".join(keywords) + r")")))
    return tuple(rules)


def local_rules() -> tuple[tuple[str, re.Pattern[str]], ...]:
    global _local_cache
    try:
        mtime = LOCAL_RULES_PATH.stat().st_mtime
    except OSError:
        return ()
    if _local_cache is None or _local_cache[0] != mtime:
        _local_cache = (mtime, parse_local_rules(LOCAL_RULES_PATH.read_text(encoding="utf-8")))
    return _local_cache[1]


#: A credit that undoes a purchase.
_REFUND_RE = re.compile(
    r"^\s*(?:AVOIR|PAIEMENT\s+(?:CB|PSC)|CARTE|CB|REMBOURSEMENT\s+CB|ANNULATION)\b"
    r"|\b(?:AVOIR|REMBOURSEMENT|REMB|RBT|ANNULATION|ANNUL|RETOUR)\b"
)

#: A VIR / VIREMENT nobody recognised: money sent to someone, or received.
_TRANSFER_RE = re.compile(r"^\s*(?:VIR|VIREMENT)\b")

#: Money moving to or from one of my savings books, whatever the bank calls
#: the movement (VIR, VIREMENT, VERSEMENT, RETRAIT...). Checked at read time
#: too, so a line the import missed (the book itself not in the export, an
#: unusual prefix) is still not spending; the interest it pays is excluded.
_SAVINGS_RE = re.compile(r"\b(?:LIVRET|LDDS?|LEP|CEL|PEL)\b")
_NOT_SAVINGS_MOVE_RE = re.compile(
    r"^\s*(?:PAIEMENT|CARTE|CB|ACHAT|AVOIR|PRLV|PRELEVEMENT)\b|\bINTERETS?\b|\bREMUNERATION\b"
)


def is_savings_move(upper: str) -> bool:
    return bool(_SAVINGS_RE.search(upper)) and not _NOT_SAVINGS_MOVE_RE.search(upper)


#: The operation-kind prefixes, then the noise that follows a counterparty.
_PREFIX_RE = re.compile(
    r"^\s*(?:PAIEMENT\s+(?:CB|PSC|CARTE|PAR\s+CARTE)|PAIEMENT|CARTE|CB|ACHAT\s+CB|PRLV\s+SEPA|PRLV|PRELEVEMENT(?:\s+SEPA)?"
    r"|VIR\s+(?:SEPA\s+)?(?:INST(?:ANTANE)?\s+)?(?:RECU\s+|EMIS\s+)?(?:DE\s+|A\s+|VERS\s+)?|VIREMENT(?:\s+SEPA)?(?:\s+(?:RECU|EMIS))?(?:\s+(?:DE|A|VERS))?"
    r"|RETRAIT\s+DAB|RETRAIT|AVOIR\s+CB|AVOIR|REMBOURSEMENT\s+CB|ECHEANCE)\s*",
)
_CARD_RE = re.compile(r"\bCARTE\s+\S*\d{4}\b.*$|\bCB\s*\*+\d{4}\b")
_DATE_RE = re.compile(r"^\d{4}\s+|\b\d{2}/\d{2}(?:/\d{2,4})?\b")
_REF_RE = re.compile(r"\bREF\b.*$|\bMANDAT\b.*$|\bRUM\b.*$|\bECH\b.*$|\bID EMETTEUR\b.*$")


def _is_reference(token: str) -> bool:
    """``FM-123456-01``, ``0000123456``, ``ECH/020726``: a token carrying
    a run of digits is a mandate, an invoice or a date, never a name."""
    digits = sum(ch.isdigit() for ch in token)
    return digits >= 4 or (digits and len(token) >= 6)


@dataclass(frozen=True)
class Categorized:
    category: str
    kind: str
    merchant: str


def merchant(label: str) -> str:
    """``PAIEMENT CB 0201 PARIS BOULANGERIE CARTE 1234`` → ``PARIS BOULANGERIE``.

    Readable, and without the card number or mandate references: this is
    what the budget view and Hermes see, never the raw label."""
    text = " ".join(label.upper().split())
    text = _PREFIX_RE.sub("", text, count=1)
    text = _DATE_RE.sub(" ", text)
    text = re.sub(r"^\s*MOB\s+", "", text)  # paid with the phone
    text = _CARD_RE.sub("", text)
    text = _REF_RE.sub("", text)
    text = " ".join(token for token in text.split() if not _is_reference(token))
    text = re.sub(r"[*]+", " ", text)
    text = " ".join(text.split()).strip(" -/.")
    return (text or " ".join(label.split()))[:40]


def categorize(
    label: str,
    amount: float,
    *,
    broker: str | None = None,
    own_transfer: bool = False,
) -> Categorized:
    upper = " ".join(label.upper().replace(".", " . ").split()).replace(" . ", ".")
    name = merchant(label)
    if own_transfer or (broker is None and is_savings_move(upper)):
        return Categorized("internal", INTERNAL, name)
    if broker is None:
        # Lines imported before a broker pattern learnt a new form (a
        # truncated "MINTO", "INVES") still count as invested.
        broker = broker_of(label)
    if broker is not None:
        # Profit-sharing Amundi pays straight to the bank is pay, not a
        # withdrawal from the plan (same split as `BrokerTransfer.kind`).
        if amount > 0 and ("PARTICIPATION" in upper or "INTERESSEMENT" in upper):
            return Categorized("salary", INCOME, name)
        return Categorized("investment", INVESTMENT, name)
    for category, pattern in local_rules():
        if pattern.search(upper):
            kind = CATEGORY_KIND[category]
            if kind == SPENDING and amount > 0 and not _REFUND_RE.search(upper):
                return Categorized("other_income", INCOME, name)
            return Categorized(category, kind, name)
    if amount > 0:
        for category, pattern in _CREDIT_RULES:
            if pattern.search(upper):
                return Categorized(category, INCOME, name)
    elif _BENEFITS_RE.search(upper):
        # Paying back benefits received too much: lowers that income.
        return Categorized("benefits", INCOME, name)
    for category, pattern in _RULES:
        if pattern.search(upper):
            # A credit here lowers that category's spending only when it is
            # a refund: a card credit, or a label that says so. Money a
            # payment service passes on (a PayPal transfer from a sale or a
            # friend) is income, not a negative purchase.
            if amount > 0 and not _REFUND_RE.search(upper):
                return Categorized("other_income", INCOME, name)
            return Categorized(category, SPENDING, name)
    if amount > 0:
        return Categorized("other_income", INCOME, name)
    if _TRANSFER_RE.match(upper):
        return Categorized("transfers_out", SPENDING, name)
    return Categorized("other", SPENDING, name)
