"""The app's own figures for a year set against that year's income tax
notice (DEVLOG "Step 3u.112"): what the notice is missing, or where it
differs. Every check states a gap and both figures; none says what to
declare.

What is compared.
- Gains on sales (CTO shares and CFDs): the notice's "Plus-values de
  cession de valeurs mobilières" against the app's net for the year. A
  net loss must show on the notice as a loss carried forward ("Moins-value
  provenant de l'année …"); otherwise it was not declared and is lost.
  When earlier losses were available and the notice keeps the gain whole,
  they were not set off.
- Investment income: the notice's "Revenus de capitaux mobiliers déclarés"
  against dividends (gross) and interest of ordinary accounts plus P2P
  interest. Income inside PEA and employee savings is left out: it is not
  declared while it stays there.

Small differences are expected (rounding to the euro, a broker's own
figure, a few cents of fees), so a gap counts from 20 € and 5 % up.
"""

from __future__ import annotations

import unicodedata

from app.messages import Message, TaxPrepNote
from app.tax.gains import CapitalGainsYear

_MIN_GAP = 20.0
_MIN_SHARE = 0.05


def _differs(a: float, b: float) -> bool:
    gap = abs(a - b)
    return gap >= _MIN_GAP and gap >= _MIN_SHARE * max(abs(a), abs(b))


def _fold(text: str) -> str:
    plain = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return " ".join(plain.lower().split())


def notice_checks(
    year: int,
    figures: dict,
    lines: list[dict],
    capital_gains: CapitalGainsYear | None,
    investment_income: float,
) -> list[Message]:
    out: list[Message] = []

    notice_gains = figures.get("capital_gains")
    carried = any(
        "moins-value" in _fold(line.get("label", "")) and str(year) in line.get("label", "")
        for line in lines
    )
    if capital_gains is not None:
        net = capital_gains.net
        if net < -_MIN_GAP and not carried:
            out.append(Message(TaxPrepNote.CHECK_LOSS_NOT_ON_NOTICE, {"loss": round(-net, 2)}))
        elif net > _MIN_GAP:
            if notice_gains is None:
                out.append(Message(TaxPrepNote.CHECK_GAINS_NOT_ON_NOTICE, {"app": round(net, 2)}))
            elif capital_gains.losses_used > _MIN_GAP and not _differs(notice_gains, net) and _differs(
                notice_gains, capital_gains.taxable_net
            ):
                out.append(
                    Message(
                        TaxPrepNote.CHECK_LOSSES_NOT_USED,
                        {
                            "available": round(capital_gains.losses_used, 2),
                            "notice": notice_gains,
                            "app": round(capital_gains.taxable_net, 2),
                        },
                    )
                )
            elif _differs(notice_gains, capital_gains.taxable_net) and _differs(notice_gains, net):
                out.append(Message(TaxPrepNote.CHECK_GAINS_DIFFER, {"app": round(net, 2), "notice": notice_gains}))

    notice_income = figures.get("investment_income")
    if investment_income > _MIN_GAP:
        if notice_income is None:
            out.append(Message(TaxPrepNote.CHECK_INCOME_NOT_ON_NOTICE, {"app": round(investment_income, 2)}))
        elif _differs(notice_income, investment_income):
            out.append(
                Message(TaxPrepNote.CHECK_INCOME_DIFFERS, {"app": round(investment_income, 2), "notice": notice_income})
            )

    return out or [Message(TaxPrepNote.CHECK_AGREES, {})]
