"""Comparing two regions (FR10): the test is on the trend of the difference series A − B.

Shared ups and downs cancel in the difference, so regions that move together are not
under-tested and regions that move apart are not over-tested (Santer et al. 2000).
"""

from __future__ import annotations

import numpy as np
from scipy import stats as sps

from .aggregate import Series
from .stats import ALPHA, analyse_trend

POWER = 0.80


def align(
    a: Series, b: Series
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[str], np.ndarray | None]:
    if a.mode != b.mode or a.per_year != b.per_year:
        raise ValueError("both regions must use the same aggregation")
    ia = {lab: i for i, lab in enumerate(a.labels)}
    common = [lab for lab in b.labels if lab in ia]
    ib = {lab: i for i, lab in enumerate(b.labels)}
    sa = np.array([ia[lab] for lab in common], int)
    sb = np.array([ib[lab] for lab in common], int)
    group = a.group[sa] if a.group is not None else None
    return a.t[sa], a.y[sa], b.y[sb], a.years[sa], common, group


def compare_series(a: Series, b: Series, alpha: float = ALPHA) -> dict:
    t, ya, yb, years, labels, group = align(a, b)
    ok = np.isfinite(ya) & np.isfinite(yb)
    t, ya, yb, years = t[ok], ya[ok], yb[ok], years[ok]
    labels = [lab for lab, k in zip(labels, ok, strict=True) if k]
    group = group[ok] if group is not None else None
    d = ya - yb
    st_a = analyse_trend(t, ya, years, labels, a.per_year, group, alpha)
    st_b = analyse_trend(t, yb, years, labels, b.per_year, group, alpha)
    st_d = analyse_trend(t, d, years, labels, a.per_year, group, alpha)
    o = st_d.ols
    if o.testable and np.isfinite(o.se_adj):
        mdd = (sps.t.ppf(1 - alpha / 2, o.df) + sps.t.ppf(POWER, o.df)) * o.se_adj
    else:
        mdd = float("inf")
    corr = float(np.corrcoef(ya - ya.mean(), yb - yb.mean())[0, 1]) if ya.size > 2 else float("nan")
    opposite = bool(
        st_a.significant and st_b.significant and np.sign(st_a.sen.slope) != np.sign(st_b.sen.slope)
    )
    return {
        "n": int(d.size),
        "labels": labels,
        "t": t.tolist(),
        "a": ya.tolist(),
        "b": yb.tolist(),
        "diff": d.tolist(),
        "correlation": corr,
        "stats_a": st_a.to_dict(),
        "stats_b": st_b.to_dict(),
        "stats_diff": st_d.to_dict(),
        "difference": {
            "slope_per_decade": st_d.sen.slope * 10,
            "ci_low_per_decade": st_d.sen.ci_low * 10,
            "ci_high_per_decade": st_d.sen.ci_high * 10,
            "ols_slope_per_decade": o.slope * 10,
            "p": max(st_d.mk.p, o.p),
            "p_mk": st_d.mk.p,
            "p_ols": o.p,
            "significant": st_d.significant,
            "min_detectable_per_decade": float(mdd * 10),
        },
        "opposite": opposite,
    }
