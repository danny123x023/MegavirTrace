"""Aggregation, verdict templates and the two-region comparison."""

import numpy as np
import pytest

from megavir.catalog import VARIABLES
from megavir.engine.aggregate import build_series, month_index, month_zscore, region_mean
from megavir.engine.compare import compare_series
from megavir.engine.stats import analyse_trend
from megavir.engine.verdict import compare_verdict, fmt_num, fmt_signed, trend_verdict


def monthly(start=2001, years=24, trend=0.03, noise=0.3, seasonal=5.0, seed=4):
    # a fresh generator per call, so a test's data never depends on which tests ran before it
    idx = np.arange(month_index(start, 1), month_index(start + years - 1, 12) + 1)
    yrs = idx // 12 + (idx % 12) / 12
    vals = (
        seasonal * np.sin(2 * np.pi * (idx % 12) / 12)
        + trend * (yrs - start)
        + np.random.default_rng(seed).normal(scale=noise, size=idx.size)
    )
    return idx, vals


def test_region_mean_weights_and_coverage():
    cube = np.array([[[1.0, 3.0], [np.nan, 5.0]]])
    w = np.array([[1.0, 1.0], [2.0, 0.0]])
    mean, cov = region_mean(cube, w)
    assert mean[0] == pytest.approx(2.0)
    assert cov[0] == pytest.approx(0.5)


def test_changing_coverage_is_not_a_trend():
    """A cold cell with data all along and a warm cell only in the second half: averaging raw values
    makes a step; averaging each cell's anomaly (then adding back the regional normal) does not."""
    months = np.arange(month_index(2001, 1), month_index(2020, 12) + 1)
    cold = np.full(months.size, 10.0)
    warm = np.where(months >= month_index(2011, 1), 20.0, np.nan)
    cube = np.column_stack([cold, warm])
    w = np.array([1.0, 1.0])
    plain, _ = region_mean(cube, w)
    assert plain[0] == pytest.approx(10.0) and plain[-1] == pytest.approx(15.0)
    anom, cov = region_mean(cube, w, months)
    np.testing.assert_allclose(anom, 15.0)  # the regional normal, without a step
    assert cov[0] == pytest.approx(0.5) and cov[-1] == pytest.approx(1.0)
    # with complete coverage both ways agree
    full = np.column_stack([cold, np.full(months.size, 20.0)]) + np.sin(np.arange(months.size))[:, None]
    np.testing.assert_allclose(region_mean(full, w, months)[0], region_mean(full, w)[0], atol=1e-9)


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
    # the chart shows monthly anomalies without the seasonal cycle
    assert abs(s.plot_y.mean()) < 0.01 and s.plot_y.std() < 0.05
    assert len(s.chart_labels) == idx.size and s.chart_labels[0] == "2001-01"


def test_monthly_mode_tests_yearly_means_of_the_anomalies():
    """Months next to each other (and the months of one El Niño year) are not independent, so the
    monthly views are tested on yearly means; the chart still shows the months."""
    idx, vals = monthly(trend=0.05, noise=0.5)
    s = build_series(idx, vals, "monthly")
    assert s.per_year == 1 and s.group is None
    assert s.labels[0] == "2001" and len(s.labels) == 24
    by_year = np.array(s.plot_y).reshape(24, 12).mean(axis=1)
    np.testing.assert_allclose(s.y, by_year, atol=1e-12)
    raw = build_series(idx, vals, "raw")
    np.testing.assert_allclose(raw.y, s.y)  # raw mode only changes what the chart shows
    np.testing.assert_allclose(raw.plot_y, vals)
    # the slope matches the yearly mode's (yearly values differ only by a constant)
    a = build_series(idx, vals, "annual")
    np.testing.assert_allclose(np.diff(s.y), np.diff(a.y), atol=1e-9)


def test_years_use_only_the_calendar_months_observed_here():
    """Ocean colour has no data in polar night: years are built from the months that are observed."""
    idx, vals = monthly(trend=0.0, noise=0.0)
    vals = vals.copy()
    dark = np.isin(idx % 12 + 1, [11, 12, 1, 2])
    vals[dark] = np.nan
    s = build_series(idx, vals, "annual")
    assert s.months_used == tuple(range(3, 11))
    assert len(s.y) == 24  # every year has all 8 observed months
    np.testing.assert_allclose(s.y, np.nanmean(np.where(dark, np.nan, vals)[:12]), atol=1e-9)
    vals2 = vals.copy()
    vals2[np.flatnonzero(~dark)[:2]] = (
        np.nan
    )  # 2001 keeps 6 of its 8 observed months: below ceil(10/12 x 8) = 7
    assert build_series(idx, vals2, "annual").labels[0] == "2002"
    tot = build_series(idx, np.where(dark, np.nan, 10.0), "annual", agg="sum")
    np.testing.assert_allclose(tot.y, 80.0)  # a total over the 8 observed months
    two = np.where(np.isin(idx % 12 + 1, [6, 7]), vals, np.nan)
    assert build_series(idx, two, "annual").y.size == 0  # 2 calendar months cannot make a year


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


def test_related_verdict_wording():
    from megavir.engine.verdict import related_verdict

    rel = {
        "best_lag": 1,
        "best_r": -0.42,
        "p_adjusted": 0.01,
        "n_lags_tested": 25,
        "significant": True,
        "same_direction": False,
    }
    v = related_verdict(rel, "Rainfall", "Topsoil moisture (0–10 cm)", "Testland")
    assert v["headline"] == "Rainfall and topsoil moisture (0–10 cm) in Testland move together."
    assert "below normal about a month later" in v["sentences"][0]
    assert any("not caused by" in c for c in v["caveats"])
    rel.update({"significant": False, "best_lag": -3})
    v = related_verdict(rel, "Rainfall", "Topsoil moisture (0–10 cm)", "Testland")
    assert v["headline"].startswith("No clear relationship between rainfall")
    assert "about 3 months later" in v["sentences"][0]


def test_sen_range_uses_the_tests_t_reference():
    """The interval inverts the Mann–Kendall test, which uses Student t: so must the interval."""
    from megavir.engine.stats import mann_kendall, sen_slope

    rng = np.random.default_rng(12)
    t = np.arange(20) + 0.5
    y = 0.03 * t + rng.normal(0, 0.3, 20)
    mk = mann_kendall(t, y, r1=0.3, df=12.0)
    z = sen_slope(t, y, mk.var_s_adj)
    tt = sen_slope(t, y, mk.var_s_adj, df=12.0)
    assert tt.slope == z.slope and tt.ci_low < z.ci_low and tt.ci_high > z.ci_high


def test_no_clear_trend_never_says_the_range_includes_zero_when_it_does_not():
    import dataclasses

    st, var = _trend(trend=0.0, noise=1.0)
    st = dataclasses.replace(
        st,
        significant=False,
        sen=dataclasses.replace(st.sen, ci_low=0.001, ci_high=0.05),
        mk=dataclasses.replace(st.mk, p=0.08),
        ols=dataclasses.replace(st.ols, p=0.07),
    )
    v = trend_verdict(st, var, "Testland", "°C")
    text = " ".join(v["sentences"])
    assert v["status"] == "not_significant" and "includes no change" not in text and "clear enough" in text


def test_p_values_near_the_line_are_not_rounded_onto_it():
    from megavir.engine.verdict import fmt_p

    assert fmt_p(0.0496) == "= 0.0496" and fmt_p(0.0504) == "= 0.0504"
    assert fmt_p(0.31) == "= 0.31" and fmt_p(0.0004) == "< 0.001"


def test_years_needed_sentence_adds_up():
    st, var = _trend(var="rainfall", trend=0.002, noise=1.0)
    v = trend_verdict(st, var, "Testland", "mm/year")
    sh = v["shown"]
    if "n_star" in sh:
        assert int(sh["n_star"]) - int(sh["span"]) == int(sh["more"]) > 0


def test_spanish_verdicts_use_spanish_unit_words():
    st, var = _trend(var="rainfall", trend=0.0, noise=1.0)
    v = trend_verdict(st, var, "Testlandia", "mm/month", lang="es")
    text = v["headline"] + " ".join(v["sentences"])
    assert "mm/mes" in text and "mm/month" not in text


def test_rates_of_a_percent_quantity_are_in_percentage_points():
    """Sea ice at 60 % falling to 57 % fell 3 points, not 3 %: rates and totals say percentage points."""
    st, var = _trend(var="sea_ice", trend=-0.3, noise=0.5)
    for lang, words in (("en", "percentage points"), ("es", "puntos porcentuales")):
        v = trend_verdict(st, var, "Testland", "%", lang=lang)
        text = v["headline"] + " " + " ".join(v["sentences"])
        assert words in text
        assert "% per decade" not in text and "% por década" not in text
    # the level unit itself is untouched elsewhere
    from megavir.engine.verdict import change_unit, unit_text

    assert unit_text("%", "en") == "%" and change_unit("%", "en", short=True) == "pp"
    assert change_unit("°C", "es") == "°C" and change_unit("mm/month", "es") == "mm/mes"


def test_an_unbounded_range_is_described_not_printed():
    import dataclasses

    st, var = _trend(trend=0.0, noise=1.0)
    st = dataclasses.replace(
        st,
        significant=False,
        sen=dataclasses.replace(st.sen, ci_low=float("-inf"), ci_high=float("inf")),
        mk=dataclasses.replace(st.mk, p=0.4),
        ols=dataclasses.replace(st.ols, p=0.5),
    )
    for lang in ("en", "es"):
        v = trend_verdict(st, var, "Testland", "°C", lang=lang)
        text = " ".join(v["sentences"])
        assert "∞" not in text and "lo" not in v["shown"] and "hi" not in v["shown"]
        assert ("meaningful 95% range" if lang == "en" else "rango del 95 % con sentido") in text
        assert "includes no change" not in text


def test_comparison_names_both_p_values():
    idx, base = monthly(trend=0.0, noise=1.0)
    a = build_series(idx, base + 0.04 * (idx / 12 - 2001), "annual")
    b = build_series(idx, base, "annual")
    c = compare_series(a, b)
    v = compare_verdict(c, VARIABLES["sea_ice"], "A", "B", "%")
    body = v["sentences"][0]
    assert "Mann–Kendall p" in body and "least squares p" in body and "both must pass" in body
    assert "percentage points per decade" in body
    assert {"p", "p_mk", "p_ols"} <= set(v["shown"])
