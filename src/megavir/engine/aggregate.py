"""From a monthly grid to the regional series the trend tests run on.

Months are stored as an absolute index ``year * 12 + (month - 1)``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SEASONS: dict[str, tuple[int, int, int]] = {
    "DJF": (12, 1, 2),
    "MAM": (3, 4, 5),
    "JJA": (6, 7, 8),
    "SON": (9, 10, 11),
}
MODES = ("annual", "season", "monthly", "raw")
MIN_MONTHS_PER_YEAR = 10
MIN_COVERAGE = 0.5  # a month counts only if at least half the region has data


def month_index(year: int, month: int) -> int:
    return year * 12 + (month - 1)


def split_months(idx: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    idx = np.asarray(idx, int)
    return idx // 12, idx % 12 + 1


def month_label(idx: int) -> str:
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


# --------------------------------------------------------------------------------------
# Regional mean
# --------------------------------------------------------------------------------------


def region_mean(cube: np.ndarray, weights: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Area-weighted mean per month and the share of the region's weight that had data.

    cube: (n_months, ...cells) with NaN for missing; weights: the cells' shape, already including
    cos(latitude), the fraction of each cell inside the region and the variable's land/sea mask.
    """
    w = np.asarray(weights, float).ravel()
    cube = np.asarray(cube, float)
    cube = cube.reshape(cube.shape[0], -1)
    total = float(w.sum())
    if total <= 0:
        raise ValueError("region has no valid cells for this variable")
    valid = np.isfinite(cube)
    wv = np.where(valid, w[None], 0.0)
    sw = wv.sum(axis=1)
    vals = np.where(valid, cube, 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = (vals * wv).sum(axis=1) / sw
    mean[sw == 0] = np.nan
    return mean, sw / total


# --------------------------------------------------------------------------------------
# Series for the tests
# --------------------------------------------------------------------------------------


@dataclass
class Series:
    mode: str
    t: np.ndarray  # decimal years
    y: np.ndarray  # values the tests use
    years: np.ndarray  # the year each value belongs to (for leave-one-year-out)
    labels: list[str]
    per_year: int
    group: np.ndarray | None  # calendar month for the seasonal test, else None
    season: str | None
    plot_y: np.ndarray  # values shown on the chart (raw months in "raw" mode)
    climatology: np.ndarray  # 12 monthly means over the chosen years

    def __len__(self) -> int:
        return int(self.y.size)


def _climatology(years: np.ndarray, months: np.ndarray, values: np.ndarray) -> np.ndarray:
    clim = np.full(12, np.nan)
    for m in range(1, 13):
        sel = (months == m) & np.isfinite(values)
        if sel.any():
            clim[m - 1] = float(values[sel].mean())
    return clim


def build_series(
    months_abs: np.ndarray,
    values: np.ndarray,
    mode: str = "annual",
    season: str | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    agg: str = "mean",
    coverage: np.ndarray | None = None,
    min_coverage: float = MIN_COVERAGE,
) -> Series:
    """Turn a monthly regional series into yearly, seasonal or monthly-anomaly values.

    * annual: a year needs at least 10 of 12 months.  Its value is the mean of the 12-month
      climatology plus the mean anomaly of the months present, so a missing winter month does
      not bias the year.  ``agg="sum"`` reports the yearly total (12 x the monthly mean).
    * season: all 3 months are needed; DJF belongs to the year of its January.
    * monthly: each month minus that calendar month's mean over the chosen years; the
      seasonal Mann–Kendall test is used.
    * raw: the chart shows the raw months; the tests use the monthly anomalies.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    months_abs = np.asarray(months_abs, int)
    values = np.asarray(values, float).copy()
    if coverage is not None:
        values[np.asarray(coverage) < min_coverage] = np.nan
    years, months = split_months(months_abs)

    if mode == "season":
        if season not in SEASONS:
            raise ValueError(f"season must be one of {list(SEASONS)}")
        # DJF: December counts towards the following year
        season_year = np.where((months == 12) & (season == "DJF"), years + 1, years)
    else:
        season_year = years

    keep = np.ones(values.size, bool)
    if start_year is not None:
        keep &= season_year >= start_year
    if end_year is not None:
        keep &= season_year <= end_year
    months_abs, values, years, months, season_year = (
        months_abs[keep],
        values[keep],
        years[keep],
        months[keep],
        season_year[keep],
    )
    clim = _climatology(years, months, values)

    if mode == "annual":
        out_t, out_y, out_years, labels = [], [], [], []
        anom = values - clim[months - 1]
        clim_mean = float(np.nanmean(clim)) if np.isfinite(clim).all() else np.nan
        for yr in np.unique(years):
            sel = (years == yr) & np.isfinite(anom)
            if sel.sum() < MIN_MONTHS_PER_YEAR:
                continue
            v = clim_mean + float(anom[sel].mean())
            if agg == "sum":
                v *= 12.0
            out_t.append(yr + 0.5)
            out_y.append(v)
            out_years.append(yr)
            labels.append(str(int(yr)))
        y = np.array(out_y)
        return Series(
            mode, np.array(out_t, float), y, np.array(out_years, int), labels, 1, None, None, y, clim
        )

    if mode == "season":
        wanted = SEASONS[season]
        out_t, out_y, out_years, labels = [], [], [], []
        for yr in np.unique(season_year):
            vals = []
            for m in wanted:
                sel = (season_year == yr) & (months == m) & np.isfinite(values)
                if sel.any():
                    vals.append(float(values[sel][0]))
            if len(vals) < 3:
                continue
            v = float(np.sum(vals)) if agg == "sum" else float(np.mean(vals))
            centre = {"DJF": 0.08, "MAM": 0.33, "JJA": 0.58, "SON": 0.83}[season]
            out_t.append(yr + centre)
            out_y.append(v)
            out_years.append(yr)
            labels.append(f"{int(yr)} {season}")
        y = np.array(out_y)
        return Series(
            mode, np.array(out_t, float), y, np.array(out_years, int), labels, 1, None, season, y, clim
        )

    # monthly anomalies (and raw months for the chart)
    ok = np.isfinite(values)
    anom = values - clim[months - 1]
    t = years + (months - 0.5) / 12.0
    labels = [month_label(int(i)) for i in months_abs[ok]]
    plot = values[ok] if mode == "raw" else anom[ok]
    return Series(mode, t[ok], anom[ok], years[ok], labels, 12, months[ok], None, plot, clim)


def month_zscore(months_abs: np.ndarray, values: np.ndarray, year: int, month: int) -> dict | None:
    """How unusual one month is against the same calendar month in other years (exploratory)."""
    months_abs = np.asarray(months_abs, int)
    values = np.asarray(values, float)
    _, months = split_months(months_abs)
    same = (months == month) & np.isfinite(values)
    target = month_index(year, month)
    hit = np.flatnonzero(months_abs == target)
    if hit.size == 0 or not np.isfinite(values[hit[0]]) or same.sum() < 5:
        return None
    pool = values[same]
    v = float(values[hit[0]])
    sd = float(pool.std(ddof=1))
    rank_high = int(np.sum(pool > v)) + 1
    return {
        "month": month_label(target),
        "value": v,
        "mean": float(pool.mean()),
        "z": float((v - pool.mean()) / sd) if sd > 0 else 0.0,
        "rank_from_highest": rank_high,
        "of": int(pool.size),
    }


def per_cell_values(
    months_abs: np.ndarray,
    cube: np.ndarray,
    mode: str = "annual",
    season: str | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Yearly (or seasonal) values for every cell at once, for the cell map.

    cube: (n_months, n_cells).  Monthly and raw modes use yearly values.  Same rules as
    ``build_series``: a year needs 10 of 12 months, a season all 3.
    Returns (t, values[n_years, n_cells]).
    """
    months_abs = np.asarray(months_abs, int)
    X = np.asarray(cube, float)
    years, months = split_months(months_abs)
    if mode == "season" and season in SEASONS:
        sy = np.where((months == 12) & (season == "DJF"), years + 1, years)
        wanted = SEASONS[season]
        keep = np.isin(months, wanted)
    else:
        sy = years
        keep = np.ones(months.size, bool)
    if start_year is not None:
        keep &= sy >= start_year
    if end_year is not None:
        keep &= sy <= end_year
    X, sy, months = X[keep], sy[keep], months[keep]
    out_t, rows = [], []
    if mode == "season" and season in SEASONS:
        centre = {"DJF": 0.08, "MAM": 0.33, "JJA": 0.58, "SON": 0.83}[season]
        for yr in np.unique(sy):
            sel = sy == yr
            if sel.sum() < 3:
                continue
            block = X[sel]
            v = np.where(np.isfinite(block).sum(0) == 3, np.nanmean(block, axis=0), np.nan)
            out_t.append(yr + centre)
            rows.append(v)
    else:
        clim = np.full((12, X.shape[1]), np.nan)
        with np.errstate(all="ignore"):
            for m in range(1, 13):
                sel = months == m
                if sel.any():
                    clim[m - 1] = np.nanmean(X[sel], axis=0)
            anom = X - clim[months - 1]
            clim_mean = np.nanmean(clim, axis=0)
            for yr in np.unique(sy):
                sel = sy == yr
                block = anom[sel]
                v = np.where(
                    np.isfinite(block).sum(0) >= MIN_MONTHS_PER_YEAR,
                    clim_mean + np.nanmean(block, axis=0),
                    np.nan,
                )
                out_t.append(yr + 0.5)
                rows.append(v)
    if not rows:
        return np.empty(0), np.empty((0, X.shape[1]))
    return np.array(out_t, float), np.vstack(rows)


def per_cell_monthly_anomalies(
    months_abs: np.ndarray, cube: np.ndarray, start_year: int | None = None, end_year: int | None = None
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Monthly anomalies for every cell (each month minus that cell's mean for the calendar month).

    Returns (t, anomalies[n_months, n_cells], calendar month of each row); rows stay consecutive
    months so the lag-1 autocorrelation is one month apart.
    """
    months_abs = np.asarray(months_abs, int)
    X = np.asarray(cube, float)
    years, months = split_months(months_abs)
    keep = np.ones(months.size, bool)
    if start_year is not None:
        keep &= years >= start_year
    if end_year is not None:
        keep &= years <= end_year
    X, years, months = X[keep], years[keep], months[keep]
    anom = np.full_like(X, np.nan)
    with np.errstate(all="ignore"):
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            for m in range(1, 13):
                sel = months == m
                if sel.any():
                    anom[sel] = X[sel] - np.nanmean(X[sel], axis=0)
    return years + (months - 0.5) / 12.0, anom, months
