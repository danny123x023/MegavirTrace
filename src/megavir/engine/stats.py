"""Trend statistics: the single, deterministic source of every number MegavirTrace shows.

Everything here is plain NumPy/SciPy so it can be re-run from the exported notebook.

Conventions
-----------
* ``t`` is time in decimal years, ``y`` the values.  Slopes are per year internally and
  converted to per decade only for display.
* ``group`` (optional) holds a season label per value (the calendar month in monthly
  mode).  When it is given the Mann–Kendall test and Sen's slope are the *seasonal*
  versions (Hirsch et al. 1982): pairs are only formed inside a season.
* ``step`` is the sampling step in years (1 for one value per year, 1/12 for months).

Autocorrelation
---------------
The lag-1 autocorrelation r1 of the least-squares residuals is estimated, corrected for its
small-sample bias (measured by simulation for this exact estimator, see correct_r1_for_trend)
and used twice:

* least squares: the standard error is widened with the effective sample size
  ``n_eff = n (1 - r1) / (1 + r1)`` (Santer et al. 2000);
* Mann–Kendall: the variance of S is multiplied by the ratio Var_AR1(S) / Var_iid(S), where
  Var_AR1(S) is the variance of S for a Gaussian AR(1) series with that r1.  It is computed
  exactly from the pairwise sign covariances E[sgn(D_p) sgn(D_q)] = (2/pi) arcsin(corr(D_p, D_q))
  (the same identity that gives the textbook n(n-1)(2n+5)/18 when r1 = 0).  This is an AR(1)
  model correction, *not* the Hamed–Rao (1998) empirical rank-autocorrelation correction.
  Because r1 is estimated, Z is referred to a t distribution with the same n_eff - 2 degrees
  of freedom as the least-squares test.

Both corrections are checked by the Monte Carlo false-alarm tests in ``tests/``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy import stats as sps

ALPHA = 0.05
R1_MAX = 0.95  # upper clip for the corrected lag-1 autocorrelation
WEATHERHEAD_K = 3.3  # 90 % chance of detecting at the 5 % level (Weatherhead et al. 1998)


# --------------------------------------------------------------------------------------
# Autocorrelation
# --------------------------------------------------------------------------------------


def lag1_autocorrelation(t: np.ndarray, x: np.ndarray, step: float) -> float:
    """Lag-1 autocorrelation using only neighbours exactly one ``step`` apart (gap-aware)."""
    x = np.asarray(x, float)
    t = np.asarray(t, float)
    if x.size < 3:
        return 0.0
    order = np.argsort(t)
    t, x = t[order], x[order]
    xm = x - x.mean()
    denom = float(np.sum(xm * xm))
    if denom <= 0:
        return 0.0
    dt = np.diff(t)
    ok = np.abs(dt - step) < 0.25 * step
    if not ok.any():
        return 0.0
    num = float(np.sum(xm[:-1][ok] * xm[1:][ok]))
    # scale so that a fully regular series reproduces the usual estimator
    num *= (x.size - 1) / ok.sum()
    return num / denom


def _r1_bias_table() -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    tab = _ratio_table()
    if tab is None or "r1_mean" not in tab:
        return None
    return tab["r1_phi"], tab["r1_n"], tab["r1_mean"]


def _invert_r1(r1_hat: np.ndarray, n: int) -> np.ndarray:
    """r1 whose expected estimate E[r1_hat | r1, n] equals the observed r1_hat (one record length)."""
    r1_hat = np.asarray(r1_hat, float)
    got = _r1_bias_table()
    if n < 6 or got is None:
        return np.clip(r1_hat, 0.0, R1_MAX)
    phi, ns, mean = got
    if n > ns[-1]:
        # beyond the table the bias is ~(2 + 5 r1) / n, so r1 = (n r1_hat + 2) / (n - 5)
        return np.clip((n * r1_hat + 2.0) / (n - 5.0), -0.99, R1_MAX)
    inv = 1.0 / ns.astype(float)  # decreasing
    col = np.array([np.interp(1.0 / n, inv[::-1], mean[::-1, j]) for j in range(phi.size)])
    return np.clip(np.interp(r1_hat, col, phi), -0.99, R1_MAX)


def correct_r1_for_trend(r1_hat: float, n: int) -> float:
    """Undo the small-sample bias of r1 estimated from trend residuals.

    The lag-1 sample autocorrelation of least-squares residuals is biased low: by about
    (2 + 5 r1) / n in long records (the (2 + 4 r1) / n of van Giersbergen 2005 for the
    least-squares AR(1) estimator, plus r1 / n because this ratio divides by all n squared
    residuals), and by more at high r1 in short records (at r1 = 0.9 and n = 25 the estimate
    averages 0.56).  The mean estimate E[r1_hat | r1, n] is tabulated by simulation for exactly
    this estimator (scripts/build_r1_bias_table.py) and inverted here.
    """
    return float(_invert_r1(np.array([r1_hat]), int(n))[0])


def correct_r1_for_trend_many(r1_hat: np.ndarray, n: np.ndarray) -> np.ndarray:
    """correct_r1_for_trend for many series at once (the cell map), grouped by record length."""
    r1_hat = np.asarray(r1_hat, float)
    n = np.asarray(n, int)
    out = np.zeros_like(r1_hat)
    for nn in np.unique(n):
        sel = n == nn
        out[sel] = _invert_r1(r1_hat[sel], int(nn))
    return out


def effective_n(n: int, r1: float) -> float:
    """Effective sample size; a negative r1 is not allowed to *raise* n (conservative)."""
    r = max(0.0, r1)
    return n * (1.0 - r) / (1.0 + r)


# --------------------------------------------------------------------------------------
# Least squares with autocorrelation-corrected interval
# --------------------------------------------------------------------------------------


@dataclass
class OLSResult:
    slope: float  # per year
    intercept: float
    se: float  # ordinary standard error of the slope
    se_adj: float  # widened for autocorrelation
    ci_low: float
    ci_high: float
    t_stat: float
    df: float
    p: float
    r1_raw: float
    r1: float
    n: int
    n_eff: float
    resid_sd: float
    testable: bool


def ols_trend(t: np.ndarray, y: np.ndarray, step: float = 1.0, alpha: float = ALPHA) -> OLSResult:
    t = np.asarray(t, float)
    y = np.asarray(y, float)
    n = y.size
    tm = t - t.mean()
    sxx = float(np.sum(tm * tm))
    slope = float(np.sum(tm * (y - y.mean())) / sxx)
    intercept = float(y.mean() - slope * t.mean())
    resid = y - (intercept + slope * t)
    s2 = float(np.sum(resid * resid) / (n - 2))
    se = float(np.sqrt(s2 / sxx))
    r1_raw = lag1_autocorrelation(t, resid, step)
    r1 = correct_r1_for_trend(r1_raw, n)
    n_eff = effective_n(n, r1)
    testable = n_eff > 3.0 and se > 0
    if testable:
        df = n_eff - 2.0
        se_adj = se * float(np.sqrt((n - 2.0) / df))
        tcrit = float(sps.t.ppf(1 - alpha / 2, df))
        t_stat = slope / se_adj
        p = float(2 * sps.t.sf(abs(t_stat), df))
        lo, hi = slope - tcrit * se_adj, slope + tcrit * se_adj
    else:
        df = max(n_eff - 2.0, 0.0)
        se_adj = float("inf")
        t_stat, p, lo, hi = 0.0, 1.0, float("-inf"), float("inf")
        if se == 0:  # a perfect straight line
            se_adj, lo, hi = 0.0, slope, slope
            p = 0.0 if slope != 0 else 1.0
            testable = n >= 3
    return OLSResult(
        slope=slope,
        intercept=intercept,
        se=se,
        se_adj=se_adj,
        ci_low=lo,
        ci_high=hi,
        t_stat=t_stat,
        df=df,
        p=p,
        r1_raw=r1_raw,
        r1=r1,
        n=n,
        n_eff=n_eff,
        resid_sd=float(np.sqrt(s2)),
        testable=testable,
    )


# --------------------------------------------------------------------------------------
# Mann–Kendall with an AR(1) variance correction
# --------------------------------------------------------------------------------------


def _groups(group: np.ndarray | None, n: int) -> list[np.ndarray]:
    if group is None:
        return [np.arange(n)]
    group = np.asarray(group)
    return [np.flatnonzero(group == g) for g in np.unique(group)]


def _tie_variance(x: np.ndarray) -> float:
    n = x.size
    _, counts = np.unique(x, return_counts=True)
    ties = counts[counts > 1]
    return (n * (n - 1) * (2 * n + 5) - float(np.sum(ties * (ties - 1) * (2 * ties + 5)))) / 18.0


@lru_cache(maxsize=4096)
def _ar1_var_sum(n: int, phi: float, n_seasons: int) -> float:
    """Var(S) / 1 for a regular Gaussian AR(1) series, summed over all pairs of pairs.

    Pairs (i, j) and (k, l) with i < j, k < l are described by u = j - i, v = l - k and
    w = k - i; their multiplicity in a record of n points is counted in closed form, so the
    cost is O(n^3) instead of O(n^4).  With ``n_seasons`` = 12 the series is monthly and
    seasons are calendar months; pairs are formed within a season (years apart) and
    seasons g, h are offset by delta = h - g months.
    """
    m = n_seasons
    idx = np.arange(1, n)
    u, v, w = np.meshgrid(idx, idx, np.arange(-(n - 1), n), indexing="ij")
    u, v, w = u.ravel(), v.ravel(), w.ravel()
    lo = np.maximum(0, -w)
    hi = np.minimum(n - 1 - u, n - 1 - w - v)
    mult = hi - lo + 1
    keep = mult > 0
    u, v, w, mult = u[keep], v[keep], w[keep], mult[keep].astype(float)

    def gamma(d):
        return np.power(phi, np.abs(d))

    total = 0.0
    deltas = range(-(m - 1), m) if m > 1 else [0]
    for delta in deltas:
        weight = m - abs(delta)
        ut, vt, wt = m * u, m * v, m * w + delta
        cov = gamma(ut - wt - vt) - gamma(ut - wt) - gamma(wt + vt) + gamma(wt)
        var_u = 2.0 * (1.0 - gamma(ut))
        var_v = 2.0 * (1.0 - gamma(vt))
        c = np.clip(cov / np.sqrt(var_u * var_v), -1.0, 1.0)
        total += weight * float(np.sum(mult * np.arcsin(c)))
    return total * 2.0 / np.pi


def ar1_variance_ratio_exact(n: int, r1: float, seasonal: bool = False) -> float:
    """Var(S) under AR(1) with lag-1 correlation r1, divided by Var(S) for independent data."""
    phi = round(max(0.0, min(r1, R1_MAX)), 3)
    if phi == 0.0 or n < 3:
        return 1.0
    m = 12 if seasonal else 1
    return _ar1_var_sum(n, phi, m) / _ar1_var_sum(n, 0.0, m)


_TABLE_PATH = Path(__file__).with_name("data") / "ar1_ratio.npz"


@lru_cache(maxsize=1)
def _ratio_table() -> dict | None:
    if not _TABLE_PATH.exists():
        return None
    with np.load(_TABLE_PATH) as z:
        return {k: z[k] for k in z.files}


def _interp_table(ns: np.ndarray, phis: np.ndarray, table: np.ndarray, n: int, phi: float) -> float:
    """Bilinear in (1/n, phi); beyond the longest tabulated n, extrapolate linearly in 1/n."""
    col = np.array([np.interp(phi, phis, row) for row in table])
    inv = 1.0 / ns.astype(float)  # decreasing
    x = 1.0 / n
    if n <= ns[-1]:
        return float(np.interp(x, inv[::-1], col[::-1]))
    # r(n) ~= L - c / n, fitted on the two longest tabulated records
    x1, x2 = inv[-2], inv[-1]
    y1, y2 = col[-2], col[-1]
    return float(y2 + (y2 - y1) / (x2 - x1) * (x - x2))


def ar1_variance_ratio(n: int, r1: float, seasonal: bool = False) -> float:
    """Var_AR1(S) / Var_iid(S), from the precomputed exact table (exact computation as fallback)."""
    phi = max(0.0, min(r1, R1_MAX))
    if phi == 0.0 or n < 3:
        return 1.0
    tab = _ratio_table()
    if tab is None:
        return ar1_variance_ratio_exact(n, phi, seasonal)
    if seasonal:
        return _interp_table(tab["n_monthly"], tab["phi"], tab["monthly"], n, phi)
    return _interp_table(tab["n_annual"], tab["phi"], tab["annual"], n, phi)


@dataclass
class MKResult:
    S: float
    var_s: float  # tie-corrected, independent-data variance
    var_s_adj: float  # after the AR(1) correction
    variance_ratio: float
    Z: float
    p: float
    tau: float
    n: int
    seasonal: bool


def mann_kendall(
    t: np.ndarray,
    y: np.ndarray,
    r1: float = 0.0,
    group: np.ndarray | None = None,
    df: float | None = None,
) -> MKResult:
    """Mann–Kendall (seasonal when ``group`` is given) with the AR(1) variance correction.

    With ``df`` the Z statistic is referred to a Student t distribution with ``df`` degrees of
    freedom (the least-squares test's n_eff - 2) instead of the normal: the corrected variance
    depends on an *estimated* r1, and the Monte Carlo tests show the normal reference is then
    too eager (about 8 % false alarms at r1 = 0.5 and n = 20).  ``df=None`` gives the textbook
    normal test, used to check against reference libraries.
    """
    t = np.asarray(t, float)
    y = np.asarray(y, float)
    S = 0.0
    var0 = 0.0
    n_pairs = 0
    sizes = []
    for g in _groups(group, y.size):
        order = g[np.argsort(t[g])]
        x = y[order]
        k = x.size
        if k < 2:
            continue
        diff = x[None, :] - x[:, None]
        S += float(np.sum(np.sign(diff[np.triu_indices(k, 1)])))
        var0 += _tie_variance(x)
        n_pairs += k * (k - 1) // 2
        sizes.append(k)
    seasonal = group is not None
    n_typ = int(np.median(sizes)) if sizes else 0
    ratio = ar1_variance_ratio(n_typ, r1, seasonal) if n_typ >= 3 else 1.0
    var_adj = var0 * ratio
    if S > 0:
        Z = (S - 1) / np.sqrt(var_adj)
    elif S < 0:
        Z = (S + 1) / np.sqrt(var_adj)
    else:
        Z = 0.0
    if var_adj <= 0:
        p = 1.0
    elif df is not None:
        p = float(2 * sps.t.sf(abs(Z), max(df, 1.0)))
    else:
        p = float(2 * sps.norm.sf(abs(Z)))
    tau = S / n_pairs if n_pairs else 0.0
    return MKResult(
        S=S,
        var_s=var0,
        var_s_adj=var_adj,
        variance_ratio=ratio,
        Z=float(Z),
        p=p,
        tau=float(tau),
        n=int(y.size),
        seasonal=seasonal,
    )


# --------------------------------------------------------------------------------------
# Sen's slope
# --------------------------------------------------------------------------------------


def pairwise_slopes(t: np.ndarray, y: np.ndarray, group: np.ndarray | None = None) -> np.ndarray:
    t = np.asarray(t, float)
    y = np.asarray(y, float)
    out = []
    for g in _groups(group, y.size):
        if g.size < 2:
            continue
        i, j = np.triu_indices(g.size, 1)
        dt = t[g][j] - t[g][i]
        ok = dt != 0
        out.append((y[g][j] - y[g][i])[ok] / dt[ok])
    return np.concatenate(out) if out else np.empty(0)


@dataclass
class SenResult:
    slope: float  # per year
    ci_low: float
    ci_high: float
    intercept: float


def sen_slope(
    t: np.ndarray,
    y: np.ndarray,
    var_s: float,
    group: np.ndarray | None = None,
    alpha: float = ALPHA,
) -> SenResult:
    """Sen (1968) slope; interval from the (autocorrelation-corrected) variance of S (Gilbert 1987)."""
    slopes = np.sort(pairwise_slopes(t, y, group))
    N = slopes.size
    if N == 0:
        return SenResult(0.0, float("-inf"), float("inf"), float(np.median(y)))
    slope = float(np.median(slopes))
    c = float(sps.norm.ppf(1 - alpha / 2) * np.sqrt(max(var_s, 0.0)))
    m1 = (N - c) / 2.0  # 1-based rank of the lower limit
    m2 = (N + c) / 2.0 + 1.0  # 1-based rank of the upper limit
    ranks = np.arange(1, N + 1)
    lo = float(np.interp(m1, ranks, slopes)) if m1 >= 1 else float("-inf")
    hi = float(np.interp(m2, ranks, slopes)) if m2 <= N else float("inf")
    intercept = float(np.median(np.asarray(y) - slope * np.asarray(t)))
    return SenResult(slope=slope, ci_low=lo, ci_high=hi, intercept=intercept)


# --------------------------------------------------------------------------------------
# Detectability, size against the noise, robustness
# --------------------------------------------------------------------------------------


def years_to_detect(slope_per_year: float, noise_sd: float, r1: float, per_year: int) -> float:
    """Weatherhead et al. (1998) n*: years of data needed to detect a trend of this size.

    n* = [3.3 sigma_N / |omega| * sqrt((1 + phi) / (1 - phi))]^(2/3).  Weatherhead writes it for
    monthly data; with ``per_year`` values per year the noise term scales by sqrt(12 / per_year),
    because the variance of a fitted slope over n years is 12 sigma^2 / (per_year n^3).
    """
    if slope_per_year == 0 or not np.isfinite(slope_per_year):
        return float("inf")
    phi = float(np.clip(r1, 0.0, R1_MAX))
    scale = np.sqrt(12.0 / per_year)
    inner = WEATHERHEAD_K * scale * noise_sd / abs(slope_per_year) * np.sqrt((1 + phi) / (1 - phi))
    return float(inner ** (2.0 / 3.0))


EFFECT_LABELS = ((0.5, "small"), (1.0, "moderate"), (2.0, "large"), (float("inf"), "very large"))


def size_against_noise(slope_per_year: float, span_years: float, noise_sd: float) -> tuple[float, str]:
    """How far the trend line moves over the record, divided by the scatter around it."""
    if noise_sd <= 0:
        return float("inf"), "very large"
    ratio = abs(slope_per_year) * span_years / noise_sd
    for limit, label in EFFECT_LABELS:
        if ratio < limit:
            return float(ratio), label
    return float(ratio), "very large"


@dataclass
class RobustnessResult:
    fragile: bool
    checks: list[dict] = field(default_factory=list)  # {"check": str, "slope": float, "keeps_sign": bool}


def robustness(
    t: np.ndarray, y: np.ndarray, years: np.ndarray, group: np.ndarray | None = None
) -> RobustnessResult:
    """Sen's slope must keep its sign in each half, without the end years and leaving out any one year."""
    t = np.asarray(t, float)
    y = np.asarray(y, float)
    years = np.asarray(years)
    full = float(np.median(pairwise_slopes(t, y, group))) if y.size > 1 else 0.0
    sign = np.sign(full)
    uniq = np.unique(years)
    checks: list[dict] = []

    def run(name: str, mask: np.ndarray) -> None:
        g = group[mask] if group is not None else None
        sl = pairwise_slopes(t[mask], y[mask], g)
        if sl.size == 0:
            return
        s = float(np.median(sl))
        checks.append({"check": name, "slope": s, "keeps_sign": bool(sign != 0 and np.sign(s) == sign)})

    if uniq.size >= 6:
        half = uniq[uniq.size // 2]
        run("first half", years < half)
        run("second half", years >= half)
        run("without first and last years", (years != uniq[0]) & (years != uniq[-1]))
    for yr in uniq:
        run(f"without {int(yr)}", years != yr)
    fragile = sign == 0 or any(not c["keeps_sign"] for c in checks)
    return RobustnessResult(fragile=bool(fragile), checks=checks)


# --------------------------------------------------------------------------------------
# Exploratory clues
# --------------------------------------------------------------------------------------


def unusual_points(resid: np.ndarray, labels: list[str], k: float = 2.0) -> list[dict]:
    sd = float(np.std(resid, ddof=1)) if resid.size > 2 else 0.0
    if sd == 0:
        return []
    out = []
    for r, lab in zip(resid, labels, strict=True):
        if abs(r) > k * sd:
            out.append({"label": lab, "departure": float(r), "sd_units": float(r / sd)})
    return out


def turning_point(t: np.ndarray, y: np.ndarray, min_points: int = 5) -> dict | None:
    """Best continuous two-piece (hinge) line; kept only if it beats a straight line on BIC."""
    t = np.asarray(t, float)
    y = np.asarray(y, float)
    n = y.size
    if n < 2 * min_points + 1:
        return None
    order = np.argsort(t)
    t, y = t[order], y[order]
    X1 = np.column_stack([np.ones(n), t])
    rss1 = float(np.sum((y - X1 @ np.linalg.lstsq(X1, y, rcond=None)[0]) ** 2))
    best = None
    for k in range(min_points, n - min_points):
        tb = t[k]
        X2 = np.column_stack([np.ones(n), t, np.maximum(t - tb, 0.0)])
        beta = np.linalg.lstsq(X2, y, rcond=None)[0]
        rss = float(np.sum((y - X2 @ beta) ** 2))
        if best is None or rss < best[0]:
            best = (rss, tb, beta)
    if best is None or best[0] <= 0 or rss1 <= 0:
        return None
    rss2, tb, beta = best
    bic1 = n * np.log(rss1 / n) + 2 * np.log(n)
    bic2 = n * np.log(rss2 / n) + 4 * np.log(n)  # hinge location counts as a parameter
    return {
        "at": float(tb),
        "slope_before": float(beta[1]),
        "slope_after": float(beta[1] + beta[2]),
        "bic_straight": float(bic1),
        "bic_two_piece": float(bic2),
        "preferred": bool(bic2 < bic1 - 2.0),
    }


# --------------------------------------------------------------------------------------
# The whole trend analysis of one series
# --------------------------------------------------------------------------------------


# --------------------------------------------------------------------------------------
# Is it speeding up? (FR7)
# --------------------------------------------------------------------------------------

ALPHA_ACCEL = (
    0.025  # stricter: calibrated by Monte Carlo to keep false "speeding up" claims in the trend targets
)
MIN_YEARS_ACCEL = 15


def acceleration(t: np.ndarray, y: np.ndarray, alpha: float = ALPHA_ACCEL) -> dict:
    """Is the trend speeding up, slowing down or changing direction?

    A straight line misreads acceleration, so the curvature term c of y = a + b t + c t^2 is
    tested with the same autocorrelation treatment as the trend: r1 from the quadratic
    residuals, corrected for the bias of a three-parameter fit ((n r1 + 3) / (n - 5)), the
    standard error widened with n_eff and a t-test with n_eff - 3 degrees of freedom.  A
    claim needs p < 0.025 (stricter than for the trend itself) and the robust Sen slopes of the
    two halves of the record must show the same change.  Monte Carlo: at most 3.3 % false
    claims at r1 = 0.3 and 4.8 % at r1 = 0.5 for a straight trend with AR(1) noise.
    """
    t = np.asarray(t, float)
    y = np.asarray(y, float)
    n = y.size
    out = {"tested": False, "significant": False, "kind": None, "alpha": alpha}
    if np.unique(np.floor(t)).size < MIN_YEARS_ACCEL:
        out["reason"] = f"needs at least {MIN_YEARS_ACCEL} years"
        return out
    order = np.argsort(t)
    t, y = t[order], y[order]
    tc = t - t.mean()
    X = np.column_stack([np.ones(n), tc, tc * tc])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    res = y - X @ beta
    s2 = float(res @ res) / (n - 3)
    cov = s2 * np.linalg.inv(X.T @ X)
    r1_hat = lag1_autocorrelation(t, res, 1.0)
    r1 = float(np.clip((n * r1_hat + 3.0) / (n - 5.0), 0.0, R1_MAX))
    n_eff = effective_n(n, r1)
    h = n // 2
    early = float(np.median(pairwise_slopes(t[:h], y[:h])))
    late = float(np.median(pairwise_slopes(t[h:], y[h:])))
    out.update(
        {
            "tested": True,
            "curvature": float(beta[2]),
            "slope_early": early,
            "slope_late": late,
            "split": float(t[h]),
            "first": float(t[0]),
            "last": float(t[-1]),
            "r1": r1,
            "n_eff": n_eff,
        }
    )
    if n_eff <= 4 or cov[2, 2] <= 0:
        out["p"] = 1.0
        out["reason"] = "too few independent values"
        return out
    df = n_eff - 3.0
    se = float(np.sqrt(cov[2, 2]) * np.sqrt((n - 3.0) / df))
    p = float(2 * sps.t.sf(abs(beta[2] / se), df))
    out["p"] = p
    c = float(beta[2])
    agrees = late != early and np.sign(late - early) == np.sign(c)
    if p < alpha and agrees:
        out["significant"] = True
        if early != 0 and late != 0 and np.sign(early) != np.sign(late):
            out["kind"] = "changed_direction"
        elif abs(late) > abs(early):
            out["kind"] = "speeding_up"
        else:
            out["kind"] = "slowing_down"
    return out


@dataclass
class TrendStats:
    n: int
    per_year: int
    seasonal_test: bool
    first: float
    last: float
    ols: OLSResult
    mk: MKResult
    sen: SenResult
    significant: bool
    agree: bool
    direction: str  # "rising" | "falling" | "flat"
    years_needed: float
    years_more: float
    effect_ratio: float
    effect_label: str
    robustness: RobustnessResult
    unusual: list[dict]
    turning: dict | None
    acceleration: dict | None
    alpha: float = ALPHA

    def to_dict(self) -> dict:
        return _clean(asdict(self))


def _clean(obj):
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_clean(v) for v in obj]
    if isinstance(obj, float | np.floating):
        f = float(obj)
        if np.isnan(f):
            return None
        if np.isinf(f):
            return "inf" if f > 0 else "-inf"
        return f
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    return obj


MIN_POINTS = 8


def trend_test(
    t: np.ndarray,
    y: np.ndarray,
    per_year: int = 1,
    group: np.ndarray | None = None,
    alpha: float = ALPHA,
) -> tuple[OLSResult, MKResult, SenResult, bool, bool]:
    """The agreement rule: significant only if both corrected tests pass and all signs agree."""
    ols = ols_trend(t, y, step=1.0 / per_year, alpha=alpha)
    mk = mann_kendall(t, y, r1=ols.r1, group=group, df=ols.df if ols.testable else None)
    sen = sen_slope(t, y, mk.var_s_adj, group=group, alpha=alpha)
    signs = {np.sign(ols.slope), np.sign(sen.slope), np.sign(mk.S)}
    agree = len(signs) == 1 and 0 not in signs
    significant = bool(ols.testable and ols.p < alpha and mk.p < alpha and agree)
    return ols, mk, sen, agree, significant


class NotEnoughData(ValueError):
    pass


def analyse_trend(
    t: np.ndarray,
    y: np.ndarray,
    years: np.ndarray,
    labels: list[str],
    per_year: int = 1,
    group: np.ndarray | None = None,
    alpha: float = ALPHA,
) -> TrendStats:
    t = np.asarray(t, float)
    y = np.asarray(y, float)
    ok = np.isfinite(y) & np.isfinite(t)
    t, y, years = t[ok], y[ok], np.asarray(years)[ok]
    labels = [lab for lab, k in zip(labels, ok, strict=True) if k]
    g = np.asarray(group)[ok] if group is not None else None
    n_years = np.unique(years).size
    if y.size < MIN_POINTS or n_years < MIN_POINTS:
        raise NotEnoughData(f"needs at least {MIN_POINTS} years with data, found {n_years}")

    step = 1.0 / per_year
    ols, mk, sen, agree, significant = trend_test(t, y, per_year, g, alpha)
    direction = "flat" if sen.slope == 0 else ("rising" if sen.slope > 0 else "falling")

    span = float(t.max() - t.min()) + step
    n_star = years_to_detect(sen.slope, ols.resid_sd, ols.r1, per_year)
    years_more = max(0.0, float(np.ceil(n_star - span))) if np.isfinite(n_star) else float("inf")
    eff, eff_label = size_against_noise(sen.slope, span - step, ols.resid_sd)
    rob = robustness(t, y, years, g)
    resid = y - (ols.intercept + ols.slope * t)
    return TrendStats(
        n=int(y.size),
        per_year=per_year,
        seasonal_test=g is not None,
        first=float(t.min()),
        last=float(t.max()),
        ols=ols,
        mk=mk,
        sen=sen,
        significant=significant,
        agree=agree,
        direction=direction,
        years_needed=n_star,
        years_more=years_more,
        effect_ratio=eff,
        effect_label=eff_label,
        robustness=rob,
        unusual=unusual_points(resid, labels),
        turning=turning_point(t, y) if per_year == 1 else None,
        acceleration=acceleration(t, y) if per_year == 1 else None,
        alpha=alpha,
    )
