"""Where inside the region (FR8): a trend for every grid cell, then false-discovery control.

A vectorised Sen slope and AR(1)-corrected Mann–Kendall test (t reference with n_eff - 2
degrees of freedom, as in the single-series engine) runs on each cell's yearly (or seasonal)
series.  Benjamini–Hochberg q-values are computed across the cells of the region,
and a cell "passes" when q <= 2 alpha: Wilks (2016) shows that, for spatially correlated
fields, controlling the FDR at alpha_FDR = 2 alpha_global keeps the chance of any false
field-wide finding near alpha_global.

Which cells pass depends on the region tested (the FDR is computed over its cells), and the
map says so.  In monthly mode the map uses yearly values.
"""

from __future__ import annotations

import warnings

import numpy as np
from scipy import stats as sps

from .stats import ALPHA, MIN_POINTS, R1_MAX, _ratio_table, ar1_variance_ratio

FDR_FACTOR = 2.0  # Wilks (2016): alpha_FDR = 2 * alpha_global


def benjamini_hochberg(p: np.ndarray) -> np.ndarray:
    """BH q-values (adjusted p), NaN-aware."""
    p = np.asarray(p, float)
    q = np.full_like(p, np.nan)
    ok = np.isfinite(p)
    pv = p[ok]
    m = pv.size
    if m == 0:
        return q
    order = np.argsort(pv)
    ranked = pv[order] * m / np.arange(1, m + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(m)
    out[order] = np.minimum(ranked, 1.0)
    q[ok] = out
    return q


def nanmedian_axis0(a: np.ndarray) -> np.ndarray:
    """Median along axis 0 ignoring NaN, vectorised.

    np.nanmedian falls back to a Python loop per column when NaNs exist.  Complete columns get
    one linear-time np.partition; columns with gaps are sorted (NaNs sort to the end) and the
    two middle ranks of their finite values are read off.
    """
    n = a.shape[0]
    k = np.isfinite(a).sum(axis=0)
    out = np.full(a.shape[1], np.nan)
    full = np.flatnonzero(k == n)
    if full.size and n:
        lo, hi = (n - 1) // 2, n // 2
        part = np.partition(a[:, full], [lo, hi] if lo != hi else lo, axis=0)
        out[full] = (part[lo] + part[hi]) / 2.0
    gap = np.flatnonzero((k < n) & (k > 0))
    if gap.size:
        srt = np.sort(a[:, gap], axis=0)
        kk = k[gap]
        cols = np.arange(gap.size)
        out[gap] = (srt[(kk - 1) // 2, cols] + srt[kk // 2, cols]) / 2.0
    return out


def _ratio_vector(n: np.ndarray, r1: np.ndarray, seasonal: bool = False) -> np.ndarray:
    """AR(1) variance ratio for many cells at once (table lookup per distinct n).

    For the seasonal test n is the typical number of years per calendar month.
    """
    out = np.ones_like(r1, dtype=float)
    tab = _ratio_table()
    key_n, key_t = ("n_monthly", "monthly") if seasonal else ("n_annual", "annual")
    for nv in np.unique(n):
        sel = n == nv
        if nv < 3:
            continue
        if tab is None:
            out[sel] = [ar1_variance_ratio(int(nv), float(r), seasonal) for r in r1[sel]]
            continue
        # interpolate the table row for this n (in 1/n), then in phi
        ns = tab[key_n].astype(float)
        table = tab[key_t]
        inv = 1.0 / ns
        x = 1.0 / nv
        if nv <= ns[-1]:
            row = np.array([np.interp(x, inv[::-1], table[::-1, k]) for k in range(tab["phi"].size)])
        else:
            y1, y2 = table[-2], table[-1]
            row = y2 + (y2 - y1) / (inv[-1] - inv[-2]) * (x - inv[-1])
        out[sel] = np.interp(np.clip(r1[sel], 0.0, R1_MAX), tab["phi"], row)
    return out


CHUNK_ELEMENTS = 4_000_000  # pairs x cells per chunk (keeps memory to a few hundred MB)


def _pairs(n_t: int, group: np.ndarray | None) -> tuple[np.ndarray, np.ndarray]:
    i, j = np.triu_indices(n_t, 1)
    if group is not None:
        same = group[i] == group[j]
        i, j = i[same], j[same]
    return i, j


def cell_trends(
    t: np.ndarray, cube: np.ndarray, alpha: float = ALPHA, group: np.ndarray | None = None
) -> dict:
    """t: (n,) decimal years; cube: (n, ncell) values with NaN.  Returns per-cell arrays.

    With ``group`` (the calendar month of each row, rows consecutive months) the seasonal
    Mann–Kendall test and seasonal Sen slope are used, as in the single-series engine.
    The per-cell tests run in chunks of cells; the FDR step then runs over all cells.
    """
    X = np.asarray(cube, float)
    t = np.asarray(t, float)
    g = np.asarray(group) if group is not None else None
    n_t, n_c = X.shape
    i, j = _pairs(n_t, g)
    step = max(1, CHUNK_ELEMENTS // max(1, i.size))
    parts = [_cell_tests(t, X[:, k : k + step], i, j, g) for k in range(0, n_c, step)]
    sen = np.concatenate([q[0] for q in parts]) if parts else np.empty(0)
    p = np.concatenate([q[1] for q in parts]) if parts else np.empty(0)
    n = np.concatenate([q[2] for q in parts]) if parts else np.empty(0, int)
    r1 = np.concatenate([q[3] for q in parts]) if parts else np.empty(0)
    q = benjamini_hochberg(p)
    passes = np.where(np.isfinite(q), q <= FDR_FACTOR * alpha, False)
    return {
        "slope": sen,  # per year
        "p": p,
        "q": q,
        "passes": passes,
        "raw_significant": np.where(np.isfinite(p), p < alpha, False),
        "n": n,
        "r1": r1,
        "alpha_fdr": FDR_FACTOR * alpha,
        "seasonal": g is not None,
    }


def _cell_tests(t, X, i, j, group):
    with warnings.catch_warnings():  # all-empty cells give harmless "mean of empty slice" warnings
        warnings.simplefilter("ignore", RuntimeWarning)
        return _cell_tests_inner(t, X, i, j, group)


def _cell_tests_inner(
    t: np.ndarray, X: np.ndarray, i: np.ndarray, j: np.ndarray, group: np.ndarray | None
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    X = np.asarray(X, float)
    valid = np.isfinite(X)
    n = valid.sum(axis=0)

    dx = X[j] - X[i]  # (pairs, cells)
    dt = (t[j] - t[i])[:, None]
    S = np.nansum(np.sign(dx), axis=0)
    sen = nanmedian_axis0(dx / dt)

    # least-squares residual lag-1 autocorrelation per cell (consecutive rows = one step)
    tt = np.where(valid, t[:, None], np.nan)
    tm = tt - np.nanmean(tt, axis=0)
    xm = X - np.nanmean(X, axis=0)
    b = np.nansum(tm * xm, axis=0) / np.nansum(tm * tm, axis=0)
    resid = xm - b * tm
    num = np.nansum(resid[:-1] * resid[1:], axis=0)
    den = np.nansum(resid * resid, axis=0)
    pairs_ok = (valid[:-1] & valid[1:]).sum(axis=0)
    r1_hat = num / den * (n - 1) / np.maximum(pairs_ok, 1)
    r1 = np.where(n > 6, (n * r1_hat + 2.0) / (n - 4.0), r1_hat)
    r1 = np.clip(np.nan_to_num(r1), 0.0, R1_MAX)

    if group is None:
        var0 = n * (n - 1) * (2 * n + 5) / 18.0
        n_typ = n
    else:
        var0 = np.zeros(X.shape[1])
        sizes = []
        for gv in np.unique(group):
            ng = valid[group == gv].sum(axis=0)
            var0 += ng * (ng - 1) * (2 * ng + 5) / 18.0
            sizes.append(ng)
        n_typ = np.median(np.vstack(sizes), axis=0).astype(int)
    var = var0 * _ratio_vector(n_typ, r1, seasonal=group is not None)
    Z = np.where(S > 0, (S - 1) / np.sqrt(var), np.where(S < 0, (S + 1) / np.sqrt(var), 0.0))
    n_eff = n * (1.0 - r1) / (1.0 + r1)
    p = 2 * sps.t.sf(np.abs(Z), np.maximum(n_eff - 2.0, 1.0))
    enough = (n_typ if group is not None else n) >= MIN_POINTS
    p = np.where(enough, p, np.nan)
    sen = np.where(enough, sen, np.nan)
    return sen, p, n, r1
