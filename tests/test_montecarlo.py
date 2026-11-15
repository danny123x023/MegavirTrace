"""Monte Carlo checks of the honesty commitment (run in CI).

* false alarms of the agreement rule on trend-free AR(1) series:
  at most 5 % at lag-1 autocorrelation 0.3, at most 7 % at 0.5 and at most 6 % at 0.7;
* the monthly views (tested on yearly means) stay near 5 % with year-to-year memory;
* a synthetic trend is recovered inside its 95 % interval;
* the two-region difference test keeps false alarms near 5 % whatever the correlation;
* the vectorised cell engine gives the same slope and p as the per-series engine.

2,000 runs per setting.  The binomial standard error at 5 % is 0.5 %, so the thresholds are
the design targets themselves, not loosened ones.
"""

import numpy as np
import pytest

from megavir.engine.cellmap import benjamini_hochberg, cell_trends
from megavir.engine.stats import trend_test

pytestmark = pytest.mark.montecarlo
RUNS = 2000


def ar1(rng, n, phi, reps):
    e = rng.standard_normal((reps, n))
    x = np.empty_like(e)
    x[:, 0] = e[:, 0] / np.sqrt(1 - phi**2)
    for k in range(1, n):
        x[:, k] = phi * x[:, k - 1] + e[:, k]
    return x


@pytest.mark.parametrize("n", [20, 30])
@pytest.mark.parametrize("phi,limit", [(0.3, 0.05), (0.5, 0.07), (0.7, 0.06)])
def test_false_alarm_rate_yearly(n, phi, limit):
    rng = np.random.default_rng(1000 + n + int(phi * 10))
    t = np.arange(n) + 0.5
    X = ar1(rng, n, phi, RUNS)
    rate = np.mean([trend_test(t, x)[4] for x in X])
    assert rate <= limit, f"false alarms {rate:.3f} > {limit}"


@pytest.mark.parametrize("year_phi", [0.0, 0.5])
def test_false_alarm_rate_monthly_mode_with_year_to_year_memory(year_phi):
    """Monthly views: month-to-month memory plus a slow year-to-year swing (as El Niño gives).
    A one-month AR(1) correction gave 18–31 % false alarms here; the yearly-means test stays near 5 %."""
    from megavir.engine.aggregate import build_series, month_index

    rng = np.random.default_rng(78 + int(year_phi * 10))
    years = 25
    idx = np.arange(month_index(2000, 1), month_index(2000 + years - 1, 12) + 1)
    monthly_noise = ar1(rng, idx.size, 0.5, 1000)
    yearly = np.repeat(ar1(rng, years, year_phi, 1000) * 0.6, 12, axis=1)
    season = 3 * np.sin(2 * np.pi * (idx % 12) / 12)
    hits = []
    for x in monthly_noise + yearly + season:
        s = build_series(idx, x, "monthly")
        hits.append(trend_test(s.t, s.y)[4])
    rate = np.mean(hits)
    assert rate <= 0.07, f"false alarms {rate:.3f}"


@pytest.mark.parametrize("phi", [0.0, 0.3])
def test_synthetic_trend_inside_interval(phi):
    rng = np.random.default_rng(5)
    n, true = 25, 0.05
    t = np.arange(n) + 0.5
    X = ar1(rng, n, phi, 800) + true * t
    res = [trend_test(t, x) for x in X]
    cov_sen = np.mean([r[2].ci_low <= true <= r[2].ci_high for r in res])
    cov_ols = np.mean([r[0].ci_low <= true <= r[0].ci_high for r in res])
    assert cov_sen >= 0.90 and cov_ols >= 0.90


@pytest.mark.parametrize("rho", [-0.5, 0.0, 0.5, 0.95])
def test_difference_test_false_alarms(rho):
    rng = np.random.default_rng(int(100 + rho * 10))
    n = 25
    t = np.arange(n) + 0.5
    A = ar1(rng, n, 0.3, RUNS)
    B = rho * A + np.sqrt(1 - rho**2) * ar1(rng, n, 0.3, RUNS)
    rate = np.mean([trend_test(t, a - b)[4] for a, b in zip(A, B, strict=True)])
    assert 0.02 <= rate <= 0.065, f"false alarms {rate:.3f}"


def test_cell_engine_matches_series_engine():
    rng = np.random.default_rng(9)
    n, cells = 24, 60
    t = np.arange(n) + 2001.5
    X = ar1(rng, n, 0.4, cells).T + 0.03 * t[:, None] * rng.uniform(-1, 1, cells)
    res = cell_trends(t, X)
    for c in range(0, cells, 7):
        ols, mk, sen, _, _ = trend_test(t, X[:, c])
        assert res["slope"][c] == pytest.approx(sen.slope, rel=1e-9, abs=1e-12)
        assert res["p"][c] == pytest.approx(mk.p, rel=1e-6, abs=1e-9)


def test_benjamini_hochberg_matches_definition():
    p = np.array([0.01, 0.04, 0.03, 0.2, np.nan])
    q = benjamini_hochberg(p)
    assert np.isnan(q[-1])
    np.testing.assert_allclose(q[:4], [0.04, 0.0533333, 0.0533333, 0.2], rtol=1e-5)


def test_seasonal_cell_engine_matches_series_engine():
    rng = np.random.default_rng(10)
    years, cells = 12, 25
    n = 12 * years
    t = (np.arange(n) + 0.5) / 12 + 2010
    grp = np.arange(n) % 12 + 1
    X = ar1(rng, n, 0.6, cells).T + 0.05 * (t[:, None] - 2010) * rng.uniform(-1, 1, cells)
    res = cell_trends(t, X, group=grp)
    assert res["seasonal"]
    for c in range(0, cells, 6):
        ols, mk, sen, _, _ = trend_test(t, X[:, c], 12, grp)
        assert res["slope"][c] == pytest.approx(sen.slope, rel=1e-9, abs=1e-12)
        assert res["p"][c] == pytest.approx(mk.p, rel=1e-6, abs=1e-9)


@pytest.mark.parametrize("n", [20, 30])
@pytest.mark.parametrize("phi,limit", [(0.3, 0.05), (0.5, 0.07)])
def test_no_false_speeding_up_claims(n, phi, limit):
    """A straight trend with AR(1) noise must not be called "speeding up" or "slowing down" too often."""
    from megavir.engine.stats import acceleration

    rng = np.random.default_rng(500 + n + int(phi * 10))
    t = np.arange(n) + 0.5
    X = ar1(rng, n, phi, RUNS) + 0.05 * t
    rate = np.mean([acceleration(t, x)["significant"] for x in X])
    assert rate <= limit, f"false acceleration claims {rate:.3f} > {limit}"


def test_real_acceleration_is_found():
    from megavir.engine.stats import acceleration

    rng = np.random.default_rng(7)
    n = 45
    t = np.arange(n) + 0.5
    X = ar1(rng, n, 0.3, 300) + 0.02 * t + 0.01 * t**2
    res = [acceleration(t, x) for x in X]
    assert np.mean([r["significant"] for r in res]) > 0.9
    assert all(r["kind"] == "speeding_up" for r in res if r["significant"])


@pytest.mark.parametrize("n", [120, 240])
@pytest.mark.parametrize("phi", [0.0, 0.3, 0.7])
def test_no_false_relationships(n, phi):
    """Unrelated series that share a season and a trend must rarely be called related (lag search included)."""
    from megavir.engine.related import lagged_relationship

    rng = np.random.default_rng(900 + n + int(phi * 10))
    months = np.arange(2000 * 12, 2000 * 12 + n)
    season = 5 * np.sin(2 * np.pi * (months % 12) / 12)
    A = ar1(rng, n, phi, RUNS) + season + 0.01 * months
    B = ar1(rng, n, phi, RUNS) + 2 * season
    rate = np.mean([lagged_relationship(months, a, b, 12)["significant"] for a, b in zip(A, B, strict=True)])
    assert rate <= 0.05, f"false relationships {rate:.3f}"


def test_a_real_lead_is_found_at_the_right_lag():
    from megavir.engine.related import lagged_relationship

    rng = np.random.default_rng(12)
    months = np.arange(2000 * 12, 2000 * 12 + 240)
    season = 5 * np.sin(2 * np.pi * (months % 12) / 12)
    found = 0
    for _ in range(50):
        base = ar1(rng, 243, 0.7, 1)[0]
        a = season + base[3:] + 0.8 * rng.standard_normal(240)
        b = season + base[:240] + 0.8 * rng.standard_normal(240)
        res = lagged_relationship(months, a, b, 12)
        found += res["significant"] and res["best_lag"] == 3 and res["same_direction"]
    assert found >= 45
