"""Persistance d'un export courtier analysé.

Sémantique d'import assumée :

* Les **positions ouvertes** sont un instantané, mais un export ne couvre qu'un
  compte à la fois (« My Trades », « PEA »…). Le remplacement est donc limité aux
  comptes présents dans le fichier — sinon importer le relevé PEA effacerait les
  positions du compte titres. Les positions saisies à la main sont préservées.
* Les **transactions** sont un journal cumulatif, dédupliqué sur l'identifiant
  d'opération du courtier (ou une clé synthétique quand il n'y en a pas), ce qui
  rend un réimport du même fichier sans effet de bord.
"""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingest.xtb_import import ParsedExport, parse_xtb_export
from app.models import (
    ImportBatch,
    Instrument,
    MappingStatus,
    Position,
    Source,
    SymbolOverride,
    Transaction,
    TxType,
)
from app.symbols import mapping


def _load_overrides(db: Session) -> dict[str, str]:
    return {
        row.broker_symbol: row.provider_symbol
        for row in db.execute(select(SymbolOverride)).scalars()
    }


def get_or_create_instrument(
    db: Session,
    broker_symbol: str,
    overrides: dict[str, str] | None = None,
    currency: str | None = None,
    name: str | None = None,
    category: str | None = None,
) -> Instrument:
    """Retrouve un instrument par son symbole courtier, ou le crée en résolvant le mapping."""
    broker_symbol = broker_symbol.strip().upper()
    instrument = db.execute(
        select(Instrument).where(Instrument.broker_symbol == broker_symbol)
    ).scalar_one_or_none()

    if instrument is not None:
        # L'export enrichit un instrument déjà connu sans écraser ce qui existe.
        if currency and not instrument.currency:
            instrument.currency = currency
        if name and not instrument.name:
            instrument.name = name
        if category and not instrument.category:
            instrument.category = category
        return instrument

    # La catégorie du courtier (STOCK / ETF / CFD) fait autorité : elle est plus
    # fiable qu'une heuristique sur le symbole, qui prendrait « GOLD.US »
    # (Barrick Gold, une action) pour une matière première.
    resolution = mapping.resolve(
        broker_symbol, overrides if overrides is not None else {}, category=category
    )

    instrument = Instrument(
        broker_symbol=broker_symbol,
        provider_symbol=resolution.provider_symbol,
        mapping_status=resolution.status,
        name=name,
        category=category.upper() if category else None,
        currency=currency or resolution.currency_hint,
        country=resolution.country_suffix,
    )
    db.add(instrument)
    db.flush()
    return instrument


def _insert_transaction(
    db: Session,
    *,
    external_id: str | None,
    tx_type: str,
    instrument: Instrument | None,
    batch: ImportBatch,
    seen: set[tuple[str, str]],
    **fields: Any,
) -> bool:
    """Insère une transaction si elle n'existe pas déjà. Retourne True si insérée.

    ``seen`` protège des doublons *à l'intérieur* d'un même import : les objets
    ajoutés à la session ne sont pas encore visibles d'un SELECT, si bien que deux
    lignes de clé identique passeraient toutes deux le contrôle en base avant de
    faire échouer la contrainte d'unicité au flush.
    """
    if external_id:
        key = (external_id, tx_type)
        if key in seen:
            return False

        existing = db.execute(
            select(Transaction).where(
                Transaction.external_id == external_id,
                Transaction.type == tx_type,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return False

        seen.add(key)

    db.add(
        Transaction(
            external_id=external_id,
            type=tx_type,
            instrument_id=instrument.id if instrument else None,
            import_batch_id=batch.id,
            **fields,
        )
    )
    return True


def import_export_file(db: Session, content: bytes, filename: str) -> ImportBatch:
    """Analyse puis enregistre un export xStation. Retourne le lot d'import créé."""
    parsed: ParsedExport = parse_xtb_export(content, filename)

    batch = ImportBatch(
        filename=filename,
        file_hash=hashlib.sha256(content).hexdigest(),
        warnings=list(parsed.warnings),
        detected_sections=list(parsed.detected_sections),
        accounts=list(parsed.accounts),
        positions_found=len(parsed.open_positions),
        transactions_found=len(parsed.closed_positions) + len(parsed.cash_operations),
    )
    db.add(batch)
    db.flush()

    overrides = _load_overrides(db)
    inserted = 0
    seen: set[tuple[str, str]] = set()

    # --- Positions ouvertes : instantané, remplacé compte par compte ---
    if parsed.open_positions:
        accounts = set(parsed.accounts)
        stale = db.execute(
            select(Position).where(Position.source == Source.IMPORT)
        ).scalars().all()
        for position in stale:
            # Sans information de compte, on retombe sur un remplacement global :
            # c'est le comportement des exports mono-compte.
            if not accounts or position.account in accounts or position.account is None:
                db.delete(position)
        db.flush()

        for item in parsed.open_positions:
            instrument = get_or_create_instrument(
                db,
                item["broker_symbol"],
                overrides,
                currency=item.get("currency"),
                name=item.get("name"),
                category=item.get("category"),
            )
            db.add(
                Position(
                    instrument_id=instrument.id,
                    external_id=item.get("external_id"),
                    source=Source.IMPORT,
                    account=item.get("account"),
                    quantity=item["quantity"],
                    avg_price=item["avg_price"],
                    currency=item.get("currency") or instrument.currency,
                    opened_at=item.get("opened_at"),
                    lots_count=item.get("lots_count") or 1,
                    broker_gross_pl=item.get("gross_pl"),
                    broker_net_pl=item.get("net_pl"),
                    broker_net_pl_pct=item.get("net_pl_pct"),
                    broker_purchase_value=item.get("purchase_value"),
                    broker_market_value=item.get("market_value"),
                    market_price=item.get("market_price"),
                    commission=item.get("commission"),
                    swap=item.get("swap"),
                    comment=item.get("comment"),
                    import_batch_id=batch.id,
                    raw=item.get("raw"),
                )
            )

    # --- Positions fermées : journal des allers-retours réalisés ---
    for item in parsed.closed_positions:
        instrument = get_or_create_instrument(
            db,
            item["broker_symbol"],
            overrides,
            currency=item.get("currency"),
            name=item.get("name"),
            category=item.get("category"),
        )
        inserted += _insert_transaction(
            db,
            external_id=item.get("external_id"),
            tx_type=TxType.CLOSED_TRADE,
            instrument=instrument,
            batch=batch,
            seen=seen,
            executed_at=item.get("closed_at") or item.get("opened_at"),
            quantity=item.get("quantity"),
            price=item.get("close_price"),
            amount=item.get("net_pl"),
            currency=item.get("currency"),
            commission=item.get("commission"),
            swap=item.get("swap"),
            comment=item.get("comment"),
            raw=item.get("raw"),
        )

    # --- Opérations de caisse ---
    for item in parsed.cash_operations:
        instrument = (
            get_or_create_instrument(
                db,
                item["broker_symbol"],
                overrides,
                name=item.get("name"),
                category=item.get("category"),
            )
            if item.get("broker_symbol")
            else None
        )
        inserted += _insert_transaction(
            db,
            external_id=item.get("external_id"),
            tx_type=item["type"],
            instrument=instrument,
            batch=batch,
            seen=seen,
            executed_at=item.get("executed_at"),
            amount=item.get("amount"),
            comment=item.get("comment") or item.get("raw_type"),
            raw=item.get("raw"),
        )

    batch.transactions_inserted = inserted

    # Les symboles non résolus doivent être visibles, pas découverts par surprise.
    # Les CFD sont exclus du décompte : leur absence de correspondance est normale
    # et attendue, la signaler comme une anomalie serait du bruit.
    unresolved = db.execute(
        select(Instrument).where(
            Instrument.mapping_status == MappingStatus.UNRESOLVED,
            Instrument.category.is_distinct_from("CFD"),
        )
    ).scalars().all()
    if unresolved:
        batch.warnings = list(batch.warnings) + [
            f"{len(unresolved)} symbole(s) sans correspondance fournisseur : "
            f"{', '.join(i.broker_symbol for i in unresolved[:10])}"
            f"{'…' if len(unresolved) > 10 else ''}. "
            "Corrigez-les depuis la page Portefeuille pour activer leur analyse."
        ]

    db.commit()
    db.refresh(batch)
    return batch
