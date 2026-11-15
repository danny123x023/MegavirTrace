"""From a monthly grid to the regional series the trend tests run on.

Months are stored as an absolute index ``year * 12 + (month - 1)``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

SEASONS: dict[str, tuple[int, int, int]] = {
    "DJF": (12, 1, 2),
    "MAM": (3, 4, 5),
    "JJA": (6, 7, 8),
    "SON": (9, 10, 11),
}
MODES = ("annual", "season", "monthly", "raw")
MIN_MONTHS_PER_YEAR = 10  # of 12; with fewer calendar months observed here, the same share of them
MIN_CALENDAR_MONTHS = 3  # a "year" needs at least this many calendar months that are ever observed
MIN_COVERAGE = 0.5  # a month counts only if at least half the region has data
MONTH_ABBR = {
    "en": ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
    "es": ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"),
}


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


def region_mean(
    cube: np.ndarray, weights: np.ndarray, months: np.ndarray | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Area-weighted mean per month and the share of the region's weight that had data.

    cube: (n_months, ...cells) with NaN for missing; weights: the cells' shape, already including
    cos(latitude), the fraction of each cell inside the region and the variable's land/sea mask.

    With ``months`` (the absolute month of each row) the mean is formed from anomalies, as for
    GISTEMP and HadCRUT (Hansen & Lebedeff 1987; Jones et al. 1999): each cell's departure from
    its own mean for that calendar month is averaged over the cells with data, and the weighted
    mean of the cells' calendar-month means is added back.  A change in which part of the region
    has data (clouds, polar night, a new sensor) then no longer shows up as a trend.  Where every
    cell has data the result equals the plain weighted mean.
    """
    w = np.asarray(weights, float).ravel()
    cube = np.asarray(cube)
    cube = cube.reshape(cube.shape[0], -1)
    total = float(w.sum())
    if total <= 0:
        raise ValueError("region has no valid cells for this variable")
    n_t = cube.shape[0]
    # a few months at a time: the whole Earth at 0.5° is 259,200 cells, too many for full copies
    step = max(1, 8_000_000 // max(1, cube.shape[1]))
    clim = None
    if months is not None:
        cal = np.asarray(months, int) % 12
        sums = np.zeros((12, cube.shape[1]))
        counts = np.zeros((12, cube.shape[1]))
        for t0 in range(0, n_t, step):
            block = np.asarray(cube[t0 : t0 + step], float)
            valid = np.isfinite(block)
            for m in np.unique(cal[t0 : t0 + step]):
                rows = cal[t0 : t0 + step] == m
                sums[m] += np.where(valid[rows], block[rows], 0.0).sum(axis=0)
                counts[m] += valid[rows].sum(axis=0)
        with np.errstate(invalid="ignore", divide="ignore"):
            clim = sums / counts  # each cell's mean for each calendar month (NaN: never observed)
        has = np.isfinite(clim)
        region_clim = np.full(12, np.nan)
        for m in range(12):
            wm = w[has[m]]
            if wm.sum() > 0:
                region_clim[m] = float(clim[m, has[m]] @ wm / wm.sum())
    num = np.zeros(n_t)
    sw = np.zeros(n_t)
    for t0 in range(0, n_t, step):
        block = np.asarray(cube[t0 : t0 + step], float)
        if clim is not None:
            block = block - clim[cal[t0 : t0 + step]]
        valid = np.isfinite(block)
        num[t0 : t0 + step] = np.where(valid, block, 0.0) @ w
        sw[t0 : t0 + step] = valid @ w
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = num / sw
    if clim is not None:
        mean = mean + region_clim[cal]
    mean[sw == 0] = np.nan
    return mean, sw / total


# --------------------------------------------------------------------------------------
# Series for the tests
# --------------------------------------------------------------------------------------


@dataclass
class Series:
    mode: str
    t: np.ndarray  # decimal years of the values the tests use
    y: np.ndarray  # values the tests use
    years: np.ndarray  # the year each value belongs to (for leave-one-year-out)
    labels: list[str]
    per_year: int
    group: np.ndarray | None  # calendar month for the seasonal test, else None
    season: str | None
    plot_y: np.ndarray  # values shown on the chart, at chart_t (raw months in "raw" mode)
    climatology: np.ndarray  # 12 monthly means over the chosen years
    chart_t: np.ndarray | None = None  # the chart's time axis (months in monthly and raw modes)
    chart_labels: list[str] | None = None
    months_used: tuple[int, ...] = tuple(range(1, 13))  # calendar months a year is built from

    def __post_init__(self) -> None:
        if self.chart_t is None:
            self.chart_t = self.t
        if self.chart_labels is None:
            self.chart_labels = self.labels

    def __len__(self) -> int:
        return int(self.y.size)


def months_phrase(months: tuple[int, ...], lang: str = "en") -> str:
    """'Apr–Sep' for a run of calendar months (wrapping over December), else 'Jan, Mar, Jul'."""
    abbr = MONTH_ABBR.get(lang, MONTH_ABBR["en"])
    ms = sorted(months)
    k = len(ms)
    for start in ms:  # a contiguous run, possibly across the new year
        run = [(start - 1 + i) % 12 + 1 for i in range(k)]
        if sorted(run) == ms:
            return f"{abbr[run[0] - 1]}–{abbr[run[-1] - 1]}"
    return ", ".join(abbr[m - 1] for m in ms)


def _climatology(years: np.ndarray, months: np.ndarray, values: np.ndarray) -> np.ndarray:
    clim = np.full(12, np.nan)
    for m in range(1, 13):
        sel = (months == m) & np.isfinite(values)
        if sel.any():
            clim[m - 1] = float(values[sel].mean())
    return clim


def _yearly(
    years: np.ndarray, months: np.ndarray, values: np.ndarray, clim: np.ndarray, agg: str, anomalies: bool
) -> tuple[list[float], list[float], list[int], list[str], tuple[int, ...]]:
    """One value per year: the climatology of the calendar months observed here plus the mean
    anomaly of the months present (``anomalies=True``: the mean anomaly alone).

    A year needs 10 of 12 months.  Where some calendar months never have data (polar night for
    ocean colour, winter for some satellites) a year is built from the months that do, and needs
    the same share of them (ceil(10/12 x k) of k).  ``agg="sum"`` gives the total over those
    months: 12 x the monthly mean when all 12 are observed.
    """
    observed = tuple(int(m) for m in np.flatnonzero(np.isfinite(clim)) + 1)
    k = len(observed)
    if k < MIN_CALENDAR_MONTHS:
        return [], [], [], [], observed
    need = math.ceil(MIN_MONTHS_PER_YEAR * k / 12 - 1e-9)
    anom = values - clim[months - 1]
    base = float(np.mean(clim[np.array(observed) - 1]))
    out_t, out_y, out_years, labels = [], [], [], []
    for yr in np.unique(years):
        sel = (years == yr) & np.isfinite(anom)
        if sel.sum() < need:
            continue
        v = float(anom[sel].mean())
        if not anomalies:
            v += base
            if agg == "sum":
                v *= k
        out_t.append(float(yr) + 0.5)
        out_y.append(v)
        out_years.append(int(yr))
        labels.append(str(int(yr)))
    return out_t, out_y, out_years, labels, observed


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
      Calendar months never observed here are left out of the year (see ``_yearly``).
    * season: all 3 months are needed; DJF belongs to the year of its January.
    * monthly: the chart shows each month minus that calendar month's mean over the chosen
      years.  The tests use the yearly means of those anomalies: neighbouring months, and the
      months of one El Niño year, are not independent, and a correction for one-month memory
      misses that (it gave 18–31 % false alarms with realistic year-to-year memory).
    * raw: the chart shows the raw months; the tests are those of the monthly mode.
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
        out_t, out_y, out_years, labels, used = _yearly(years, months, values, clim, agg, anomalies=False)
        y = np.array(out_y, float)
        return Series(
            mode,
            np.array(out_t, float),
            y,
            np.array(out_years, int),
            labels,
            1,
            None,
            None,
            y,
            clim,
            months_used=used,
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

    # the chart: monthly anomalies (raw months in "raw" mode); the tests: their yearly means
    ok = np.isfinite(values)
    anom = values - clim[months - 1]
    t = years + (months - 0.5) / 12.0
    chart_labels = [month_label(int(i)) for i in months_abs[ok]]
    plot = values[ok] if mode == "raw" else anom[ok]
    out_t, out_y, out_years, labels, used = _yearly(years, months, values, clim, agg, anomalies=True)
    return Series(
        mode,
        np.array(out_t, float),
        np.array(out_y, float),
        np.array(out_years, int),
        labels,
        1,
        None,
        None,
        plot,
        clim,
        chart_t=t[ok],
        chart_labels=chart_labels,
        months_used=used,
    )


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
    agg: str = "mean",
) -> tuple[np.ndarray, np.ndarray]:
    """Yearly (or seasonal) values for every cell at once, for the cell map.

    cube: (n_months, n_cells).  Same rules as ``build_series``: a year needs 10 of 12 months
    (or the same share of the calendar months observed in that cell), a season all 3.
    ``agg="sum"`` gives totals (over the observed months of a year, or the 3 months of a
    season).  Monthly and raw modes: pass mode="monthly" for the yearly mean anomaly, which
    is what the regional test of those modes uses.  Returns (t, values[n_years, n_cells]).
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
            if agg == "sum":
                v = v * 3.0
            out_t.append(yr + centre)
            rows.append(v)
    else:
        anomalies = mode in ("monthly", "raw")
        clim = np.full((12, X.shape[1]), np.nan)
        with np.errstate(all="ignore"):
            for m in range(1, 13):
                sel = months == m
                if sel.any():
                    clim[m - 1] = np.nanmean(X[sel], axis=0)
            anom = X - clim[months - 1]
            k = np.isfinite(clim).sum(axis=0)  # calendar months observed in each cell
            need = np.ceil(MIN_MONTHS_PER_YEAR * k / 12 - 1e-9)
            base = np.nanmean(clim, axis=0)  # mean over the observed calendar months
            for yr in np.unique(sy):
                sel = sy == yr
                block = anom[sel]
                v = np.nanmean(block, axis=0)
                if not anomalies:
                    v = base + v
                    if agg == "sum":
                        v = v * k
                ok = (np.isfinite(block).sum(0) >= need) & (k >= MIN_CALENDAR_MONTHS)
                out_t.append(yr + 0.5)
                rows.append(np.where(ok, v, np.nan))
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
