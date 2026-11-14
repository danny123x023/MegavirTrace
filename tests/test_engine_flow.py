"""Aggregation, verdict templates and the two-region comparison."""

import numpy as np
import pytest

from megavir.catalog import VARIABLES
from megavir.engine.aggregate import build_series, month_index, month_zscore, region_mean
from megavir.engine.compare import compare_series
from megavir.engine.stats import analyse_trend
from megavir.engine.verdict import compare_verdict, fmt_num, fmt_signed, trend_verdict

RNG = np.random.default_rng(4)


def monthly(start=2001, years=24, trend=0.03, noise=0.3, seasonal=5.0):
    idx = np.arange(month_index(start, 1), month_index(start + years - 1, 12) + 1)
    yrs = idx // 12 + (idx % 12) / 12
    vals = (
        seasonal * np.sin(2 * np.pi * (idx % 12) / 12)
        + trend * (yrs - start)
        + RNG.normal(scale=noise, size=idx.size)
    )
    return idx, vals


def test_region_mean_weights_and_coverage():
    cube = np.array([[[1.0, 3.0], [np.nan, 5.0]]])
    w = np.array([[1.0, 1.0], [2.0, 0.0]])
    mean, cov = region_mean(cube, w)
    assert mean[0] == pytest.approx(2.0)
    assert cov[0] == pytest.approx(0.5)


def test_annual_needs_ten_months_and_is_unbiased_by_gaps():
    idx, vals = monthly(trend=0.0, noise=0.0)
    vals = vals.copy()
    vals[:3] = np.nan  # first year has 9 months -> dropped
    vals[14] = np.nan  # second year has 11 months -> kept
    s = build_series(idx, vals, "annual")
    assert s.labels[0] == "2002"
    # with no noise and no trend, every year equals the climatological mean despite the gap
    np.testing.assert_allclose(s.y, s.y[0], atol=1e-9)


def test_djf_belongs_to_january_year():
    idx, vals = monthly()
    s = build_series(idx, vals, "season", season="DJF")
    assert s.labels[0] == "2002 DJF"  # Dec 2001 + Jan/Feb 2002; Jan 2001 has no December before it


def test_monthly_anomalies_remove_seasonal_cycle():
    idx, vals = monthly(trend=0.0, noise=0.01)
    s = build_series(idx, vals, "monthly")
    assert abs(s.y.mean()) < 0.01 and s.y.std() < 0.05
    assert s.group is not None and s.per_year == 12


def test_sum_aggregation_gives_yearly_totals():
    idx = np.arange(month_index(2001, 1), month_index(2010, 12) + 1)
    vals = np.full(idx.size, 10.0)
    s = build_series(idx, vals, "annual", agg="sum")
    np.testing.assert_allclose(s.y, 120.0)


def test_month_zscore():
    idx, vals = monthly(trend=0.0)
    vals = vals.copy()
    k = int(np.flatnonzero(idx == month_index(2010, 7))[0])
    vals[k] += 5
    z = month_zscore(idx, vals, 2010, 7)
    assert z["rank_from_highest"] == 1 and z["z"] > 3


def test_number_format():
    assert fmt_num(0.31234) == "0.31"
    assert fmt_num(12.6) == "13"
    assert fmt_signed(-0.0042) == "−0.0042"
    assert fmt_signed(1.5) == "+1.5"
    assert fmt_num(1234.5, lang="es") == "1\u202f234"  # whole digits are never dropped


def _trend(var="air_temp", trend=0.04, noise=0.1):
    idx, vals = monthly(trend=trend, noise=noise)
    s = build_series(idx, vals, "annual")
    st = analyse_trend(s.t, s.y, s.years, s.labels)
    return st, VARIABLES[var]


def test_significant_verdict_text():
    st, var = _trend()
    v = trend_verdict(st, var, "Testland", "°C")
    assert v["status"] == "significant"
    assert v["headline"].startswith("Air temperature (2 m) in Testland has been rising since 2001")
    assert "Testland is warming" in " ".join(v["sentences"])
    assert any("not a cause" in c for c in v["caveats"])
    assert v["shown"]["rate"] in v["headline"]


def test_not_significant_verdict_mentions_years_needed():
    st, var = _trend(var="rainfall", trend=0.0, noise=1.0)
    v = trend_verdict(st, var, "Testland", "mm/year")
    if v["status"] == "not_significant":
        text = " ".join(v["sentences"])
        assert "years of data" in text or "probably smaller" in text


def test_verdicts_are_deterministic_and_marked_for_test_data():
    st, var = _trend()
    a = trend_verdict(st, var, "X", "°C", data_kind="test")
    b = trend_verdict(st, var, "X", "°C", data_kind="test")
    assert a == b
    assert a["caveats"][0].startswith("TEST DATA")


def test_spanish_templates_render():
    st, var = _trend()
    v = trend_verdict(st, var, "Testlandia", "°C", lang="es")
    assert "por década" in v["headline"]


def test_compare_shared_noise_cancels():
    idx, base = monthly(trend=0.0, noise=1.0)
    a = build_series(idx, base + 0.04 * (idx / 12 - 2001), "annual")
    b = build_series(idx, base, "annual")
    c = compare_series(a, b)
    diff = np.array(c["diff"])
    resid = diff - np.polyval(np.polyfit(c["t"], diff, 1), c["t"])
    assert resid.std() < 0.05 * np.std(c["b"])  # the shared ups and downs cancel in A - B
    assert c["difference"]["significant"]  # identical noise cancels, the 0.04/yr gap stands out
    assert c["difference"]["slope_per_decade"] == pytest.approx(0.4, rel=0.05)
    v = compare_verdict(c, VARIABLES["air_temp"], "A", "B", "°C")
    assert v["status"] == "significant" and "A minus B" in v["sentences"][0]


def test_speeding_up_verdict():
    rng = np.random.default_rng(3)
    t = np.arange(40) + 1985.5
    y = 0.002 * (t - 1985) ** 2 + rng.normal(0, 0.1, 40)
    st = analyse_trend(t, y, np.floor(t).astype(int), [str(int(x)) for x in t])
    assert st.acceleration["significant"] and st.acceleration["kind"] == "speeding_up"
    v = trend_verdict(st, VARIABLES["air_temp"], "Testland", "°C")
    text = " ".join(v["sentences"])
    assert "speeding up" in text and "Exploratory clue" not in text
    assert v["shown"]["pace_late"] in text


def test_short_records_are_not_tested_for_pace():
    t = np.arange(12) + 2010.5
    st = analyse_trend(t, 0.1 * t + np.sin(t), np.floor(t).astype(int), [str(int(x)) for x in t])
    assert st.acceleration["tested"] is False
