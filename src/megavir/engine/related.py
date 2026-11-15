"""Moves together (FR11): how two variables are related in one place, with a time lag.

Always labelled "related, not caused by".  Three things make naive correlations of climate
series misleading, and all are handled:

* shared seasons and shared long-term trends make almost any two series correlate, so each
  series becomes monthly anomalies (seasonal cycle removed) and is then detrended;
* neighbouring months are alike, and removing monthly means leaves its own pattern
  (correlation 12, 24, 36 months apart), so the number of independent pairs is estimated with
  Bartlett's formula, Var(r) = (1 + 2 sum_j rho_a(j) rho_b(j)) / n, summed to 36 months, minus the
  13 degrees of freedom removed from n once (12 monthly means and a trend; Bretherton et al. 1999 discuss
  the lag-1 form);
* searching over many lags gives many chances, so the best lag's p-value is multiplied by the
  number of lags tried (Bonferroni).
"""

from __future__ import annotations

import numpy as np
from scipy import stats as sps

from .stats import ALPHA, lag1_autocorrelation

MIN_PAIRS = 36  # at least three years of shared months


def _monthly_anomalies(months_abs: np.ndarray, values: np.ndarray) -> np.ndarray:
    cal = np.asarray(months_abs) % 12
    v = np.asarray(values, float)
    out = np.full_like(v, np.nan)
    for c in range(12):
        sel = (cal == c) & np.isfinite(v)
        if sel.sum() >= 2:
            out[sel] = v[sel] - v[sel].mean()
    return out


def _detrend(t: np.ndarray, v: np.ndarray) -> np.ndarray:
    ok = np.isfinite(v)
    out = np.full_like(v, np.nan)
    if ok.sum() >= 3:
        b = np.polyfit(t[ok], v[ok], 1)
        out[ok] = v[ok] - np.polyval(b, t[ok])
    return out


def _standardise(v: np.ndarray) -> np.ndarray:
    ok = np.isfinite(v)
    sd = v[ok].std() if ok.sum() > 2 else 0
    return (v - np.nanmean(v)) / sd if sd > 0 else np.full_like(v, np.nan)


def _corrected_r1(t: np.ndarray, v: np.ndarray, step: float) -> float:
    """Lag-1 autocorrelation of monthly anomalies after detrending, corrected for its bias.

    Removing 12 monthly means and a trend biases r1 low by about (1 + 5.5 r1) / n (measured by
    simulation for n = 120-480), so r1 = (n r1_hat + 1) / (n - 5.5).
    """
    n = v.size
    if n <= 12:
        return 0.0
    r = lag1_autocorrelation(t, v, step)
    return float(np.clip((n * r + 1.0) / (n - 5.5), 0.0, 0.99))


def _acf(v: np.ndarray, max_lag: int) -> np.ndarray:
    """Autocorrelation of a regular monthly series with gaps (NaN), lags 0..max_lag."""
    x = v - np.nanmean(v)
    ok = np.isfinite(x)
    den = float(np.nansum(x * x)) / ok.sum()
    out = np.zeros(max_lag + 1)
    out[0] = 1.0
    for k in range(1, max_lag + 1):
        a, b = x[:-k], x[k:]
        m = np.isfinite(a) & np.isfinite(b)
        out[k] = float(np.sum(a[m] * b[m]) / m.sum() / den) if m.sum() > 2 and den > 0 else 0.0
    return out


def _overlap_series(full: np.ndarray, aa: np.ndarray, bb: np.ndarray) -> dict:
    """Standardized anomalies for the chart, trimmed to the months both series cover."""
    both = np.flatnonzero(np.isfinite(aa) & np.isfinite(bb))
    sl = slice(both[0], both[-1] + 1) if both.size else slice(0, 0)
    za, zb = _standardise(aa[sl]), _standardise(bb[sl])
    return {
        "months": [int(m) for m in full[sl]],
        "a_std": [None if not np.isfinite(v) else float(v) for v in za],
        "b_std": [None if not np.isfinite(v) else float(v) for v in zb],
    }


def lagged_relationship(
    months_abs: np.ndarray, a: np.ndarray, b: np.ndarray, max_lag: int = 12, alpha: float = ALPHA
) -> dict:
    """a, b: monthly regional values on the same month axis.  Positive lag k: b follows a by k months."""
    months_abs = np.asarray(months_abs, int)
    order = np.argsort(months_abs)
    months_abs = months_abs[order]
    full = np.arange(months_abs[0], months_abs[-1] + 1)  # regular axis so lags are true months
    A = np.full(full.size, np.nan)
    B = np.full(full.size, np.nan)
    A[months_abs - full[0]] = np.asarray(a, float)[order]
    B[months_abs - full[0]] = np.asarray(b, float)[order]
    t = full / 12.0
    aa = _detrend(t, _monthly_anomalies(full, A))
    bb = _detrend(t, _monthly_anomalies(full, B))
    step = 1.0 / 12
    oka, okb = np.isfinite(aa), np.isfinite(bb)
    r1a = _corrected_r1(t[oka], aa[oka], step)
    r1b = _corrected_r1(t[okb], bb[okb], step)
    # Bartlett: Var(r) = (1/n) * (1 + 2 sum_j rho_a(j) rho_b(j)) for unrelated series.  Summing to 36
    # months catches the pattern that removing monthly means leaves at 12, 24 and 36 months.
    J = int(min(36, max(12, oka.sum() // 4)))
    ra, rb = _acf(aa, J), _acf(bb, J)
    # lag 1 uses the bias-corrected values; the rest are the sample autocorrelations
    ra[1], rb[1] = r1a, r1b
    inflation = max(1.0, 1.0 + 2.0 * float(np.sum(ra[1:] * rb[1:])))
    USED_DF = 13  # 12 monthly means and a trend were removed from each series

    lags = list(range(-max_lag, max_lag + 1))
    rs, ps, ns, neffs = [], [], [], []
    for k in lags:
        if k >= 0:
            x, y = aa[: aa.size - k], bb[k:]
        else:
            x, y = aa[-k:], bb[: bb.size + k]
        ok = np.isfinite(x) & np.isfinite(y)
        n = int(ok.sum())
        if n < MIN_PAIRS:
            rs.append(None), ps.append(None), ns.append(n), neffs.append(None)
            continue
        r = float(np.corrcoef(x[ok], y[ok])[0, 1])
        n_eff = (n - USED_DF) / inflation
        if n_eff > 3 and abs(r) < 1:
            tt = r * np.sqrt((n_eff - 2) / (1 - r * r))
            p = float(2 * sps.t.sf(abs(tt), n_eff - 2))
        else:
            p = 1.0
        rs.append(r), ps.append(p), ns.append(n), neffs.append(float(n_eff))

    tested = [i for i, r in enumerate(rs) if r is not None]
    if not tested:
        return {
            "tested": False,
            "reason": f"the two records share fewer than {MIN_PAIRS} months",
            "lags": lags,
        }
    best = max(tested, key=lambda i: abs(rs[i]))
    p_adj = min(1.0, ps[best] * len(tested))  # Bonferroni over the lags searched
    n_eff_best = neffs[best] or 0.0
    # |r| needed at this lag for significance after the correction (for the chart's reference band)
    crit = None
    if n_eff_best > 3:
        tc = sps.t.isf(alpha / (2 * len(tested)), n_eff_best - 2)
        crit = float(tc / np.sqrt(n_eff_best - 2 + tc * tc))
    return {
        "tested": True,
        "lags": lags,
        "r": rs,
        "p": ps,
        "n": ns,
        "best_lag": lags[best],
        "best_r": rs[best],
        "p_adjusted": p_adj,
        "n_lags_tested": len(tested),
        "variance_inflation": inflation,
        "n_eff": n_eff_best,
        "r1_a": r1a,
        "r1_b": r1b,
        "r_needed": crit,
        "significant": bool(p_adj < alpha),
        "same_direction": bool(rs[best] > 0),
        **_overlap_series(full, aa, bb),
    }
