"""The statistics against reference libraries, and the AR(1) machinery against exact values."""

import numpy as np
import pymannkendall as pmk
import pytest
from scipy import stats as sps

from megavir.engine.stats import (
    _ar1_var_sum,
    analyse_trend,
    ar1_variance_ratio,
    ar1_variance_ratio_exact,
    correct_r1_for_trend,
    mann_kendall,
    ols_trend,
    pairwise_slopes,
    sen_slope,
    size_against_noise,
    years_to_detect,
)

RNG = np.random.default_rng(2026)


@pytest.mark.parametrize("n", [10, 23, 40])
def test_uncorrected_mann_kendall_matches_pymannkendall(n):
    for _ in range(5):
        y = np.round(RNG.normal(size=n) + 0.02 * np.arange(n), 1)  # rounding creates ties
        t = np.arange(n, dtype=float)
        ours = mann_kendall(t, y)
        ref = pmk.original_test(y)
        assert ours.S == pytest.approx(ref.s)
        assert ours.var_s == pytest.approx(ref.var_s)
        assert ours.Z == pytest.approx(ref.z)
        assert ours.p == pytest.approx(ref.p)
        assert ours.tau == pytest.approx(ref.Tau)
        assert sen_slope(t, y, ours.var_s).slope == pytest.approx(ref.slope)


def test_seasonal_mann_kendall_matches_pymannkendall():
    years = 15
    y = RNG.normal(size=12 * years) + np.tile(np.sin(np.arange(12)), years)
    t = np.arange(12 * years) / 12.0
    grp = np.arange(12 * years) % 12
    ours = mann_kendall(t, y, group=grp)
    ref = pmk.seasonal_test(y, period=12)
    assert ours.S == pytest.approx(ref.s)
    assert ours.var_s == pytest.approx(ref.var_s)
    assert ours.p == pytest.approx(ref.p)
    assert float(np.median(pairwise_slopes(t, y, grp))) == pytest.approx(ref.slope)


def test_least_squares_matches_scipy():
    for n in (12, 30):
        t = np.arange(n) + 2000.5
        y = RNG.normal(size=n) + 0.1 * t
        o = ols_trend(t, y)
        ref = sps.linregress(t, y)
        assert o.slope == pytest.approx(ref.slope)
        assert o.intercept == pytest.approx(ref.intercept)
        assert o.se == pytest.approx(ref.stderr)
        assert o.se_adj >= o.se  # never narrower than the textbook interval


def test_ar1_variance_reduces_to_textbook_formula():
    for n in (5, 17, 33):
        assert _ar1_var_sum(n, 0.0, 1) == pytest.approx(n * (n - 1) * (2 * n + 5) / 18)
        assert _ar1_var_sum(n, 0.0, 12) == pytest.approx(12 * n * (n - 1) * (2 * n + 5) / 18)


def test_ar1_variance_matches_simulation():
    n, phi, reps = 25, 0.5, 6000
    e = RNG.standard_normal((reps, n))
    x = np.empty_like(e)
    x[:, 0] = e[:, 0] / np.sqrt(1 - phi**2)
    for k in range(1, n):
        x[:, k] = phi * x[:, k - 1] + e[:, k]
    i, j = np.triu_indices(n, 1)
    S = np.sign(x[:, j] - x[:, i]).sum(1)
    assert S.var() == pytest.approx(_ar1_var_sum(n, phi, 1), rel=0.06)


@pytest.mark.parametrize(
    "n,phi,seasonal",
    [
        (9, 0.33, False),
        (24, 0.57, False),
        (37, 0.81, False),
        (55, 0.44, False),
        (12, 0.62, True),
        (27, 0.35, True),
    ],
)
def test_ratio_table_matches_exact(n, phi, seasonal):
    assert ar1_variance_ratio(n, phi, seasonal) == pytest.approx(
        ar1_variance_ratio_exact(n, phi, seasonal), rel=0.01
    )


def test_ratio_table_extrapolates_long_records():
    # GISTEMP-length records lie beyond the table; extrapolation in 1/n must stay close
    assert ar1_variance_ratio(146, 0.6) == pytest.approx(3.738, rel=0.01)


def test_r1_bias_correction_is_inverse_of_bias():
    r, n = 0.4, 25
    biased = r - (2 + 4 * r) / n
    assert correct_r1_for_trend(biased, n) == pytest.approx(r)


def test_weatherhead_monthly_form_and_annual_scaling():
    # monthly data: the published formula
    n_m = years_to_detect(0.1, 1.0, 0.0, per_year=12)
    assert n_m == pytest.approx((3.3 * 1.0 / 0.1) ** (2 / 3))
    # one value per year with the same per-value noise needs more years
    assert years_to_detect(0.1, 1.0, 0.0, per_year=1) > n_m
    # more autocorrelation, more years
    assert years_to_detect(0.1, 1.0, 0.6, 1) > years_to_detect(0.1, 1.0, 0.0, 1)


def test_size_labels():
    assert size_against_noise(0.0, 20, 1.0)[1] == "small"
    assert size_against_noise(0.04, 20, 1.0)[1] == "moderate"
    assert size_against_noise(0.075, 20, 1.0)[1] == "large"
    assert size_against_noise(0.2, 20, 1.0)[1] == "very large"


def test_clear_trend_is_significant_and_robust():
    n = 30
    t = np.arange(n) + 1995.5
    y = 0.05 * t + RNG.normal(scale=0.1, size=n)
    st = analyse_trend(t, y, np.arange(n) + 1995, [str(k) for k in range(n)])
    assert st.significant and st.agree and st.direction == "rising"
    assert not st.robustness.fragile
    assert st.sen.ci_low < 0.05 < st.sen.ci_high
    assert st.years_more == 0


def test_flat_noise_reports_years_needed():
    n = 20
    t = np.arange(n) + 2004.5
    y = RNG.normal(size=n) + 0.01 * t
    st = analyse_trend(t, y, np.arange(n) + 2004, [str(k) for k in range(n)])
    assert np.isfinite(st.years_needed)
    if not st.significant:
        assert st.years_more >= 0


def test_too_short_record_raises():
    from megavir.engine.stats import NotEnoughData

    with pytest.raises(NotEnoughData):
        analyse_trend(np.arange(5.0), np.arange(5.0), np.arange(5), list("abcde"))
