"""The demo export must import cleanly, or a first-time user hits an error."""

from __future__ import annotations

import io

from app.ingest.xtb_import import parse_xtb_export
from scripts.make_demo_export import HOLDINGS, build_demo_workbook


def test_demo_export_parses_without_warnings():
    buffer = io.BytesIO()
    build_demo_workbook().save(buffer)

    result = parse_xtb_export(buffer.getvalue(), "demo-xtb-export.xlsx")

    assert result.warnings == []
    assert len(result.open_positions) == len(HOLDINGS)
    assert len(result.open_lots) == sum(len(lots) for _, _, lots, _ in HOLDINGS)
    assert len(result.closed_positions) == 2
    assert len(result.cash_operations) == 5  # the "Total" row is dropped
    assert result.accounts == ["My Trades"]
