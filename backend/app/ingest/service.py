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
import re
from datetime import date, datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.ingest.amundi_import import AMUNDI_ACCOUNTS, ParsedAmundiExport, parse_amundi_statement
from app.ingest.amundi_synthese_import import parse_amundi_synthese_export
from app.ingest.mintos_import import (
    MINTOS_CORE_ACCOUNT,
    MINTOS_CORE_BROKER_SYMBOL,
    MINTOS_ETF_ACCOUNT,
    ParsedMintosExport,
    compute_average_cost_positions,
    parse_mintos_statement,
)
from app.ingest.mintos_investments_import import (
    ParsedMintosInvestmentsSnapshot,
    parse_mintos_investments_export,
)
from app.ingest.mintos_transactions_import import (
    ParsedMintosTransactionsExport,
    parse_mintos_transactions_export,
)
from app.ingest.xtb_import import ParsedExport, parse_xtb_export
from app.messages import Message, MessageCode, PerformanceNote
from app.models import (
    AmundiFundSnapshot,
    ImportBatch,
    Instrument,
    Lot,
    LotType,
    MappingStatus,
    Position,
    Source,
    SymbolOverride,
    Transaction,
    TxType,
)
from app.providers.frankfurt import looks_like_isin

#: Name fragments that denote a corporate-action artefact rather than a tradable
#: security. Combined with an ISIN-shaped ticker, they identify instruments that have
#: no market at all — a contingent value right, a rights entitlement, a when-issued
#: placeholder. Each is a right or a bookkeeping entry, not something with a quote.
NON_TRADABLE_NAME_HINTS = ("CVR", "CONTRA", "RIGHTS", "RIGHT ", "WHEN ISSUED", "ENTITLEMENT")


def detect_not_priceable(broker_symbol: str, name: str | None) -> str | None:
    """Why this instrument can never have a price, or None if it can.

    Deliberately narrow: it requires *both* a name that names a corporate-action
    artefact *and* a symbol that is an ISIN rather than a ticker. A real company whose
    name happens to contain one of these words still has a ticker, so it is untouched.
    """
    if not name or not looks_like_isin(broker_symbol):
        return None
    upper = name.upper()
    if any(hint in upper for hint in NON_TRADABLE_NAME_HINTS):
        return "corporate_action"
    return None
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
        if not instrument.not_priceable_reason:
            instrument.not_priceable_reason = detect_not_priceable(broker_symbol, name or instrument.name)
        # An export enriches a known instrument without overwriting what is set.
        # Backfills too: instruments created before ISIN detection existed still have
        # an empty field, and re-importing should repair them rather than leave the
        # user staring at a "needs fixing" row with nothing to fix.
        if not instrument.isin and looks_like_isin(broker_symbol):
            instrument.isin = broker_symbol
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
        not_priceable_reason=detect_not_priceable(broker_symbol, name),
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


def _insert_deduped(
    db: Session,
    model: type,
    *,
    external_id: str | None,
    key_field: str,
    key_value: str,
    seen: set[tuple[str, str, str]],
    **fields: Any,
) -> bool:
    """Insert a row unless one with the same ``(external_id, key_field)`` already
    exists. Returns True when inserted.

    Shared by ``Transaction`` (``key_field="type"``) and ``Lot``
    (``key_field="lot_type"``): both dedupe re-imports the same way, because the
    broker operation id alone is not always unique — a holding closed in several
    parts shares one Position ID across several rows (see `_build_closed_positions`).
    ``seen`` guards against duplicates *within* a single import: objects added to the
    session are not yet visible to a SELECT, so two rows sharing a key would both pass
    the database check before failing the unique constraint at flush time.
    """
    if external_id:
        seen_key = (model.__tablename__, external_id, key_value)
        if seen_key in seen:
            return False

        existing = db.execute(
            select(model).where(
                getattr(model, "external_id") == external_id,
                getattr(model, key_field) == key_value,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return False

        seen.add(seen_key)

    db.add(model(external_id=external_id, **{key_field: key_value}, **fields))
    return True


def _insert_transaction(
    db: Session,
    *,
    external_id: str | None,
    tx_type: str,
    instrument: Instrument | None,
    batch: ImportBatch,
    seen: set[tuple[str, str, str]],
    **fields: Any,
) -> bool:
    return _insert_deduped(
        db,
        Transaction,
        external_id=external_id,
        key_field="type",
        key_value=tx_type,
        seen=seen,
        instrument_id=instrument.id if instrument else None,
        import_batch_id=batch.id,
        **fields,
    )


def _insert_lot(
    db: Session,
    *,
    external_id: str | None,
    lot_type: str,
    instrument: Instrument,
    batch: ImportBatch,
    seen: set[tuple[str, str, str]],
    **fields: Any,
) -> bool:
    return _insert_deduped(
        db,
        Lot,
        external_id=external_id,
        key_field="lot_type",
        key_value=lot_type,
        seen=seen,
        instrument_id=instrument.id,
        source=Source.IMPORT,
        import_batch_id=batch.id,
        **fields,
    )


def import_export_file(
    db: Session, content: bytes, filename: str, *, commit: bool = True
) -> ImportBatch | dict[str, Any]:
    """Parse then persist an xStation export. Returns the import batch created.

    ``commit=False`` runs the identical parse/insert/dedup logic — so the counts
    it produces are exactly what a real import would do, not an estimate — but
    rolls back instead of committing and returns a plain summary dict instead of
    the (now-expired) ORM object. See DEVLOG "Decision 3h.1".
    """
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
    seen: set[tuple[str, str, str]] = set()

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

    # --- Open lots: the ledger feeding the historical value chart ---
    # Deliberately *not* wiped per account the way Position is above: a lot that
    # closes between two imports must stay in history even though its Position
    # row is gone by then. Pure upsert-by-external_id, same posture as Transaction.
    for item in parsed.open_lots:
        instrument = get_or_create_instrument(
            db, item["broker_symbol"], overrides, currency=item.get("currency")
        )
        _insert_lot(
            db,
            external_id=item.get("external_id"),
            lot_type=LotType.OPEN,
            instrument=instrument,
            batch=batch,
            seen=seen,
            account=item.get("account"),
            quantity=item["quantity"],
            open_price=item["open_price"],
            opened_at=item.get("opened_at"),
            currency=item.get("currency") or instrument.currency,
            raw=item.get("raw"),
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
            account=item.get("account"),
            quantity=item.get("quantity"),
            price=item.get("close_price"),
            amount=item.get("net_pl"),
            currency=item.get("currency"),
            commission=item.get("commission"),
            swap=item.get("swap"),
            comment=item.get("comment"),
            raw=item.get("raw"),
        )
        _insert_lot(
            db,
            external_id=item.get("external_id"),
            lot_type=LotType.CLOSED,
            instrument=instrument,
            batch=batch,
            seen=seen,
            account=item.get("account"),
            quantity=item.get("quantity"),
            open_price=item.get("avg_price"),
            opened_at=item.get("opened_at"),
            close_price=item.get("close_price"),
            closed_at=item.get("closed_at"),
            currency=item.get("currency") or instrument.currency,
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
            account=item.get("account"),
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

    if not commit:
        # Same fields a committed ImportBatch would expose — captured now because
        # rollback() expires every ORM instance in the session, batch included.
        summary = {
            "filename": batch.filename,
            "positions_found": batch.positions_found,
            "transactions_found": batch.transactions_found,
            "transactions_inserted": batch.transactions_inserted,
            "warnings": list(batch.warnings),
            "sections": list(batch.sections),
            "accounts": list(batch.accounts),
        }
        db.rollback()
        return summary

    db.commit()
    db.refresh(batch)
    return batch


# --- Mintos ------------------------------------------------------------------


def _recompute_mintos_etf_holdings(db: Session, overrides: dict[str, str], batch: ImportBatch) -> int:
    """Replay the *complete* Core ETF 90 ledger — every BUY/SELL persisted so
    far across every Mintos statement ever imported, not just this file —
    and wholesale-replace `Position`/`Lot` rows for `MINTOS_ETF_ACCOUNT`.

    Mintos never hands us a pre-aggregated position the way XTB does, so
    unlike every other account, `Lot` here is a *derived* artefact of the
    transaction ledger rather than independently broker-sourced data — a
    deliberate, narrow exception to Lot's usual "never bulk-deleted" rule
    (see its class docstring), justified because recomputing from the full
    ledger is strictly more correct than trying to patch existing rows
    (a sell in one import can partially close a lot opened in an earlier
    one). Returns the resulting open-position count.
    """
    rows = db.execute(
        select(Transaction, Instrument)
        .join(Instrument, Transaction.instrument_id == Instrument.id)
        .where(Transaction.account == MINTOS_ETF_ACCOUNT, Transaction.type.in_([TxType.BUY, TxType.SELL]))
        .order_by(Transaction.executed_at)
    ).all()
    transactions = [
        {
            "external_id": tx.external_id,
            "broker_symbol": instrument.broker_symbol,
            "executed_at": tx.executed_at,
            "side": tx.type,
            "units": abs(tx.quantity) if tx.quantity is not None else 0.0,
            "unit_price": tx.price,
            "currency": tx.currency,
            "raw": tx.raw,
        }
        for tx, instrument in rows
    ]
    holdings = compute_average_cost_positions(transactions)

    db.execute(delete(Lot).where(Lot.account == MINTOS_ETF_ACCOUNT))
    db.execute(delete(Position).where(Position.account == MINTOS_ETF_ACCOUNT))
    db.flush()

    for lot in holdings.lots:
        instrument = get_or_create_instrument(db, lot["broker_symbol"], overrides, category="ETF")
        db.add(
            Lot(
                external_id=lot["external_id"],
                instrument_id=instrument.id,
                account=MINTOS_ETF_ACCOUNT,
                source=Source.IMPORT,
                lot_type=LotType.CLOSED if "close_price" in lot else LotType.OPEN,
                quantity=lot["quantity"],
                open_price=lot["open_price"],
                opened_at=lot["opened_at"],
                close_price=lot.get("close_price"),
                closed_at=lot.get("closed_at"),
                currency=lot.get("currency"),
                import_batch_id=batch.id,
                raw=lot.get("raw"),
            )
        )

    for isin, pos in holdings.positions.items():
        instrument = get_or_create_instrument(db, isin, overrides, category="ETF")
        db.add(
            Position(
                instrument_id=instrument.id,
                source=Source.IMPORT,
                account=MINTOS_ETF_ACCOUNT,
                quantity=pos["quantity"],
                avg_price=pos["avg_price"],
                currency=instrument.currency,
                import_batch_id=batch.id,
            )
        )
    return len(holdings.positions)


def _mintos_core_earliest_known_date(db: Session) -> date | None:
    """The account's real starting point, for `opened_at`'s display purpose
    only — deliberately independent of `_recompute_mintos_p2p_position`'s
    own "latest snapshot wins" rule for the *value* shown. Every quarterly
    PDF's aggregate transactions record `period_start` in `raw` (their
    `executed_at` is always the period's *end* — see the "since" fix in
    `import_mintos_transactions_file`); a live Investments snapshot only
    ever has its own single as-of date, used as a last resort when no
    period-based transaction exists yet. Without this, `opened_at` used to
    be set to the *latest* snapshot's date, which reads as "you started
    investing today" right after importing a fresh live export — a real,
    user-caught bug. See DEVLOG "Decision 3u.49"."""
    rows = db.execute(
        select(Transaction.executed_at, Transaction.raw).where(
            Transaction.account == MINTOS_CORE_ACCOUNT,
            Transaction.type.in_(
                [
                    TxType.P2P_INVESTMENT,
                    TxType.P2P_PRINCIPAL_REPAYMENT,
                    TxType.P2P_INTEREST,
                    TxType.P2P_FEE,
                    TxType.P2P_SNAPSHOT,
                ]
            ),
        )
    ).all()
    earliest: date | None = None
    for executed_at, raw in rows:
        period_start = (raw or {}).get("period_start")
        candidate = datetime.fromisoformat(period_start).date() if period_start else None
        if candidate is None and executed_at is not None:
            candidate = executed_at.date()
        if candidate is not None and (earliest is None or candidate < earliest):
            earliest = candidate
    return earliest


def _recompute_mintos_p2p_position(db: Session, instrument: Instrument, batch: ImportBatch) -> None:
    """The P2P aggregate's *value* always reflects the latest statement
    period's closing balance recorded so far, regardless of import order —
    but `opened_at` (shown as "since" in the UI) uses the account's
    earliest known date instead, so a fresh live-value import never makes
    it look like the position was just opened today."""
    latest = db.execute(
        select(Transaction)
        .where(Transaction.account == MINTOS_CORE_ACCOUNT, Transaction.type == TxType.P2P_SNAPSHOT)
        .order_by(Transaction.executed_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if latest is None:
        return

    earliest_date = _mintos_core_earliest_known_date(db) or latest.executed_at.date()

    # This function only ever knows about the declared *value* (from a PDF
    # or Investments snapshot) — the real net-gain figure is a completely
    # separate computation, from `import_mintos_transactions_file`
    # (Decision 3u.47), which updates whatever Position row exists in
    # place. Deleting and recreating that row unconditionally used to wipe
    # a real, already-computed gain the moment *any* value-only import ran
    # afterward — a real, user-caught data-loss bug (the position was left
    # showing "no P&L known" for an account that actually had one on
    # record). Carrying these fields forward from the row being replaced
    # is not a recomputation: the next `import_mintos_transactions_file`
    # run still overwrites them with its own up-to-date total regardless.
    # See DEVLOG "Bug 3u.52".
    existing = db.execute(
        select(Position).where(Position.account == MINTOS_CORE_ACCOUNT)
    ).scalar_one_or_none()
    carried_gross_pl = existing.broker_gross_pl if existing else None
    carried_net_pl = existing.broker_net_pl if existing else None
    carried_net_pl_pct = existing.broker_net_pl_pct if existing else None
    carried_note = existing.performance_note if existing else None

    db.execute(delete(Position).where(Position.account == MINTOS_CORE_ACCOUNT))
    db.flush()
    db.add(
        Position(
            instrument_id=instrument.id,
            source=Source.IMPORT,
            account=MINTOS_CORE_ACCOUNT,
            quantity=1,
            # Not a real per-unit cost — deliberately never used to derive a
            # PRU or gain/loss for this category (see the `category == "P2P"`
            # branch in `routers/portfolio.py::_current_position_figures`).
            # A required NOT NULL placeholder only.
            avg_price=latest.amount,
            broker_market_value=latest.amount,
            broker_gross_pl=carried_gross_pl,
            broker_net_pl=carried_net_pl,
            broker_net_pl_pct=carried_net_pl_pct,
            performance_note=carried_note,
            currency="EUR",
            opened_at=datetime.combine(earliest_date, datetime.min.time()),
            # The date *this* declared balance is as of — the snapshot that
            # just won the "latest wins" pick above, not the account's
            # earliest-known date used for `opened_at`. See DEVLOG
            # "Decision 3u.50".
            value_as_of=latest.executed_at.date(),
            import_batch_id=batch.id,
        )
    )


def import_mintos_file(
    db: Session, content: bytes, filename: str, *, commit: bool = True
) -> ImportBatch | dict[str, Any]:
    """Parse then persist a Mintos "Periodic statement of Financial
    instruments" PDF. Idempotent and import-order-independent: every fill
    and every period's aggregate figures are deduplicated on a
    content-derived key, and Core ETF 90 holdings are always recomputed
    from the complete ledger. See DEVLOG "Decision 3u.39".
    """
    parsed: ParsedMintosExport = parse_mintos_statement(content, filename)

    batch = ImportBatch(
        filename=filename,
        file_hash=hashlib.sha256(content).hexdigest(),
        warnings=[m.as_dict() for m in parsed.warnings],
        sections=[s.as_dict() for s in parsed.sections],
        accounts=[
            a
            for a in (
                MINTOS_ETF_ACCOUNT if parsed.etf_transactions else None,
                MINTOS_CORE_ACCOUNT if parsed.p2p_period else None,
            )
            if a
        ],
        positions_found=0,
        transactions_found=len(parsed.etf_transactions) + (1 if parsed.p2p_period else 0),
    )
    db.add(batch)
    db.flush()

    overrides = _load_overrides(db)
    inserted = 0
    seen: set[tuple[str, str, str]] = set()
    positions_found = 0

    # --- Core ETF 90: append this file's fills to the permanent ledger ---
    for tx in parsed.etf_transactions:
        instrument = get_or_create_instrument(
            db, tx["broker_symbol"], overrides, currency=tx.get("currency"), category="ETF"
        )
        inserted += _insert_transaction(
            db,
            external_id=tx["external_id"],
            tx_type=TxType.BUY if tx["side"] == "BUY" else TxType.SELL,
            instrument=instrument,
            batch=batch,
            seen=seen,
            executed_at=tx["executed_at"],
            account=MINTOS_ETF_ACCOUNT,
            quantity=tx["units"] if tx["side"] == "BUY" else -tx["units"],
            price=tx["unit_price"],
            amount=-tx["total_consideration"] if tx["side"] == "BUY" else tx.get("total_consideration"),
            currency=tx.get("currency"),
            raw=tx.get("raw"),
        )

    if parsed.etf_transactions:
        # autoflush is off (see app/db.py) — the transactions just added above
        # are invisible to the SELECT inside the recompute below without this.
        db.flush()
        positions_found += _recompute_mintos_etf_holdings(db, overrides, batch)

    # --- Mintos Core: aggregate period figures + the single P2P position ---
    if parsed.p2p_period is not None:
        period = parsed.p2p_period
        period_key = period.period_end.strftime("%Y-%m-%d")
        p2p_instrument = get_or_create_instrument(
            db,
            MINTOS_CORE_BROKER_SYMBOL,
            overrides,
            currency="EUR",
            name="Prêts P2P — Mintos Core",
            category="P2P",
        )
        if not p2p_instrument.not_priceable_reason:
            p2p_instrument.not_priceable_reason = "p2p_aggregate"

        period_note = f"Mintos Core, période {period.period_start.date()} — {period.period_end.date()}"
        for tx_type, amount in (
            (TxType.P2P_INVESTMENT, period.investments),
            (TxType.P2P_PRINCIPAL_REPAYMENT, period.repayments),
            (TxType.P2P_INTEREST, period.interest_received),
            (TxType.P2P_FEE, period.fee_charged),
        ):
            if not amount:
                continue
            inserted += _insert_transaction(
                db,
                external_id=f"mintos-p2p-{period_key}-{tx_type}",
                tx_type=tx_type,
                instrument=p2p_instrument,
                batch=batch,
                seen=seen,
                executed_at=period.period_end,
                account=MINTOS_CORE_ACCOUNT,
                amount=amount,
                comment=period_note,
                raw={"period_start": period.period_start.isoformat(), "period_end": period.period_end.isoformat()},
            )
        inserted += _insert_transaction(
            db,
            external_id=f"mintos-p2p-{period_key}-snapshot",
            tx_type=TxType.P2P_SNAPSHOT,
            instrument=p2p_instrument,
            batch=batch,
            seen=seen,
            executed_at=period.period_end,
            account=MINTOS_CORE_ACCOUNT,
            amount=period.closing_balance,
            comment="Valeur déclarée par Mintos en fin de période",
            raw={
                "opening_balance": period.opening_balance,
                "closing_balance": period.closing_balance,
                "period_start": period.period_start.isoformat(),
                "period_end": period.period_end.isoformat(),
            },
        )
        db.flush()  # same autoflush=False reason as above
        _recompute_mintos_p2p_position(db, p2p_instrument, batch)
        positions_found += 1

    batch.positions_found = positions_found
    batch.transactions_inserted = inserted

    if not commit:
        summary = {
            "filename": batch.filename,
            "positions_found": batch.positions_found,
            "transactions_found": batch.transactions_found,
            "transactions_inserted": batch.transactions_inserted,
            "warnings": list(batch.warnings),
            "sections": list(batch.sections),
            "accounts": list(batch.accounts),
        }
        db.rollback()
        return summary

    db.commit()
    db.refresh(batch)
    return batch


def import_mintos_investments_file(
    db: Session, content: bytes, filename: str, *, commit: bool = True
) -> ImportBatch | dict[str, Any]:
    """Parse then persist a Mintos "Investments" .xlsx export — a live
    snapshot of the Mintos Core P2P portfolio's current total value,
    complementing (not replacing) the quarterly PDF statement import. See
    `app/ingest/mintos_investments_import.py`'s module docstring and DEVLOG
    "Decision 3u.43".

    Reuses the exact mechanism the PDF importer uses to update the P2P
    aggregate's displayed value: one `TxType.P2P_SNAPSHOT` transaction dated
    the export's "as of" date, deduplicated by that date so re-importing
    the same file is a no-op. `_recompute_mintos_p2p_position` always shows
    whichever snapshot (from either file type) is dated latest, so
    importing a more recent Investments export supersedes an older
    quarterly PDF's closing balance automatically — no explicit "which
    source wins" logic needed.
    """
    parsed: ParsedMintosInvestmentsSnapshot = parse_mintos_investments_export(content, filename)

    batch = ImportBatch(
        filename=filename,
        file_hash=hashlib.sha256(content).hexdigest(),
        warnings=[m.as_dict() for m in parsed.warnings],
        sections=[],
        accounts=[] if parsed.is_empty else [MINTOS_CORE_ACCOUNT],
        positions_found=0,
        transactions_found=0 if parsed.is_empty else 1,
    )
    db.add(batch)
    db.flush()

    inserted = 0
    if not parsed.is_empty:
        overrides = _load_overrides(db)
        seen: set[tuple[str, str, str]] = set()

        p2p_instrument = get_or_create_instrument(
            db,
            MINTOS_CORE_BROKER_SYMBOL,
            overrides,
            currency="EUR",
            name="Prêts P2P — Mintos Core",
            category="P2P",
        )
        if not p2p_instrument.not_priceable_reason:
            p2p_instrument.not_priceable_reason = "p2p_aggregate"

        as_of_key = parsed.as_of.strftime("%Y-%m-%d")
        inserted += _insert_transaction(
            db,
            external_id=f"mintos-p2p-investments-{as_of_key}-snapshot",
            tx_type=TxType.P2P_SNAPSHOT,
            instrument=p2p_instrument,
            batch=batch,
            seen=seen,
            executed_at=datetime.combine(parsed.as_of, datetime.min.time()),
            account=MINTOS_CORE_ACCOUNT,
            amount=parsed.total_invested,
            comment=f"Valeur totale investie déclarée par Mintos au {parsed.as_of.isoformat()} "
            f"(export « Investments », {parsed.positions_found} prêts fractionnés)",
            raw={"as_of": parsed.as_of.isoformat(), "positions_found": parsed.positions_found, "source": "investments_export"},
        )
        db.flush()  # autoflush is off — the snapshot just added must be visible to the SELECT below
        _recompute_mintos_p2p_position(db, p2p_instrument, batch)
        batch.positions_found = 1

    batch.transactions_inserted = inserted

    if not commit:
        summary = {
            "filename": batch.filename,
            "positions_found": batch.positions_found,
            "transactions_found": batch.transactions_found,
            "transactions_inserted": batch.transactions_inserted,
            "warnings": list(batch.warnings),
            "sections": list(batch.sections),
            "accounts": list(batch.accounts),
        }
        db.rollback()
        return summary

    db.commit()
    db.refresh(batch)
    return batch


def import_mintos_transactions_file(
    db: Session, content: bytes, filename: str, *, commit: bool = True
) -> ImportBatch | dict[str, Any]:
    """Parse then persist a Mintos full "account-statement" .csv export —
    real interest/bonus/fee/tax transactions, used to compute a real net
    gain for the Mintos Core P2P position that doesn't depend on knowing a
    complete deposit history (see
    `app/ingest/mintos_transactions_import.py`'s module docstring and
    DEVLOG "Decision 3u.47").

    Persists this file's own income/cost as ordinary `TxType.P2P_INTEREST`/
    `TxType.P2P_FEE` transactions (deduplicated by this file's own date
    range, so re-importing the same file is a no-op) — the same
    transaction types the quarterly PDF importer already uses, so a later
    import automatically includes an earlier one's contribution when
    computing "everything before this file's coverage starts". Updates the
    existing Mintos Core P2P `Position`'s `broker_net_pl`/
    `broker_net_pl_pct`/`performance_note` in place; does nothing to
    `broker_market_value` (that stays whatever the last snapshot — PDF or
    Investments export — set it to). If no such position exists yet (no
    value has ever been imported), this file's totals are still persisted
    in the `ImportBatch` for visibility, but there is nothing to attach a
    P&L to yet.
    """
    parsed: ParsedMintosTransactionsExport = parse_mintos_transactions_export(content, filename)

    batch = ImportBatch(
        filename=filename,
        file_hash=hashlib.sha256(content).hexdigest(),
        warnings=[m.as_dict() for m in parsed.warnings],
        sections=[],
        accounts=[] if parsed.is_empty else [MINTOS_CORE_ACCOUNT],
        positions_found=0,
        transactions_found=0 if parsed.is_empty else 2,
    )
    db.add(batch)
    db.flush()

    inserted = 0
    if not parsed.is_empty:
        overrides = _load_overrides(db)
        seen: set[tuple[str, str, str]] = set()

        p2p_instrument = get_or_create_instrument(
            db,
            MINTOS_CORE_BROKER_SYMBOL,
            overrides,
            currency="EUR",
            name="Prêts P2P — Mintos Core",
            category="P2P",
        )
        if not p2p_instrument.not_priceable_reason:
            p2p_instrument.not_priceable_reason = "p2p_aggregate"

        period_key = f"{parsed.period_start.isoformat()}-{parsed.period_end.isoformat()}"
        period_end_dt = datetime.combine(parsed.period_end, datetime.min.time())
        period_start_dt = datetime.combine(parsed.period_start, datetime.min.time())

        # Everything already on record for this account from *before* this
        # file's own coverage starts — combined with this file's own
        # income/cost below, this gives a gap-free total regardless of how
        # far back Mintos Core's real history actually goes, as long as
        # each import's own date range doesn't leave a hole before the next.
        pre_period_net = db.execute(
            select(func.sum(Transaction.amount)).where(
                Transaction.account == MINTOS_CORE_ACCOUNT,
                Transaction.type.in_([TxType.P2P_INTEREST, TxType.P2P_FEE]),
                Transaction.executed_at < period_start_dt,
            )
        ).scalar() or 0.0

        inserted += _insert_transaction(
            db,
            external_id=f"mintos-p2p-csv-{period_key}-interest",
            tx_type=TxType.P2P_INTEREST,
            instrument=p2p_instrument,
            batch=batch,
            seen=seen,
            executed_at=period_end_dt,
            account=MINTOS_CORE_ACCOUNT,
            amount=parsed.income_total,
            comment=f"Intérêts/bonus perçus, {parsed.period_start.isoformat()} – {parsed.period_end.isoformat()} "
            f"(export complet des transactions, {parsed.transaction_count} lignes)",
            raw={"period_start": parsed.period_start.isoformat(), "period_end": parsed.period_end.isoformat(), "source": "transactions_export"},
        )
        inserted += _insert_transaction(
            db,
            external_id=f"mintos-p2p-csv-{period_key}-fee",
            tx_type=TxType.P2P_FEE,
            instrument=p2p_instrument,
            batch=batch,
            seen=seen,
            executed_at=period_end_dt,
            account=MINTOS_CORE_ACCOUNT,
            amount=parsed.cost_total,
            comment=f"Frais/taxes, {parsed.period_start.isoformat()} – {parsed.period_end.isoformat()} "
            f"(export complet des transactions)",
            raw={"period_start": parsed.period_start.isoformat(), "period_end": parsed.period_end.isoformat(), "source": "transactions_export"},
        )
        db.flush()

        total_net_gain = round(pre_period_net + parsed.net_gain, 2)

        # Every P2P_INTEREST/P2P_FEE/P2P_SNAPSHOT transaction (periodic PDF
        # or this CSV importer) is dated at its *period's end*, not its
        # start — `min(executed_at)` would therefore report the most
        # recent single-period import's own end date as "the earliest
        # known activity" whenever it's the only one on record, understating
        # real history. Reading each row's own recorded `period_start` from
        # `raw` instead gives the true earliest point.
        period_starts = db.execute(
            select(Transaction.raw).where(
                Transaction.account == MINTOS_CORE_ACCOUNT,
                Transaction.type.in_([TxType.P2P_INTEREST, TxType.P2P_FEE, TxType.P2P_SNAPSHOT]),
            )
        ).scalars()
        # `datetime.fromisoformat`, not `date.fromisoformat`: the periodic
        # PDF importer stores a full datetime ("2024-04-01T00:00:00" — a
        # `date` was never involved there, `ParsedPeriod.period_start` is a
        # `datetime`), while this importer's own rows store a plain date
        # ("2025-01-01") — `date.fromisoformat` rejects the first shape.
        known_starts = [
            datetime.fromisoformat(raw["period_start"]).date()
            for raw in period_starts
            if raw and raw.get("period_start")
        ]
        since_text = min(known_starts).isoformat() if known_starts else parsed.period_start.isoformat()

        position = db.execute(
            select(Position).where(Position.instrument_id == p2p_instrument.id, Position.account == MINTOS_CORE_ACCOUNT)
        ).scalar_one_or_none()
        if position is not None:
            position.broker_gross_pl = total_net_gain
            position.broker_net_pl = total_net_gain
            invested = (position.broker_market_value - total_net_gain) if position.broker_market_value is not None else None
            position.broker_net_pl_pct = round(total_net_gain / invested * 100, 2) if invested else None
            position.performance_note = Message(PerformanceNote.MINTOS_INTEREST_INCOME, {"since": since_text}).as_dict()
            batch.positions_found = 1

    batch.transactions_inserted = inserted

    if not commit:
        summary = {
            "filename": batch.filename,
            "positions_found": batch.positions_found,
            "transactions_found": batch.transactions_found,
            "transactions_inserted": batch.transactions_inserted,
            "warnings": list(batch.warnings),
            "sections": list(batch.sections),
            "accounts": list(batch.accounts),
        }
        db.rollback()
        return summary

    db.commit()
    db.refresh(batch)
    return batch


# --- Amundi ESR ----------------------------------------------------------------

_SLUG_RE = re.compile(r"[^A-Z0-9]+")


def _slugify(text: str) -> str:
    return _SLUG_RE.sub("-", text.upper()).strip("-")


#: Aggregate-contribution keys counted as real money that went *into* the
#: fund (deposits + employer match) — see `amundi_import.py`'s
#: `_classify_aggregate_label`. `abondement_brut` is deliberately excluded
#: (the pre-tax duplicate of `abondement_net`, which already represents
#: what was actually invested); any unclassified "other" label is excluded
#: too, since it isn't confidently known to be a contribution rather than
#: a direct cash payout. See DEVLOG "Decision 3u.47".
_AMUNDI_CONTRIBUTION_KEYS = {"versements_volontaires", "abondement_net", "interessement_participation_percu"}


def _amundi_known_contributions(db: Session, account: str) -> tuple[float, date | None]:
    """(total, earliest_date) across every `versements_volontaires`/
    `abondement_net`/`interessement_participation_percu` aggregate
    transaction recorded for `account` so far — real money contributed,
    not the fund's current value. Only as complete as the annual
    statements actually imported for this account; a year that was never
    imported contributes nothing here, which is exactly why any fallback
    gain computed from this total must say "depuis {earliest_date}", not
    "since this account opened". See DEVLOG "Decision 3u.47"."""
    rows = db.execute(
        select(Transaction.amount, Transaction.executed_at, Transaction.raw).where(
            Transaction.account == account, Transaction.type == TxType.OTHER
        )
    ).all()
    total = 0.0
    earliest: date | None = None
    for amount, executed_at, raw in rows:
        key = (raw or {}).get("key")
        if key not in _AMUNDI_CONTRIBUTION_KEYS or amount is None:
            continue
        total += amount
        when = executed_at.date() if hasattr(executed_at, "date") else executed_at
        if when is not None and (earliest is None or when < earliest):
            earliest = when
    return round(total, 2), earliest


#: Tolerance for "this fund's quantity hasn't changed since its last known
#: snapshot" — a fund whose parts are a fixed number rounded slightly
#: differently between two Amundi export formats (xlsb vs PDF) should
#: still count as unchanged; a real new contribution reliably moves the
#: unit count by far more than floating-point noise.
_AMUNDI_QUANTITY_UNCHANGED_TOLERANCE = 1e-4


def _amundi_real_gain_since_snapshot(
    db: Session, broker_symbol: str, current_quantity: float, current_value: float, before: date
) -> tuple[float, date] | None:
    """(gain, since) using this exact fund's own most recent
    `AmundiFundSnapshot` with a real disclosed gain, dated before
    `before` — but only when `current_quantity` matches that snapshot's
    own quantity (within `_AMUNDI_QUANTITY_UNCHANGED_TOLERANCE`): no new
    contribution to *this specific fund* since then means the snapshot's
    cost basis is still exactly this fund's cost basis today, so
    `current_value - that_cost_basis` is a real, non-approximated gain —
    not a guess. Returns `None` when no matching snapshot exists, or the
    quantity has changed (a new contribution arrived, and there is no
    per-fund data to separate "new money" from "real gain" in that case —
    the caller falls back to the cruder account-level approximation
    instead). See DEVLOG "Decision 3u.48"."""
    snapshot = db.execute(
        select(AmundiFundSnapshot)
        .where(
            AmundiFundSnapshot.broker_symbol == broker_symbol,
            AmundiFundSnapshot.as_of < before,
            AmundiFundSnapshot.estimated_gain_loss.is_not(None),
        )
        .order_by(AmundiFundSnapshot.as_of.desc())
        .limit(1)
    ).scalar_one_or_none()
    if snapshot is None:
        return None
    if abs(snapshot.quantity - current_quantity) > _AMUNDI_QUANTITY_UNCHANGED_TOLERANCE:
        return None
    cost_basis = snapshot.gross_value - snapshot.estimated_gain_loss
    return round(current_value - cost_basis, 2), snapshot.as_of


def import_amundi_file(
    db: Session, content: bytes, filename: str, *, commit: bool = True
) -> ImportBatch | dict[str, Any]:
    """Parse then persist an Amundi ESR "Relevé annuel de situation" /
    "Relevé de comptes" PDF — an annual snapshot, never a transaction
    ledger (see `amundi_import.py`'s module docstring). See
    `_persist_amundi_export` for the shared persistence rules, also used
    by `import_amundi_synthese_file`.
    """
    parsed: ParsedAmundiExport = parse_amundi_statement(content, filename)
    return _persist_amundi_export(db, parsed, content, filename, commit=commit)


def import_amundi_synthese_file(
    db: Session, content: bytes, filename: str, *, commit: bool = True
) -> ImportBatch | dict[str, Any]:
    """Parse then persist an Amundi "Synthese_YYYYMMDD_HHMMSS.xlsb" export —
    a live snapshot of every fund holding, complementing (not replacing)
    the annual PDF statement, the same relationship
    `import_mintos_investments_file` has to the quarterly Mintos PDF. See
    `app/ingest/amundi_synthese_import.py`'s module docstring and DEVLOG
    "Decision 3u.44".
    """
    parsed: ParsedAmundiExport = parse_amundi_synthese_export(content, filename)
    return _persist_amundi_export(db, parsed, content, filename, commit=commit)


def _persist_amundi_export(
    db: Session, parsed: ParsedAmundiExport, content: bytes, filename: str, *, commit: bool
) -> ImportBatch | dict[str, Any]:
    """Shared by both Amundi import paths (annual PDF, live Synthese
    export): Position rows for `Amundi PEG`/`Amundi PERCO` are only
    replaced if this parsed export is the same age or newer than what is
    already recorded, compared via `Position.opened_at` reused as the
    source's "as-of" date. An older export is still fully persisted (its
    fund lines/totals live in this `ImportBatch`, browsable via the import
    history) but never regresses current positions — this makes importing
    files from either source safe in any order. See DEVLOG "Decision
    3u.39" (original) and "Decision 3u.44" (Synthese export added).
    """
    batch = ImportBatch(
        filename=filename,
        file_hash=hashlib.sha256(content).hexdigest(),
        warnings=[m.as_dict() for m in parsed.warnings],
        sections=[s.as_dict() for s in parsed.sections],
        accounts=sorted({f.account for f in parsed.funds}),
        positions_found=len(parsed.funds),
        transactions_found=sum(len(totals) for totals in parsed.aggregate_totals.values()),
    )
    db.add(batch)
    db.flush()

    if parsed.is_fiscal_document or parsed.as_of is None or not parsed.funds:
        return _finish_import(db, batch, commit)

    overrides = _load_overrides(db)
    inserted = 0
    seen: set[tuple[str, str, str]] = set()

    funds_by_account: dict[str, list] = {}
    for fund in parsed.funds:
        funds_by_account.setdefault(fund.account, []).append(fund)

    for account, funds in funds_by_account.items():
        fund_symbols: dict[str, str] = {
            fund.name: f"AMUNDI-{account.split()[-1]}-{_slugify(fund.name)}"[:40] for fund in funds
        }

        # Freshness is judged against this account's own snapshot history,
        # captured *before* this import's rows are written below — not
        # `Position.opened_at`, which this loop now sets to each fund's
        # *earliest* known snapshot date for honest "since" display
        # instead. The two questions ("is this import newer than what we
        # have" vs. "since when have I actually held this") used to share
        # one field, which made a fresh live-snapshot import look like the
        # position was opened today — a real, user-caught bug. See DEVLOG
        # "Decision 3u.49".
        prior_max_as_of = db.execute(
            select(func.max(AmundiFundSnapshot.as_of)).where(
                AmundiFundSnapshot.broker_symbol.in_(fund_symbols.values())
            )
        ).scalar()

        # Every fund's disclosed figures are recorded to
        # `AmundiFundSnapshot` regardless of whether this import ends up
        # winning the freshness check below — a later Synthese import
        # (which discloses no gain of its own) needs this per-fund history
        # to compute a real gain since a fund's own last known snapshot,
        # not just the cruder account-level approximation. See DEVLOG
        # "Decision 3u.48".
        for fund in funds:
            broker_symbol = fund_symbols[fund.name]
            existing_snapshot = db.execute(
                select(AmundiFundSnapshot).where(
                    AmundiFundSnapshot.broker_symbol == broker_symbol, AmundiFundSnapshot.as_of == parsed.as_of
                )
            ).scalar_one_or_none()
            if existing_snapshot is None:
                existing_snapshot = AmundiFundSnapshot(broker_symbol=broker_symbol, as_of=parsed.as_of)
                db.add(existing_snapshot)
            existing_snapshot.quantity = fund.quantity
            existing_snapshot.gross_value = fund.gross_value
            existing_snapshot.estimated_gain_loss = fund.estimated_gain_loss
        db.flush()

        if prior_max_as_of is not None and prior_max_as_of > parsed.as_of:
            # An older statement imported after a newer one for this
            # account — its fund lines/totals (and, now, its per-fund
            # snapshots above) are still persisted, just never used to
            # regress the current positions.
            continue

        existing = db.execute(
            select(Position).where(Position.account == account, Position.source == Source.IMPORT)
        ).scalars().all()
        for position in existing:
            db.delete(position)
        db.flush()

        # Real gain/loss when the source disclosed one (the annual PDF
        # always does — Decision 3u.39); the Synthese export never does
        # (Decision 3u.44), so any fund missing one first tries a real,
        # exact gain since that *same fund's* own last disclosed snapshot
        # (Decision 3u.48) — only valid when the fund's quantity hasn't
        # changed since then, i.e. no new contribution to *this* fund
        # muddies the comparison — and only falls back further to a
        # pro-rata share of the *account's* (current combined value −
        # known contributions) when no such per-fund anchor exists.
        # Computed once per account, not per fund, since contributions are
        # only tracked per-account in the source data. See DEVLOG
        # "Decision 3u.47".
        account_total_value = sum(f.gross_value for f in funds)
        fallback_gain_pct_of_account: float | None = None
        fallback_note: dict | None = None
        if any(f.estimated_gain_loss is None for f in funds) and account_total_value:
            contributions, earliest = _amundi_known_contributions(db, account)
            if contributions:
                fallback_gain_pct_of_account = (account_total_value - contributions) / account_total_value
                since_text = earliest.isoformat() if earliest else parsed.as_of.isoformat()
                fallback_note = Message(
                    PerformanceNote.AMUNDI_APPROXIMATE_GAIN, {"account": account, "since": since_text}
                ).as_dict()

        for fund in funds:
            broker_symbol = fund_symbols[fund.name]
            instrument = get_or_create_instrument(
                db, broker_symbol, overrides, currency="EUR", name=fund.name, category="FUND"
            )
            if not instrument.not_priceable_reason:
                instrument.not_priceable_reason = "employee_savings_fund"

            # "Since" for display is this fund's *earliest* recorded
            # snapshot, not this import's own as-of date — otherwise a
            # fresh live Synthese import (which always wins the freshness
            # check above) would make every fund look opened today. Only
            # as honest as the earliest matching-name snapshot actually on
            # file; a fund whose name drifted between export formats (see
            # DEVLOG "Decision 3u.48"'s fund-name-mismatch finding) still
            # falls back to this import's own date, same as before. See
            # DEVLOG "Decision 3u.49".
            earliest_as_of = (
                db.execute(
                    select(func.min(AmundiFundSnapshot.as_of)).where(
                        AmundiFundSnapshot.broker_symbol == broker_symbol
                    )
                ).scalar()
                or parsed.as_of
            )

            if fund.estimated_gain_loss is not None:
                # Derived from Amundi's own two published figures, not
                # invented — see DEVLOG "Decision 3u.39". Amundi discloses
                # only one P&L figure ("brute"/gross); stored in both
                # broker_gross_pl and broker_net_pl since
                # `_current_position_figures`'s broker-value fallback
                # (routers/portfolio.py) reads specifically the latter.
                gain = fund.estimated_gain_loss
                cost = fund.gross_value - gain
                gain_pct = round(gain / cost * 100, 2) if cost else None
                note = None
            else:
                per_fund = _amundi_real_gain_since_snapshot(
                    db, broker_symbol, fund.quantity, fund.gross_value, before=parsed.as_of
                )
                if per_fund is not None:
                    gain, since = per_fund
                    cost = round(fund.gross_value - gain, 2)
                    gain_pct = round(gain / cost * 100, 2) if cost else None
                    note = Message(PerformanceNote.AMUNDI_REAL_GAIN_SINCE_SNAPSHOT, {"since": since.isoformat()}).as_dict()
                elif fallback_gain_pct_of_account is not None:
                    gain = round(fund.gross_value * fallback_gain_pct_of_account, 2)
                    cost = round(fund.gross_value - gain, 2)
                    gain_pct = round(gain / cost * 100, 2) if cost else None
                    note = fallback_note
                else:
                    gain = None
                    cost = fund.gross_value
                    gain_pct = None
                    note = None

            avg_price = cost / fund.quantity if fund.quantity else (fund.unit_price or 0.0)
            db.add(
                Position(
                    instrument_id=instrument.id,
                    source=Source.IMPORT,
                    account=account,
                    quantity=fund.quantity,
                    avg_price=avg_price,
                    currency="EUR",
                    opened_at=datetime.combine(earliest_as_of, datetime.min.time()),
                    broker_market_value=fund.gross_value,
                    broker_gross_pl=gain,
                    broker_net_pl=gain,
                    broker_net_pl_pct=gain_pct,
                    market_price=fund.unit_price,
                    performance_note=note,
                    # The date *this* fund's declared value is as of — this
                    # import's own `as_of` (the one that just won the
                    # freshness check above), not `earliest_as_of` used for
                    # "since held". See DEVLOG "Decision 3u.50".
                    value_as_of=parsed.as_of,
                    import_batch_id=batch.id,
                )
            )

    period_end = date(parsed.as_of.year, 12, 31)
    for account, totals in parsed.aggregate_totals.items():
        for key, amount in totals.items():
            inserted += _insert_transaction(
                db,
                external_id=f"amundi-{_slugify(account)}-{parsed.as_of.year}-{_slugify(key)}",
                tx_type=TxType.OTHER,
                instrument=None,
                batch=batch,
                seen=seen,
                executed_at=datetime.combine(period_end, datetime.min.time()),
                account=account,
                amount=amount,
                comment=f"{key} — {account} {parsed.as_of.year} (relevé annuel, cumul non daté)",
                raw={"as_of": parsed.as_of.isoformat(), "key": key},
            )
    batch.transactions_inserted = inserted

    return _finish_import(db, batch, commit)


def _finish_import(db: Session, batch: ImportBatch, commit: bool) -> ImportBatch | dict[str, Any]:
    if not commit:
        summary = {
            "filename": batch.filename,
            "positions_found": batch.positions_found,
            "transactions_found": batch.transactions_found,
            "transactions_inserted": batch.transactions_inserted,
            "warnings": list(batch.warnings),
            "sections": list(batch.sections),
            "accounts": list(batch.accounts),
        }
        db.rollback()
        return summary

    db.commit()
    db.refresh(batch)
    return batch
