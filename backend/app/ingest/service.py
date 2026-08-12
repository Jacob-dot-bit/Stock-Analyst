"""Persisting a parsed broker export.

Import semantics:

* **Open positions** are a snapshot, but one export only ever covers a single
  account ("My Trades", "PEA"...). Replacement is therefore limited to the accounts
  present in the file — otherwise importing the PEA statement would wipe the
  brokerage account's holdings. Manually entered positions are always preserved.
* **Transactions** are a cumulative ledger, deduplicated on the broker operation id
  (or a content-derived key when there is none), which makes re-importing the same
  file a no-op.
"""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingest.xtb_import import ParsedExport, parse_xtb_export
from app.messages import Message, MessageCode
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
from app.providers.frankfurt import looks_like_isin
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
    """Find an instrument by broker symbol, or create it by resolving the mapping."""
    broker_symbol = broker_symbol.strip().upper()
    instrument = db.execute(
        select(Instrument).where(Instrument.broker_symbol == broker_symbol)
    ).scalar_one_or_none()

    if instrument is not None:
        # An export enriches a known instrument without overwriting what is set.
        if currency and not instrument.currency:
            instrument.currency = currency
        if name and not instrument.name:
            instrument.name = name
        if category and not instrument.category:
            instrument.category = category
        return instrument

    # The broker category (STOCK / ETF / CFD) is authoritative: more reliable than a
    # symbol heuristic, which would mistake "GOLD.US" (Barrick Gold, an equity) for a
    # commodity.
    resolution = mapping.resolve(
        broker_symbol, overrides if overrides is not None else {}, category=category
    )

    # Some brokers put a raw ISIN in the ticker field (seen on a CVR line). That is
    # not a guess — the symbol *is* the ISIN — and it unlocks the European source.
    isin = broker_symbol if looks_like_isin(broker_symbol) else None

    instrument = Instrument(
        broker_symbol=broker_symbol,
        provider_symbol=resolution.provider_symbol,
        mapping_status=resolution.status,
        isin=isin,
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
    """Insert a transaction unless it already exists. Returns True when inserted.

    ``seen`` guards against duplicates *within* a single import: objects added to the
    session are not yet visible to a SELECT, so two rows sharing a key would both pass
    the database check before failing the unique constraint at flush time.
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
    """Parse then persist an xStation export. Returns the import batch created."""
    parsed: ParsedExport = parse_xtb_export(content, filename)

    batch = ImportBatch(
        filename=filename,
        file_hash=hashlib.sha256(content).hexdigest(),
        warnings=[message.as_dict() for message in parsed.warnings],
        sections=[section.as_dict() for section in parsed.sections],
        accounts=list(parsed.accounts),
        positions_found=len(parsed.open_positions),
        transactions_found=len(parsed.closed_positions) + len(parsed.cash_operations),
    )
    db.add(batch)
    db.flush()

    overrides = _load_overrides(db)
    inserted = 0
    seen: set[tuple[str, str]] = set()

    # --- Open positions: a snapshot, replaced account by account ---
    if parsed.open_positions:
        accounts = set(parsed.accounts)
        stale = db.execute(
            select(Position).where(Position.source == Source.IMPORT)
        ).scalars().all()
        for position in stale:
            # With no account information we fall back to a global replacement:
            # that is the behaviour of single-account exports.
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

    # --- Closed positions: the ledger of completed round trips ---
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

    # --- Cash operations ---
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

    # Unresolved symbols must be visible, not discovered by surprise. CFDs are left
    # out of the count: having no mapping is normal and expected for them, so flagging
    # it as a problem would only be noise.
    unresolved = db.execute(
        select(Instrument).where(
            Instrument.mapping_status == MappingStatus.UNRESOLVED,
            Instrument.category.is_distinct_from("CFD"),
        )
    ).scalars().all()
    if unresolved:
        batch.warnings = list(batch.warnings) + [
            Message(
                MessageCode.UNRESOLVED_SYMBOLS,
                {
                    "count": len(unresolved),
                    # Capped so a badly mapped file cannot produce an unreadable wall
                    # of symbols; the full list stays available on the portfolio page.
                    "symbols": [i.broker_symbol for i in unresolved[:10]],
                },
            ).as_dict()
        ]

    db.commit()
    db.refresh(batch)
    return batch
