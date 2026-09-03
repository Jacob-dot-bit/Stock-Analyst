"""Tests for the Kenneth French Data Library CSV parser. See
`app/providers/kenneth_french.py`'s module docstring for the shared file
shape every one of these CSVs has (DEVLOG "Decision 3u.24")."""

from __future__ import annotations

from datetime import date

from app.providers.kenneth_french import _parse_csv_rows

US_FACTORS_SAMPLE = """This file was created by using the 202606 CRSP database.
The Tbill return is the simple daily rate.

,Mkt-RF,SMB,HML,RF
19260701,    0.09,   -0.25,   -0.27,    0.01
19260702,    0.45,   -0.33,   -0.06,    0.01

Copyright 2026 Eugene F. Fama and Kenneth R. French
"""

US_MOMENTUM_SAMPLE = """This file was created by using the 202606 CRSP database.  It
contains a momentum factor.

,Mom
19260701,   0.12
19260702,  -0.34

Copyright 2026 Eugene F. Fama and Kenneth R. French
"""

EUROPE_FACTORS_SAMPLE_CRLF = (
    "This file was created using the 202607 Bloomberg database.\r\n"
    "\r\n"
    "Missing data are indicated by -99.99.\r\n"
    "\r\n"
    "\r\n"
    "\r\n"
    ",Mkt-RF,SMB,HML,RF\r\n"
    "19900702    ,0.99    ,0.06   ,-0.56    ,0.03\r\n"
    "19900703    ,-99.99    ,-99.99   ,-99.99    ,-99.99\r\n"
    "19900704    ,0.24    ,0.00   ,-0.19    ,0.03\r\n"
    "\r\n"
    "Copyright 2026 Eugene F. Fama and Kenneth R. French\r\n"
)


class TestParseCsvRows:
    def test_parses_the_us_three_factor_shape(self):
        rows = _parse_csv_rows(US_FACTORS_SAMPLE)

        assert rows == {
            date(1926, 7, 1): {"Mkt-RF": 0.09, "SMB": -0.25, "HML": -0.27, "RF": 0.01},
            date(1926, 7, 2): {"Mkt-RF": 0.45, "SMB": -0.33, "HML": -0.06, "RF": 0.01},
        }

    def test_parses_the_single_column_momentum_shape(self):
        rows = _parse_csv_rows(US_MOMENTUM_SAMPLE)

        assert rows == {
            date(1926, 7, 1): {"Mom": 0.12},
            date(1926, 7, 2): {"Mom": -0.34},
        }

    def test_handles_windows_line_endings_and_trailing_whitespace(self):
        rows = _parse_csv_rows(EUROPE_FACTORS_SAMPLE_CRLF)

        assert date(1990, 7, 2) in rows
        assert rows[date(1990, 7, 2)]["Mkt-RF"] == 0.99

    def test_drops_rows_with_the_missing_data_sentinel(self):
        rows = _parse_csv_rows(EUROPE_FACTORS_SAMPLE_CRLF)

        # 1990-07-03 is entirely -99.99 in the fixture — must be dropped,
        # never coerced to 0.
        assert date(1990, 7, 3) not in rows
        assert date(1990, 7, 4) in rows

    def test_empty_input_returns_no_rows(self):
        assert _parse_csv_rows("") == {}
