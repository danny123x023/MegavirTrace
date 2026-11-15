"""Climate projections beside the observed trend (FR15): NASA NEX-GDDP-CMIP6.

NEX-GDDP-CMIP6 holds bias-corrected, downscaled (0.25°) daily projections from CMIP6 models.
For a region we take a small, documented sample:

* 5 models with a wide spread of climate sensitivity (ACCESS-CM2, CESM2, MIROC6,
  MPI-ESM1-2-HR, UKESM1-0-LL);
* baseline years 1995, 2000, 2005, 2010 from each model's historical run;
* sample years 2030, 2050, 2070, 2090 under SSP2-4.5 (middle path) and SSP5-8.5 (very high
  emissions).

Each file is subset on NASA's NCCS THREDDS server (NetCDF Subset Service) to the region's box
and averaged over the box and the year.  Each model's change is measured from its own baseline,
which removes model biases; the observed series is shown as its change from the same years.

This is context, not a result: projections are what models simulate under assumed emissions,
not forecasts, and they are never part of MegavirTrace's trend tests.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import h5py
import httpx
import numpy as np

THREDDS = "https://ds.nccs.nasa.gov/thredds"
ROOT = "AMES/NEX/GDDP-CMIP6"
MODELS = ["ACCESS-CM2", "CESM2", "MIROC6", "MPI-ESM1-2-HR", "UKESM1-0-LL"]
SCENARIOS = {"ssp245": "SSP2-4.5 (middle path)", "ssp585": "SSP5-8.5 (very high emissions)"}
BASELINE_YEARS = [1995, 2000, 2005, 2010]
SAMPLE_YEARS = [2030, 2050, 2070, 2090]
MAX_SPAN_DEG = 20.0
WORKERS = 5
USER_AGENT = "MegavirTrace/0.1 (NASA Space Apps open-source project)"

# MegavirTrace variable -> (CMIP6 variable, conversion of a daily-mean array to our yearly units)
PAIRINGS = {
    "air_temp": ("tas", "°C", lambda a: a - 273.15),
    "temp_change": ("tas", "°C", lambda a: a - 273.15),
    "daily_high": ("tasmax", "°C", lambda a: a - 273.15),
    "nightly_low": ("tasmin", "°C", lambda a: a - 273.15),
    "rainfall": ("pr", "mm/year", lambda a: a * 86400.0 * 365.25),  # kg/m2/s -> mm/year
}

CAVEATS = [
    "Projections are what climate models simulate if emissions follow an assumed path; they are not forecasts.",
    "Five models and four sample years per scenario: a single year includes natural ups and downs, so read the ranges, not single values.",
    "Each model's change is measured from its own baseline (the years 1995, 2000, 2005 and 2010); the observed line is the change from the observed mean over the baseline years the record has.",
    "The projections are yearly means of the region's box, so the observed line is drawn only for yearly values.",
    "Projections are shown as context only; MegavirTrace's trend tests use observations alone.",
]
BASELINE_SPAN = (1995, 2010)
MIN_OBSERVED_BASELINE_YEARS = 4


class ProjectionError(RuntimeError):
    pass


# --------------------------------------------------------------------------------------
# THREDDS catalog and subsets
# --------------------------------------------------------------------------------------

_catalog_cache: dict[str, str] = {}
_cache_lock = threading.Lock()


def _get(client: httpx.Client, url: str, params: dict | None = None, retries: int = 3) -> httpx.Response:
    for attempt in range(retries):
        try:
            r = client.get(url, params=params)
            if r.status_code == 200:
                return r
        except httpx.HTTPError:
            pass
        time.sleep(2 * (attempt + 1))
    raise ProjectionError(f"NCCS THREDDS did not answer for {url.split('/thredds/')[-1][:80]}")


def _member(client: httpx.Client, model: str, scenario: str) -> str:
    key = f"{model}/{scenario}"
    with _cache_lock:
        if key in _catalog_cache:
            return _catalog_cache[key]
    xml = _get(client, f"{THREDDS}/catalog/{ROOT}/{model}/{scenario}/catalog.xml").text
    m = re.search(r'xlink:title="(r\d+i\d+p\d+f\d+)"', xml)
    if not m:
        raise ProjectionError(f"no ensemble member for {model} {scenario}")
    with _cache_lock:
        _catalog_cache[key] = m.group(1)
    return m.group(1)


def _dataset_path(client: httpx.Client, model: str, scenario: str, var: str, year: int) -> str:
    member = _member(client, model, scenario)
    key = f"{model}/{scenario}/{member}/{var}"
    with _cache_lock:
        listing = _catalog_cache.get(key)
    if listing is None:
        listing = _get(client, f"{THREDDS}/catalog/{ROOT}/{model}/{scenario}/{member}/{var}/catalog.xml").text
        with _cache_lock:
            _catalog_cache[key] = listing
    # prefer the newest version of the file for this year (v2.0 over v1.1, ...)
    ids = re.findall(
        rf'ID="({re.escape(ROOT)}/{re.escape(model)}/{scenario}/{member}/{var}/[^"]*_{year}(?:_v[\d.]+)?\.nc)"',
        listing,
    )
    if not ids:
        raise ProjectionError(f"no {var} file for {model} {scenario} {year}")
    return sorted(ids)[-1]


def _region_mean(nc_bytes: bytes, var: str) -> float:
    with h5py.File(io.BytesIO(nc_bytes), "r") as f:
        a = np.asarray(f[var][()], float)
        lat = np.asarray(f["lat"][()], float)
        fill = f[var].attrs.get("_FillValue")
    if fill is not None:
        a[np.isclose(a, float(np.ravel(fill)[0]))] = np.nan
    a[np.abs(a) > 1e19] = np.nan
    w = np.cos(np.deg2rad(lat))[None, :, None] * np.ones_like(a)
    ok = np.isfinite(a)
    if not ok.any():
        raise ProjectionError("the subset holds no values for this region")
    return float(np.sum(np.where(ok, a, 0) * w) / np.sum(np.where(ok, w, 0)))


def annual_region_value(
    client: httpx.Client, model: str, scenario: str, var: str, year: int, bbox: list[float]
) -> float:
    path = _dataset_path(client, model, scenario, var, year)
    w, s, e, n = bbox
    params = {
        "var": var,
        "north": n,
        "south": s,
        "west": w,
        "east": e,
        "horizStride": 1,
        "temporal": "all",
        "accept": "netcdf4",
    }
    r = _get(client, f"{THREDDS}/ncss/grid/{path}", params)
    return _region_mean(r.content, var)


# --------------------------------------------------------------------------------------
# Jobs (background, cached in PostgreSQL)
# --------------------------------------------------------------------------------------

JOBS_SQL = """CREATE TABLE IF NOT EXISTS projection_job (
    key TEXT PRIMARY KEY, status TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL DEFAULT 0,
    result JSONB, error TEXT, updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"""


def job_key(var: str, region: dict) -> str:
    """The model results depend only on the variable and the region's box (the observed line is
    added when a page asks, from that page's own analysis)."""
    cmip_var = PAIRINGS[var][0]
    return hashlib.sha256(
        json.dumps(
            [cmip_var, var, region.get("id"), region["bbox"], MODELS, SAMPLE_YEARS, BASELINE_YEARS]
        ).encode()
    ).hexdigest()[:32]


def get_job(conn, key: str) -> dict | None:
    conn.execute(JOBS_SQL)
    r = conn.execute(
        "SELECT status, done, total, result, error, updated_at FROM projection_job WHERE key = %s", (key,)
    ).fetchone()
    return dict(r) if r else None


def _set(conn, key: str, **fields) -> None:
    cols = ", ".join(f"{k} = %({k})s" for k in fields)
    conn.execute(
        f"UPDATE projection_job SET {cols}, updated_at = now() WHERE key = %(key)s", {**fields, "key": key}
    )
    conn.commit()


def check_region(analysis: dict) -> tuple[str, dict]:
    var = analysis["variable"]["id"]
    if var not in PAIRINGS:
        raise ProjectionError(
            f"No NEX-GDDP-CMIP6 variable is paired with {analysis['variable']['name'].lower()}."
        )
    region = analysis["region"]
    w, s, e, n = region["bbox"]
    span_lon = (e - w) if e >= w else (e + 360 - w)
    if span_lon > MAX_SPAN_DEG or (n - s) > MAX_SPAN_DEG:
        raise ProjectionError(
            f"Projections are computed for regions up to {MAX_SPAN_DEG:g}° across; choose a smaller place."
        )
    if e < w:
        raise ProjectionError("Projections are not available yet for regions that cross the dateline.")
    return var, region


def start_job(connect, analysis: dict, values=None) -> dict:
    """Start (or reuse) the background computation for the analysis's variable and region."""
    values = values or annual_region_value
    var, region = check_region(analysis)
    key = job_key(var, region)
    with connect() as conn:
        job = get_job(conn, key)
        stale = (
            job
            and job["status"] == "running"
            and (dt.datetime.now(dt.UTC) - job["updated_at"]).total_seconds() > 600
        )
        if job and job["status"] in ("running", "done") and not stale:
            return {"key": key, **{k: job[k] for k in ("status", "done", "total")}}
        tasks = [(m, "historical", y) for m in MODELS for y in BASELINE_YEARS] + [
            (m, sc, y) for sc in SCENARIOS for m in MODELS for y in SAMPLE_YEARS
        ]
        conn.execute(
            """INSERT INTO projection_job (key, status, done, total) VALUES (%s, 'running', 0, %s)
               ON CONFLICT (key) DO UPDATE SET status = 'running', done = 0, total = EXCLUDED.total, error = NULL, result = NULL, updated_at = now()""",
            (key, len(tasks)),
        )
        conn.commit()
    threading.Thread(target=_run, args=(connect, key, var, region, tasks, values), daemon=True).start()
    return {"key": key, "status": "running", "done": 0, "total": len(tasks)}


def _run(connect, key, var, region, tasks, values) -> None:
    cmip_var, units, convert = PAIRINGS[var]
    got: dict[tuple[str, str, int], float] = {}
    try:
        with httpx.Client(timeout=300, headers={"User-Agent": USER_AGENT}) as client:
            with ThreadPoolExecutor(WORKERS) as pool:
                futures = {
                    pool.submit(values, client, m, sc, cmip_var, y, region["bbox"]): (m, sc, y)
                    for m, sc, y in tasks
                }
                for k, fut in enumerate(as_completed(futures), start=1):
                    m, sc, y = futures[fut]
                    try:
                        got[(m, sc, y)] = float(convert(np.asarray(fut.result())))
                    except ProjectionError:
                        pass  # a missing file for one model-year leaves a gap, not a failure
                    if k % 5 == 0 or k == len(tasks):
                        with connect() as conn:
                            _set(conn, key, done=k)
        result = summarise(got, var, units)
        with connect() as conn:
            _set(conn, key, status="done", result=json.dumps(result))
    except Exception as e:  # noqa: BLE001 - report the failure to the page
        with connect() as conn:
            _set(conn, key, status="error", error=str(e)[:300])


def observed_change(series: dict, var: str) -> tuple[dict | None, str | None]:
    """The observed yearly values as change from their mean over the baseline period.

    Drawn only for yearly values (the projections are yearly means).  The baseline is the mean of
    every observed year in 1995–2010, at least four of them: IMERG rainfall starts in mid-2000, so
    its baseline is 2001–2010 rather than two single years.  Returns (line, note).
    """
    if series.get("mode") != "annual":
        return None, "The observed line is drawn with yearly values only, because the projections are yearly means."
    tested = series.get("tested") or series
    t = np.array([np.nan if x is None else x for x in tested["t"]], float)
    v = np.array([np.nan if x is None else x for x in tested["values"]], float)
    years = np.floor(t)
    inb = (years >= BASELINE_SPAN[0]) & (years <= BASELINE_SPAN[1]) & np.isfinite(v)
    if inb.sum() < MIN_OBSERVED_BASELINE_YEARS:
        return None, (
            f"The observed record has fewer than {MIN_OBSERVED_BASELINE_YEARS} years in "
            f"{BASELINE_SPAN[0]}–{BASELINE_SPAN[1]}, the models' baseline period, so no observed line is drawn."
        )
    b = float(v[inb].mean())
    ch = (v - b) if not rainfall_relative(var) else 100.0 * (v - b) / b
    first, last = int(years[inb].min()), int(years[inb].max())
    line = {
        "t": [None if not np.isfinite(x) else float(x) for x in t],
        "change": [None if not np.isfinite(x) else float(x) for x in ch],
        "labels": list(tested["labels"]),
        "baseline": [first, last],
        "baseline_years": int(inb.sum()),
    }
    return line, f"Observed change from its {first}–{last} mean ({int(inb.sum())} years)."


def summarise(got: dict, var: str, units: str, observed: dict | None = None) -> dict:
    """Each model's change from its own baseline; ensemble median and range per scenario and year.

    ``observed`` (a series with mode, labels, t and values) adds the observed line; the stored job
    result leaves it out, and the API adds it from the page's own analysis.
    """
    baselines = {}
    for m in MODELS:
        vals = [got[(m, "historical", y)] for y in BASELINE_YEARS if (m, "historical", y) in got]
        if len(vals) >= 2:
            baselines[m] = float(np.mean(vals))
    scen = {}
    for sc in SCENARIOS:
        med, lo, hi, n = [], [], [], []
        for y in SAMPLE_YEARS:
            ch = [got[(m, sc, y)] - baselines[m] for m in baselines if (m, sc, y) in got]
            if rainfall_relative(var):
                ch = [
                    100.0 * c / baselines[m]
                    for c, m in zip(ch, [m for m in baselines if (m, sc, y) in got], strict=True)
                ]
            med.append(float(np.median(ch)) if ch else None)
            lo.append(float(np.min(ch)) if ch else None)
            hi.append(float(np.max(ch)) if ch else None)
            n.append(len(ch))
        scen[sc] = {"label": SCENARIOS[sc], "median": med, "min": lo, "max": hi, "models": n}
    obs, note = observed_change(observed, var) if observed else (None, None)
    return {
        "variable": var,
        "units": "%" if rainfall_relative(var) else units,
        "change_kind": "percent" if rainfall_relative(var) else "absolute",
        "models_used": sorted(baselines),
        "baseline_years": BASELINE_YEARS,
        "years": SAMPLE_YEARS,
        "scenarios": scen,
        "observed": obs,
        "observed_note": note,
        "caveats": CAVEATS,
        "source": "NASA NEX-GDDP-CMIP6 (NASA Earth Exchange Global Daily Downscaled Projections, CMIP6), via NASA NCCS THREDDS",
    }


def rainfall_relative(var: str) -> bool:
    return var == "rainfall"
