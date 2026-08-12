"""Fixtures partagées.

Les classeurs de test reproduisent la structure réelle des exports xStation 2026,
vérifiée sur des fichiers de production : une feuille par section, un préambule de
métadonnées, puis la table. Points reproduits fidèlement car ce sont ceux qui
cassent un parser naïf :

* ``Ticker`` porte le symbole, ``Instrument`` la raison sociale ;
* les positions ouvertes sont sur deux niveaux — une ligne agrégée par titre
  (catégorie renseignée, sens vide) suivie d'une ligne par lot (sens renseigné,
  catégorie vide) ;
* le « Position ID » des positions fermées **n'est pas unique** : une position soldée
  en plusieurs fois produit plusieurs lignes portant le même identifiant ;
* les opérations de trésorerie contiennent des lignes « Total » à écarter.

Les numéros de compte sont fictifs : les fixtures ne doivent jamais contenir de
données personnelles réelles, le dépôt ayant vocation à être publié.
"""

from __future__ import annotations

import io
import os

import pytest
from openpyxl import Workbook

os.environ.setdefault("BASE_CURRENCY", "EUR")


def build_xtb_workbook(sheets: list[tuple[str, list[list], list[str], list[list]]]) -> bytes:
    """Construit un classeur (nom de feuille, préambule, en-têtes, lignes)."""
    workbook = Workbook()
    workbook.remove(workbook.active)

    for sheet_name, preamble, headers, rows in sheets:
        sheet = workbook.create_sheet(title=sheet_name)
        for line in preamble:
            sheet.append(line)
        sheet.append(headers)
        for row in rows:
            sheet.append(row)

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def build_workbook(blocks: list[tuple[str, list[str], list[list]]]) -> bytes:
    """Variante « blocs empilés sur une seule feuille », pour les cas limites."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Rapport"

    for section_label, headers, rows in blocks:
        sheet.append([section_label])
        sheet.append(headers)
        for row in rows:
            sheet.append(row)
        sheet.append([])

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


OPEN_HEADERS = [
    "Product", "Instrument/Position", "Ticker", "Category", "Type", "Volume", "Value",
    "Current price", "Open price", "Open time (UTC)", "Stop Loss", "Take Profit",
    "Net Profit %", "Net Profit", "Gross Profit", "Margin", "Open Commission", "Swap",
]

# Les 25 colonnes réelles de la feuille « Closed Positions ».
CLOSED_HEADERS = [
    "Instrument", "Ticker", "Category", "Type", "Volume", "Open Price", "Open Time (UTC)",
    "Close Price", "Close Time (UTC)", "Product", "Profit/Loss", "Gross Profit",
    "Purchase Value", "Sale Value", "Stop Loss", "Take Profit", "Commission", "Margin",
    "Swap", "Rollover", "Open Conversion Rate", "Close Conversion Rate", "Close Origin",
    "Position ID", "Comment",
]


def closed_row(
    name, ticker, volume, open_price, open_time, close_price, close_time, pl, position_id
):
    """Construit une ligne de position fermée au format réel (25 colonnes)."""
    return [
        name, ticker, "STOCK", "BUY", volume, open_price, open_time, close_price, close_time,
        "My Trades", pl, pl, None, None, None, None, 0.0, None, None, None,
        1.0, 1.0, "Android", position_id, None,
    ]

CASH_HEADERS = [
    "Type", "Instrument", "Ticker", "Category", "Time", "Amount", "ID", "Comment",
    "Product", "Position ID",
]


@pytest.fixture
def xtb_export() -> bytes:
    """Export réaliste d'un compte titres, structure identique aux fichiers réels."""
    return build_xtb_workbook(
        [
            (
                "Open Positions",
                [
                    ["Account number", 1234567],
                    ["Open Positions"],
                    ["Data as of report generated", "2026-08-11 23:16:37"],
                    # Petit tableau de synthèse qui précède la vraie table.
                    ["Product", "Metric", "Amount", "Currency"],
                    ["My Trades", "Value", 2870.08, "EUR"],
                    ["My Trades", "Profit", 1448.57, "EUR"],
                    [],
                    ["Note", "Summary values are shown as of the report generation time"],
                ],
                OPEN_HEADERS,
                [
                    # Ligne agrégée : catégorie présente, sens et heure absents.
                    ["My Trades", "ASML", "ASML.NL", "STOCK", None, 1.0, 1558.0, None,
                     723.7, None, None, None, 115.28, 834.3, 834.3, None, None, None],
                    # Lot correspondant : sens et heure présents, catégorie absente.
                    ["My Trades", 1636247573, "ASML.NL", None, "BUY", 1.0, 1558.0, 1558.0,
                     723.7, "2025-01-31 13:33:28", None, None, 115.28, 834.3, 834.3, None, None, None],

                    ["My Trades", "Nvidia", "NVDA.US", "STOCK", None, 2.0, 1312.08, None,
                     106.53, None, None, None, 88.03, 614.27, 614.27, None, None, None],
                    ["My Trades", 1630937303, "NVDA.US", None, "BUY", 1.0, 656.04, 217.46,
                     120.2, "2025-01-28 15:06:48", None, None, 61.94, 306.13, 306.13, None, None, None],
                    ["My Trades", 1744899271, "NVDA.US", None, "BUY", 1.0, 656.04, 217.46,
                     93.75, "2025-04-04 16:31:15", None, None, 118.51, 308.14, 308.14, None, None, None],
                ],
            ),
            (
                "Closed Positions",
                [
                    ["Account number", 1234567],
                    ["Closed Positions"],
                    ["Date from (UTC)", "2006-01-01 00:00:00"],
                ],
                CLOSED_HEADERS,
                [
                    closed_row("Canadian Pacific", "CP.US", 1.0, 77.3, "2025-02-25 18:05:02",
                               90.07, "2026-05-29 16:06:15", 2.83, 1677685560.0),
                    closed_row("Nestle", "NESN.CH", 1.0, 72.18, "2025-09-22 08:10:38",
                               80.035, "2026-05-29 11:38:30", 9.78, 1677685561.0),
                    # Clôture partielle : même « Position ID » que la ligne suivante.
                    # Constaté sur des exports réels (223 lignes pour 220 identifiants).
                    closed_row("Applied Digital", "APLD.US", 1.0, 7.88, "2025-03-31 15:55:55",
                               37.25, "2026-01-16 20:57:06", 24.35, 1677685567.0),
                    closed_row("Applied Digital", "APLD.US", 1.0, 7.88, "2025-03-31 15:55:55",
                               42.33, "2026-05-15 19:51:17", 30.10, 1677685567.0),
                ],
            ),
            (
                "Cash Operations",
                [
                    ["Account number", 1234567],
                    ["Cash Operations"],
                    ["Date from (UTC)", "2006-01-01 00:00:00"],
                ],
                CASH_HEADERS,
                [
                    ["Withholding tax", "ASML", "ASML.NL", "STOCK", "2026-08-05 09:59:25",
                     -0.28, 1386991258, "ASML.NL EUR WHT 15%", "My Trades", 1636247573],
                    ["Dividend", "ASML", "ASML.NL", "STOCK", "2026-08-05 09:59:25",
                     1.88, 1386991257, "ASML.NL EUR 1.8800/ SHR", "My Trades", 1636247573],
                    ["Free funds interest", None, None, None, "2026-08-04 14:52:46",
                     0.01, 1383977734, "Free-funds Interest 2026-07", "My Trades", None],
                    ["Free funds interest tax", None, None, None, "2026-08-04 14:52:46",
                     -0.01, 1383977735, "Tax on interest", "My Trades", None],
                    ["Stock purchase", "Nvidia", "NVDA.US", "STOCK", "2025-01-28 15:06:48",
                     -120.2, 1130937303, "OPEN BUY 1 @ 120.2", "My Trades", 1630937303],
                    ["Deposit", None, None, None, "2024-01-01 00:00:00",
                     5000.0, 1000000001, "Virement initial", "My Trades", None],
                    # Ligne de sous-total : ne doit pas devenir une opération.
                    ["Total", None, None, None, None, 4881.4, None, None, None, None],
                ],
            ),
        ]
    )


@pytest.fixture
def xtb_pea_export() -> bytes:
    """Export du second compte (PEA), pour vérifier l'isolation entre comptes."""
    return build_xtb_workbook(
        [
            (
                "Open Positions",
                [
                    ["Account number", 7654321],
                    ["Open Positions"],
                    ["Product", "Metric", "Amount", "Currency"],
                    ["PEA", "Value", 1000.0, "EUR"],
                ],
                OPEN_HEADERS,
                [
                    ["PEA", "TotalEnergies", "TTE.FR", "STOCK", None, 10.0, 620.0, None,
                     55.0, None, None, None, 12.72, 70.0, 70.0, None, None, None],
                    ["PEA", 1914280470, "TTE.FR", None, "BUY", 10.0, 620.0, 62.0,
                     55.0, "2025-03-10 10:00:00", None, None, 12.72, 70.0, 70.0, None, None, None],
                ],
            ),
            (
                "Cash Operations",
                [["Account number", 7654321], ["Cash Operations"]],
                CASH_HEADERS,
                [
                    ["Dividend", "TotalEnergies", "TTE.FR", "STOCK", "2026-07-03 09:58:01",
                     0.85, 1341782108, "TTE.FR EUR 0.8500/ SHR", "PEA", 1914280470],
                ],
            ),
        ]
    )
