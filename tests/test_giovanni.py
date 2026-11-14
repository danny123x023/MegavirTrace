"""Giovanni time-series CSV parsing (layout copied from real responses)."""

import pytest

from megavir.ingest.giovanni import _parse_csv

MONTHLY = """prod_name,GPM_3IMERGM.07
unit,mm/hr
undef,-9999.9
lat,30.05
mean,1.3125e-01

Timestamp (UTC),Data
2019-11-01 00:00,0.079
2019-12-01 00:00,-9999.9
2020-01-01 00:00,0.264
"""

HOURLY = """prod_name,M2T1NXSLV.5.12.4
unit,K
undef,1e+15

Timestamp (UTC),Data
2020-01-31 22:30,280.0
2020-01-31 23:30,282.0
2020-02-01 00:30,290.0
2020-02-01 01:30,1e+15
"""


def test_monthly_rows_pass_through_and_undef_is_dropped():
    out = _parse_csv(MONTHLY)
    assert out == {2019 * 12 + 10: pytest.approx(0.079), 2020 * 12: pytest.approx(0.264)}


def test_hourly_rows_are_averaged_per_month():
    out = _parse_csv(HOURLY)
    assert out[2020 * 12] == pytest.approx(281.0)
    assert out[2020 * 12 + 1] == pytest.approx(290.0)  # the undef hour is ignored
