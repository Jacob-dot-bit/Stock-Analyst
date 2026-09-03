"""Phase 2: a walk-forward-validated logistic regression over the
price-only features in `features.py`. See DEVLOG "Decision 3u.23".

Trained live on every call rather than persisted to disk: the dataset is a
few thousand rows at most, fitting a logistic regression on it takes well
under a second, and this app already recomputes its scores live on every
request (`compute_scores` is never cached) rather than maintaining a
separate persisted-model lifecycle — same principle applied here.

**Walk-forward, not random split.** A random train/test split would let
the model see both sides of the same market period, which a real trade
never could. Every row here is split strictly by date: the model is
trained only on rows whose `as_of` falls before the test period's start,
and evaluated only on rows at or after it — the same ordering constraint a
live prediction would actually face.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.corporate_actions.service import load_actions_by_instrument
from app.models import Instrument, PriceBar
from app.prediction.features import FEATURE_NAMES, FeatureRow, build_feature_rows, row_as_vector

#: Fraction of the date-ordered dataset used for training; the remainder,
#: strictly later in time, is the held-out test period.
TRAIN_FRACTION = 0.7

#: Below this many test-period samples, a reported accuracy is closer to
#: noise than to a real estimate — surfaced explicitly rather than shown
#: with the same confidence as a well-powered result.
MIN_RELIABLE_TEST_SAMPLES = 100


@dataclass
class BacktestReport:
    instruments_used: int
    train_samples: int
    test_samples: int
    train_start: date | None
    train_end: date | None
    test_start: date | None
    test_end: date | None
    #: Fraction of test-period predictions that matched the actual
    #: up/down outcome. `None` if there were no test samples at all.
    test_accuracy: float | None
    #: Mean realized forward return of test rows the model predicted
    #: "up" vs "down" — more informative than accuracy alone for whether
    #: the signal has any real magnitude, not just direction.
    avg_return_predicted_up: float | None
    avg_return_predicted_down: float | None
    #: True when `test_samples < MIN_RELIABLE_TEST_SAMPLES` — the caller
    #: must surface this, not just the accuracy number on its own.
    low_sample_warning: bool
    #: True when the training period's labels were all "up" or all "down"
    #: (e.g. a period with no down move at all) — a classifier can't be
    #: fit on one class, so `test_accuracy` is `None` rather than a
    #: trivially perfect or fabricated number.
    single_class_warning: bool = False

    def as_dict(self) -> dict:
        return {
            "instruments_used": self.instruments_used,
            "train_samples": self.train_samples,
            "test_samples": self.test_samples,
            "train_start": self.train_start.isoformat() if self.train_start else None,
            "train_end": self.train_end.isoformat() if self.train_end else None,
            "test_start": self.test_start.isoformat() if self.test_start else None,
            "test_end": self.test_end.isoformat() if self.test_end else None,
            "test_accuracy": self.test_accuracy,
            "avg_return_predicted_up": self.avg_return_predicted_up,
            "avg_return_predicted_down": self.avg_return_predicted_down,
            "low_sample_warning": self.low_sample_warning,
            "single_class_warning": self.single_class_warning,
        }


def build_dataset(db: Session) -> list[FeatureRow]:
    """Every labeled sample across every instrument with cached price
    history. Cache-only — never triggers a fetch."""
    instrument_ids = list(db.execute(select(PriceBar.instrument_id).distinct()).scalars())
    actions_by_instrument = load_actions_by_instrument(db, instrument_ids)
    rows: list[FeatureRow] = []
    for instrument_id in instrument_ids:
        bars = list(
            db.execute(select(PriceBar).where(PriceBar.instrument_id == instrument_id)).scalars()
        )
        rows.extend(build_feature_rows(instrument_id, bars, actions_by_instrument.get(instrument_id)))
    return rows


def _empty_report() -> BacktestReport:
    return BacktestReport(
        instruments_used=0,
        train_samples=0,
        test_samples=0,
        train_start=None,
        train_end=None,
        test_start=None,
        test_end=None,
        test_accuracy=None,
        avg_return_predicted_up=None,
        avg_return_predicted_down=None,
        low_sample_warning=True,
    )


def run_backtest(db: Session) -> BacktestReport:
    """Train on the earlier `TRAIN_FRACTION` of the dataset by date, test
    on the strictly later remainder, and report honest, unrounded metrics —
    including when the sample size is too small to trust."""
    rows = build_dataset(db)
    if len(rows) < 20:
        return _empty_report()

    rows.sort(key=lambda r: r.as_of)
    split_index = int(len(rows) * TRAIN_FRACTION)
    train_rows, test_rows = rows[:split_index], rows[split_index:]

    if not train_rows or not test_rows:
        return _empty_report()

    X_train = [row_as_vector(r) for r in train_rows]
    y_train = [1 if r.forward_return > 0 else 0 for r in train_rows]
    X_test = [row_as_vector(r) for r in test_rows]

    if len(set(y_train)) < 2:
        # Every training-period label is the same direction (e.g. a pure
        # uptrend with no down move at all) — there is nothing for a
        # classifier to discriminate. Report the split's real shape and
        # dates, but no accuracy: a trivial "always predict up" number
        # would look like a real result without being one.
        return BacktestReport(
            instruments_used=len({r.instrument_id for r in rows}),
            train_samples=len(train_rows),
            test_samples=len(test_rows),
            train_start=train_rows[0].as_of,
            train_end=train_rows[-1].as_of,
            test_start=test_rows[0].as_of,
            test_end=test_rows[-1].as_of,
            test_accuracy=None,
            avg_return_predicted_up=None,
            avg_return_predicted_down=None,
            low_sample_warning=len(test_rows) < MIN_RELIABLE_TEST_SAMPLES,
            single_class_warning=True,
        )

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    model = LogisticRegression(max_iter=1000)
    model.fit(X_train_scaled, y_train)
    predictions = model.predict(X_test_scaled)

    correct = sum(
        1 for pred, row in zip(predictions, test_rows) if pred == (1 if row.forward_return > 0 else 0)
    )
    accuracy = correct / len(test_rows)

    up_returns = [row.forward_return for pred, row in zip(predictions, test_rows) if pred == 1]
    down_returns = [row.forward_return for pred, row in zip(predictions, test_rows) if pred == 0]

    return BacktestReport(
        instruments_used=len({r.instrument_id for r in rows}),
        train_samples=len(train_rows),
        test_samples=len(test_rows),
        train_start=train_rows[0].as_of,
        train_end=train_rows[-1].as_of,
        test_start=test_rows[0].as_of,
        test_end=test_rows[-1].as_of,
        test_accuracy=accuracy,
        avg_return_predicted_up=(sum(up_returns) / len(up_returns)) if up_returns else None,
        avg_return_predicted_down=(sum(down_returns) / len(down_returns)) if down_returns else None,
        low_sample_warning=len(test_rows) < MIN_RELIABLE_TEST_SAMPLES,
    )
