"""The analysis service: region + variable -> series, statistics, verdict, cell map.

Used by the HTTP API, the AI tools and the exports, so every number has one source.
Results are stored under a fingerprint of (request, data versions, engine version) and
reused: statistics are computed once per data version.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import dataclass

import numpy as np

from megavir.catalog import DATASETS, VARIABLES, get_variable, series_units
from megavir.engine.aggregate import (
    MIN_CALENDAR_MONTHS,
    MIN_COVERAGE,
    MIN_MONTHS_PER_YEAR,
    build_series,
    month_label,
    month_zscore,
    per_cell_values,
    region_mean,
)
from megavir.engine.cellmap import block_size, cell_trends, merge_blocks
from megavir.engine.compare import compare_series
from megavir.engine.stats import MIN_POINTS, NotEnoughData, analyse_trend
from megavir.engine.verdict import LANGUAGES, compare_verdict, trend_verdict
from megavir.places.geometry import apply_domain, cells_for
from megavir.store import GridSpec, Version, active_versions, read_cells, read_land_mask

ENGINE_VERSION = "2026.11-11"
MAX_MAP_CELLS = 40_000  # mapped cell by cell up to this many
MAP_TARGET_CELLS = 20_000  # bigger regions: cells merged into blocks, at most this many


class AnalysisError(ValueError):
    """A problem the visitor can fix (no data for this place, bad request, ...)."""


# --------------------------------------------------------------------------------------
# Places
# --------------------------------------------------------------------------------------


@dataclass
class Region:
    id: str | None
    name: str
    kind: str  # country | admin1 | city | preset | box
    bbox: list[float]
    geometry: dict | None
    context: str = ""

    def descriptor(self) -> dict:
        return {"id": self.id, "bbox": self.bbox, "geometry": self.geometry}

    def public(self, with_geometry: bool = True) -> dict:
        d = {"id": self.id, "name": self.name, "kind": self.kind, "bbox": self.bbox, "context": self.context}
        if with_geometry:
            d["geometry"] = self.geometry
        return d


def _box_name(b: list[float]) -> str:
    def ll(v, pos, neg):
        return f"{abs(v):g}°{pos if v >= 0 else neg}"

    return f"box {ll(b[1], 'N', 'S')}–{ll(b[3], 'N', 'S')}, {ll(b[0], 'E', 'W')}–{ll(b[2], 'E', 'W')}"


_THE_COUNTRY = re.compile(
    r"^(United |Republic|Dem\. |Democratic|Central African|Dominican Rep|Netherlands|Philippines|Bahamas|Gambia|Maldives|"
    r"Seychelles|Comoros|Solomon|Marshall|Cayman|Falkland|Faroe|Turks|British|U\.S\.|Vatican|Czech|Cook Is|N\. Mariana|"
    r"Northern Mariana|Virgin|Congo|Ivory Coast|Isle of Man|Gaza|West Bank)"
)
_THE_PRESET = re.compile(
    r"(Basin|Sea\b|Ocean|Gulf|Bay\b|Current|Plateau|Plain|Desert|Delta|Valley|Lakes|Tropics|Arctic|Sahel|Sahara|Himalaya|Alps|"
    r"Andes|Outback|Pampas|Cerrado|Pantanal|Mediterranean|Maghreb|Horn of|corridor|Steppe|steppe|Coast\b|coast|belt|Belt|region|"
    r"hole|Mojave|Highveld|Kalahari|Gobi|Atacama|monsoon|Niño|warm pool|Great Barrier|Coral Triangle|Bight|Prairies|"
    r"Ruhr|Peninsula|Archipelago|North Slope|Slope|savanna|forests|farmland|aquifer|icefields|glaciers|waters|lands|"
    r"Indo-Gangetic|Ganges|Loess|Northwest|Persian|Philippines|Maldives|Tuvalu|metropolitan|Corn Belt|Upwelling|upwelling)"
)


def in_phrase(name: str, kind: str, lang: str = "en") -> str:
    """How a place reads after "in": "the whole Earth", "the Amazon Basin", "the United States"."""
    if lang == "es":
        if kind == "city":
            return f"los alrededores de {name}"
        return "toda la Tierra" if name == "Whole Earth" else name
    if kind == "city":
        return f"the area around {name}"
    special = {
        "Whole Earth": "the whole Earth",
        "West Antarctica (Amundsen Sea sector)": "West Antarctica (Amundsen Sea sector)",
        "Northwest India (Punjab–Haryana–Rajasthan)": "northwest India (Punjab–Haryana–Rajasthan)",
        "Amazon 'arc of deforestation'": "the Amazon 'arc of deforestation'",
        "Tuvalu and Kiribati waters": "the waters of Tuvalu and Kiribati",
        "Maldives waters": "the waters of the Maldives",
    }
    if name in special:
        return special[name]
    if kind == "country" and _THE_COUNTRY.match(name):
        return "the " + name
    if (
        kind == "preset"
        and _THE_PRESET.search(name)
        and not name.startswith(("Lake ", "Greater ", "Western Europe", "Eastern Europe"))
    ):
        return "the " + name
    return name


def resolve_region(conn, spec: dict, lang: str = "en") -> Region:
    """spec: {"place": id} or {"bbox": [w, s, e, n], "name"?: str}."""
    if spec.get("place"):
        r = conn.execute(
            "SELECT id, name, kind, context, bbox, geometry FROM place WHERE id = %s", (spec["place"],)
        ).fetchone()
        if not r:
            raise AnalysisError(f"unknown place {spec['place']!r}")
        name = in_phrase(r["name"], r["kind"], lang)
        return Region(r["id"], name, r["kind"], list(r["bbox"]), r["geometry"], r["context"])
    b = spec.get("bbox")
    if not b or len(b) != 4:
        raise AnalysisError("a region needs a place id or a bbox [west, south, east, north]")
    w, s, e, n = (float(x) for x in b)
    if not (-180 <= w <= 180 and -180 <= e <= 180 and -90 <= s < n <= 90):
        raise AnalysisError("bbox must be [west, south, east, north] in degrees, south < north")
    bb = [round(w, 4), round(s, 4), round(e, 4), round(n, 4)]
    name = (spec.get("name") or "").strip()[:80] or _box_name(bb)
    return Region(None, name, "box", bb, None)


# --------------------------------------------------------------------------------------
# Regional monthly series
# --------------------------------------------------------------------------------------


@dataclass
class RegionalData:
    version: Version
    months: np.ndarray
    values: np.ndarray
    coverage: np.ndarray
    cells: object
    weights: np.ndarray
    cube: np.ndarray  # (n_months, n_cells) for the cell map


def region_cells(conn, var, v: Version, region: Region):
    """The grid cells of a region that count for a variable, with their weights in ``area``
    (cos(latitude) x share of the cell inside the region x the variable's land/sea mask)."""
    rc = cells_for(region.descriptor(), v.spec)
    if rc.size == 0:
        raise AnalysisError(_outside_message(var, v))
    land = None
    if var.domain != "all":
        got = read_land_mask(conn, v.spec.res)
        if got:
            g, lf = got
            land = (lf, v.spec.offset_in(g))
    weights = apply_domain(rc, var.domain, land[0] if land else None, land[1] if land else (0, 0))
    keep = weights > 0
    if not keep.any():
        where = "land" if var.domain == "land" else "sea"
        raise AnalysisError(
            f"{region.name} has no {where} cells, and {var.name.lower()} is measured only over {where}."
        )
    return type(rc)(rc.ii[keep], rc.jj[keep], rc.frac[keep], weights[keep], rc.lat[keep], rc.lon[keep])


# A region's monthly mean is kept once per data version: comparisons, scans and cases then reuse
# it instead of reading every cell again (the whole Earth at 0.5° is 259,200 cells, ~30 s).
SERIES_SQL = """
CREATE TABLE IF NOT EXISTS region_series (
    version_id INTEGER NOT NULL,
    region_key TEXT NOT NULL,          -- sha1 of the region's outline or box
    mean       DOUBLE PRECISION[] NOT NULL,
    coverage   DOUBLE PRECISION[] NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (version_id, region_key)
);
"""
_series_ready: set[str] = set()


def _series_table(conn) -> None:
    key = f"{conn.info.dbname}@{conn.info.host}:{conn.info.port}"
    if key not in _series_ready:
        conn.execute(SERIES_SQL)
        conn.commit()
        _series_ready.add(key)


SERIES_METHOD = "anomaly-mean-1"  # how region_series rows are formed: change it when region_mean changes


def region_key(region: Region) -> str:
    blob = {"region": region.descriptor(), "method": SERIES_METHOD}
    return hashlib.sha1(json.dumps(blob, sort_keys=True, default=str).encode()).hexdigest()


def regional_monthly(conn, var_id: str, region: Region, need_cells: bool = False) -> RegionalData:
    var = get_variable(var_id)
    versions = active_versions(conn)
    v = versions.get(var_id)
    if not v:
        raise AnalysisError(f"{var.name} is not loaded yet")
    _series_table(conn)
    key = region_key(region)
    if not need_cells:
        hit = conn.execute(
            "SELECT mean, coverage FROM region_series WHERE version_id = %s AND region_key = %s", (v.id, key)
        ).fetchone()
        if hit and len(hit["mean"]) == len(v.months):
            mean = np.array(hit["mean"], float)
            cov = np.array(hit["coverage"], float)
            return RegionalData(v, v.months, mean, cov, None, None, np.empty((0, 0)))
    sub = region_cells(conn, var, v, region)
    w = sub.area
    cube = read_cells(conn, v, sub.ii, sub.jj)
    if not np.isfinite(cube).any():
        raise AnalysisError(_outside_message(var, v))
    mean, cov = region_mean(cube, w, v.months)
    conn.execute(
        """INSERT INTO region_series (version_id, region_key, mean, coverage) VALUES (%s, %s, %s, %s)
           ON CONFLICT (version_id, region_key) DO UPDATE SET mean = EXCLUDED.mean, coverage = EXCLUDED.coverage""",
        (v.id, key, [float(x) for x in mean], [float(x) for x in cov]),
    )
    conn.commit()
    return RegionalData(v, v.months, mean, cov, sub, w, cube if need_cells else np.empty((0, 0)))


def _outside_message(var, v: Version) -> str:
    if v.kind in ("test", "synthetic"):
        b = v.to_public()["bbox"]
        return (
            f"{var.name} is loaded only as {v.kind} data for a small area "
            f"({b[1]:.1f}–{b[3]:.1f}°, {b[0]:.1f}–{b[2]:.1f}°). Choose a place inside it."
        )
    return f"There is no {var.name.lower()} data for this region."


# --------------------------------------------------------------------------------------
# Fingerprints and the result cache
# --------------------------------------------------------------------------------------


def fingerprint(kind: str, request: dict, version_ids: list[int]) -> str:
    blob = json.dumps({"k": kind, "r": request, "v": version_ids, "e": ENGINE_VERSION}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:32]


def cached(conn, fid: str) -> dict | None:
    r = conn.execute("SELECT result FROM analysis WHERE id = %s", (fid,)).fetchone()
    return r["result"] if r else None


def store(
    conn, fid: str, kind: str, request: dict, version_ids: list[int], result: dict, replace: bool = False
) -> None:
    conflict = "DO UPDATE SET result = EXCLUDED.result" if replace else "DO NOTHING"
    conn.execute(
        f"INSERT INTO analysis (id, kind, request, versions, result) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (id) {conflict}",
        (fid, kind, json.dumps(request), version_ids, json.dumps(result, allow_nan=False)),
    )
    conn.commit()


def get_report(conn, fid: str) -> dict | None:
    r = conn.execute(
        "SELECT kind, request, result, created_at FROM analysis WHERE id = %s", (fid,)
    ).fetchone()
    return dict(r) if r else None


def _nan_to_none(a) -> list:
    return [None if (x is None or not math.isfinite(float(x))) else float(x) for x in np.asarray(a, float)]


# --------------------------------------------------------------------------------------
# Trend for one region
# --------------------------------------------------------------------------------------


def normalise_request(req: dict) -> dict:
    var = req.get("variable")
    if var not in VARIABLES:
        raise AnalysisError(f"unknown variable {var!r}")
    mode = req.get("mode") or VARIABLES[var].default_mode
    if mode not in ("annual", "season", "monthly", "raw"):
        raise AnalysisError("mode must be annual, season, monthly or raw")
    season = req.get("season") if mode == "season" else None
    if mode == "season" and season not in ("DJF", "MAM", "JJA", "SON"):
        raise AnalysisError("season must be DJF, MAM, JJA or SON")
    lang = req.get("lang") or "en"
    if lang not in LANGUAGES:
        lang = "en"
    region = req.get("region") or {}
    region = (
        {"place": region["place"]}
        if region.get("place")
        else {
            "bbox": [round(float(x), 4) for x in (region.get("bbox") or [])],
            "name": (region.get("name") or "")[:80],
        }
    )
    sy, ey = req.get("start_year"), req.get("end_year")
    return {
        "variable": var,
        "region": region,
        "mode": mode,
        "season": season,
        "start_year": int(sy) if sy else None,
        "end_year": int(ey) if ey else None,
        "cell_map": bool(req.get("cell_map", True)),
        "lang": lang,
    }


def provenance(var_id: str, v: Version, fid: str) -> dict:
    var = VARIABLES[var_id]
    ds = DATASETS[var.dataset]
    return {
        "product": ds.product,
        "title": ds.title,
        "archive": ds.archive,
        "doi": ds.doi,
        "paper_doi": ds.paper_doi,
        "citation": ds.citation,
        "source_badge": var.source_badge,
        "grid": f"{v.spec.res:g}°",
        "data_version": v.id,
        "data_kind": v.kind,
        "data_created": str(v.created_at),
        "engine_version": ENGINE_VERSION,
        "fingerprint": fid,
    }


def run_trend(conn, raw_request: dict, use_cache: bool = True) -> dict:
    req = normalise_request(raw_request)
    versions = active_versions(conn)
    v = versions.get(req["variable"])
    if not v:
        raise AnalysisError(f"{VARIABLES[req['variable']].name} is not loaded yet")
    fid = fingerprint("trend", req, [v.id])
    hit = cached(conn, fid) if use_cache else None
    if hit and not _map_was_too_big(hit):
        return hit
    t0 = time.time()
    var = VARIABLES[req["variable"]]
    region = resolve_region(conn, req["region"], req["lang"])
    rd = regional_monthly(conn, req["variable"], region, need_cells=req["cell_map"])
    s = build_series(
        rd.months,
        rd.values,
        req["mode"],
        req["season"],
        req["start_year"],
        req["end_year"],
        var.agg,
        rd.coverage,
    )
    unit = series_units(var, req["mode"])
    try:
        st = analyse_trend(s.t, s.y, s.years, s.labels, s.per_year, s.group)
    except NotEnoughData as e:
        raise AnalysisError(not_enough_message(var, region.name, s, req, rd, str(e))) from None
    # lowest coverage among the months that actually entered the statistics
    used = (
        np.isin(rd.months, _months_used(rd.months, s))
        & np.isfinite(rd.values)
        & (rd.coverage >= MIN_COVERAGE)
    )
    min_cov = float(np.nanmin(rd.coverage[used])) if used.any() else None
    verdict = trend_verdict(
        st, var, region.name, unit, s.season, req["lang"], v.kind, min_cov, req["mode"], s.months_used
    )
    stats = st.to_dict()
    stats["per_decade"] = {
        "sen": st.sen.slope * 10,
        "sen_low": st.sen.ci_low * 10,
        "sen_high": st.sen.ci_high * 10,
        "ols": st.ols.slope * 10,
        "ols_low": st.ols.ci_low * 10,
        "ols_high": st.ols.ci_high * 10,
    }
    stats = _jsonable(stats)
    result = {
        "id": fid,
        "kind": "trend",
        "request": req,
        "variable": var.to_dict(),
        "region": region.public(),
        "units": unit,
        "series": {
            "mode": s.mode,
            "season": s.season,
            # the chart: months in monthly and raw modes, else the tested values themselves
            "labels": s.chart_labels,
            "t": _nan_to_none(s.chart_t),
            "values": _nan_to_none(s.plot_y),
            "plot_values": _nan_to_none(s.plot_y),
            "trend_line": _nan_to_none(st.sen.intercept + st.sen.slope * s.chart_t),
            "per_year": 12 if s.mode in ("monthly", "raw") else s.per_year,
            # the values the tests ran on (yearly means of the monthly anomalies in monthly modes)
            "tested": {"labels": s.labels, "t": _nan_to_none(s.t), "values": _nan_to_none(s.y)},
            "months_used": list(s.months_used),
        },
        "monthly": {
            "labels": [month_label(int(m)) for m in rd.months],
            "values": _nan_to_none(rd.values),
            "coverage": _nan_to_none(rd.coverage),
            "units": var.units,
        },
        "stats": stats,
        "verdict": verdict,
        "cell_map": _cell_map(rd, req, var) if req["cell_map"] else None,
        "data": v.to_public(),
        "provenance": provenance(req["variable"], v, fid),
        "compute_ms": None,
    }
    result["compute_ms"] = round((time.time() - t0) * 1000)
    store(conn, fid, "trend", req, [v.id], result, replace=hit is not None)
    return result


def not_enough_message(var, place: str, s, req: dict, rd: RegionalData, why: str) -> str:
    """Why a record cannot be tested, and what (if anything) would help."""
    head = f"Not enough data for {var.name.lower()} in {place}: {why}."
    if s.mode != "season" and len(s.months_used) < MIN_CALENDAR_MONTHS:
        n = len(s.months_used)
        return (
            f"{head} Only {n} calendar month{'s' if n != 1 else ''} ever "
            f"{'have' if n != 1 else 'has'} data covering at least half of this region, too few to form yearly values."
        )
    ok = np.isfinite(rd.values) & (rd.coverage >= MIN_COVERAGE)
    months = rd.months[ok]
    if req["start_year"]:
        months = months[months // 12 >= req["start_year"]]
    if req["end_year"]:
        months = months[months // 12 <= req["end_year"]]
    restricted = bool(req["start_year"] or req["end_year"])
    if months.size == 0:
        return f"{head} {'Try a longer period.' if restricted else 'No month has data covering at least half of the region.'}"
    k = len(s.months_used) if s.mode != "season" else 3
    need = 3 if s.mode == "season" else int(math.ceil(MIN_MONTHS_PER_YEAR * k / 12 - 1e-9))
    # how many years the span of the record could fill, even if every month had data
    first, last = int(months.min()), int(months.max())
    possible = sum(
        1
        for y in range(first // 12, last // 12 + 1)
        if min(last, y * 12 + 11) - max(first, y * 12) + 1 >= need
    )
    if possible < MIN_POINTS:
        if restricted:
            return f"{head} Try a longer period."
        return (
            f"{head} The record here runs from {month_label(first)} to {month_label(last)}, which holds only "
            f"{possible} year{'s' if possible != 1 else ''} with enough months; a trend test needs at least {MIN_POINTS}."
        )
    if s.mode == "season":
        return f"{head} Too few years have all three months of {s.season} with data covering at least half of the region."
    return (
        f"{head} Too few years have at least {need} of their {k} observed months with data covering at "
        "least half of the region."
    )


def _map_was_too_big(result: dict) -> bool:
    """Stored before big regions were mapped in blocks: compute again (with the map)."""
    cm = result.get("cell_map")
    return isinstance(cm, dict) and str(cm.get("skipped", "")).startswith("region too large")


def _months_used(months: np.ndarray, s) -> np.ndarray:
    years = np.unique(s.years)
    return months[np.isin(months // 12, years)]


def _jsonable(obj):
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj):
            return None
        if math.isinf(obj):
            return "inf" if obj > 0 else "-inf"
    if isinstance(obj, np.generic):
        return _jsonable(obj.item())
    return obj


CAVEATS = {
    "region": "Which cells pass depends on the region tested: the false-discovery control runs over this region's cells.",
    "view": "Which cells pass depends on the area in view: the false-discovery control runs over the cells shown.",
}


def _cell_map(rd: RegionalData, req: dict, var) -> dict | None:
    return cell_map_for(rd.cube, rd.months, rd.cells, rd.version.spec, req, var, "region")


def cell_map_for(cube: np.ndarray, months: np.ndarray, cells, spec, req: dict, var, scope: str) -> dict:
    """A trend for every cell, then false-discovery control over the cells mapped.

    Up to MAX_MAP_CELLS cells are mapped one by one.  Bigger regions (the whole Earth has 259,200
    cells at 0.5°) are mapped in k x k blocks of cells, so the whole region still gets a map;
    the page then asks for full detail of the area in view (run_cells) as the visitor zooms in.
    """
    n_cells = cube.shape[1]
    if n_cells < 2:
        return {"skipped": "the region covers a single grid cell"}
    k = 1 if n_cells <= MAX_MAP_CELLS else block_size(cells.ii, cells.jj, MAP_TARGET_CELLS)
    lat, lon, frac = cells.lat, cells.lon, cells.frac
    if k > 1:
        merged = merge_blocks(cube, cells.ii, cells.jj, cells.area, cells.frac, k)
        cube = merged["cube"]
        lat = spec.lat0 + spec.res * (merged["bi"] * k + (k - 1) / 2)
        lon = spec.lon0 + spec.res * (merged["bj"] * k + (k - 1) / 2)
        frac = merged["frac"]
    # the same values the regional test of each mode uses (yearly mean anomalies in monthly modes)
    mode = req["mode"]
    t, vals = per_cell_values(months, cube, mode, req["season"], req["start_year"], req["end_year"], var.agg)
    if t.size < MIN_POINTS:
        return {"skipped": "not enough years for a cell map"}
    res = cell_trends(t, vals)
    basis = {
        "annual": "yearly values",
        "season": f"{req['season']} values",
    }.get(mode, "yearly means of the monthly anomalies")
    return {
        "res": spec.res * k,
        "native_res": spec.res,
        "block": k,
        "scope": scope,
        "lat": _nan_to_none(lat),
        "lon": _nan_to_none(lon),
        "frac": _nan_to_none(frac),
        "slope_per_decade": _nan_to_none(res["slope"] * 10),
        "p": _nan_to_none(res["p"]),
        "q": _nan_to_none(res["q"]),
        "passes": [bool(x) for x in res["passes"]],
        "alpha_fdr": res["alpha_fdr"],
        "n_cells": int(cube.shape[1]),
        "n_pass": int(np.sum(res["passes"])),
        "n_raw_significant": int(np.sum(res["raw_significant"])),
        "basis": basis,
        "caveat": CAVEATS[scope],
    }


def _view_box(view) -> list[float]:
    if not view or len(view) != 4:
        raise AnalysisError("view must be [west, south, east, north]")
    w, so, e, n = (float(x) for x in view)
    w, e = max(-180.0, min(180.0, w)), max(-180.0, min(180.0, e))
    so, n = max(-90.0, min(90.0, so)), max(-90.0, min(90.0, n))
    if not so < n or w == e:
        raise AnalysisError("the view box is empty")
    return [round(w, 3), round(so, 3), round(e, 3), round(n, 3)]


def run_cells(conn, raw: dict, use_cache: bool = True) -> dict:
    """The cell map of the part of a region in view, at the finest resolution that fits.

    Reads only the tiles under the view.  The false-discovery control runs over the cells
    shown, so which cells pass can differ from the whole-region map (the result says so).
    """
    req = normalise_request({**raw, "cell_map": True})
    view = _view_box(raw.get("view"))
    v = active_versions(conn).get(req["variable"])
    if not v:
        raise AnalysisError(f"{VARIABLES[req['variable']].name} is not loaded yet")
    fid = fingerprint("cells", {**req, "view": view}, [v.id])
    if use_cache and (hit := cached(conn, fid)):
        return hit
    var = VARIABLES[req["variable"]]
    region = resolve_region(conn, req["region"], req["lang"])
    rc = region_cells(conn, var, v, region)
    w, so, e, n = view
    lon_in = (rc.lon >= w) & (rc.lon <= e) if w < e else (rc.lon >= w) | (rc.lon <= e)
    inside = lon_in & (rc.lat >= so) & (rc.lat <= n)
    if not inside.any():
        result = {"skipped": "no cells of the region in view", "view": view}
    else:
        sub = type(rc)(
            rc.ii[inside], rc.jj[inside], rc.frac[inside], rc.area[inside], rc.lat[inside], rc.lon[inside]
        )
        cube = read_cells(conn, v, sub.ii, sub.jj)
        result = {**cell_map_for(cube, v.months, sub, v.spec, req, var, "view"), "view": view}
    store(conn, fid, "cells", {**req, "view": view}, [v.id], result)
    return result


# --------------------------------------------------------------------------------------
# Compare two regions
# --------------------------------------------------------------------------------------


def run_compare(conn, raw: dict, use_cache: bool = True) -> dict:
    base = normalise_request({**raw, "region": raw.get("region_a"), "cell_map": False})
    rb = normalise_request({**raw, "region": raw.get("region_b"), "cell_map": False})["region"]
    req = {**base, "region_a": base.pop("region"), "region_b": rb}
    req.pop("cell_map", None)
    if req["mode"] == "raw":
        req["mode"] = "monthly"
    v = active_versions(conn).get(req["variable"])
    if not v:
        raise AnalysisError("variable not loaded")
    fid = fingerprint("compare", req, [v.id])
    if use_cache and (hit := cached(conn, fid)):
        return hit
    var = VARIABLES[req["variable"]]
    A = resolve_region(conn, req["region_a"], req["lang"])
    B = resolve_region(conn, req["region_b"], req["lang"])
    da = regional_monthly(conn, req["variable"], A)
    db = regional_monthly(conn, req["variable"], B)
    args = (req["mode"], req["season"], req["start_year"], req["end_year"], var.agg)
    sa = build_series(da.months, da.values, *args, coverage=da.coverage)
    sb = build_series(db.months, db.values, *args, coverage=db.coverage)
    unit = series_units(var, req["mode"])
    try:
        cmp = compare_series(sa, sb)
    except NotEnoughData as e:
        raise AnalysisError(f"Not enough overlapping data: {e}") from None
    verdict = compare_verdict(cmp, var, A.name, B.name, unit, req["lang"], v.kind)
    result = _jsonable(
        {
            "id": fid,
            "kind": "compare",
            "request": req,
            "variable": var.to_dict(),
            "region_a": A.public(),
            "region_b": B.public(),
            "units": unit,
            "comparison": cmp,
            "verdict": verdict,
            "data": v.to_public(),
            "provenance": provenance(req["variable"], v, fid),
        }
    )
    store(conn, fid, "compare", req, [v.id], result)
    return result


# --------------------------------------------------------------------------------------
# What is changing here? (all variables for one place, FDR across variables)
# --------------------------------------------------------------------------------------


def run_scan(conn, raw: dict) -> dict:
    from megavir.engine.cellmap import benjamini_hochberg

    region_spec = raw.get("region") or {}
    lang = raw.get("lang") or "en"
    versions = active_versions(conn)
    rows = []
    for var_id in VARIABLES:
        if var_id not in versions:
            continue
        try:
            r = run_trend(
                conn,
                {
                    "variable": var_id,
                    "region": region_spec,
                    "mode": VARIABLES[var_id].default_mode,
                    "cell_map": False,
                    "lang": lang,
                },
            )
        except AnalysisError as e:
            rows.append({"variable": var_id, "name": VARIABLES[var_id].local(lang)["name"], "error": str(e)})
            continue
        st = r["stats"]
        p_joint = max(st["mk"]["p"], st["ols"]["p"]) if st["agree"] and st["ols"]["testable"] else 1.0
        rows.append(
            {
                "variable": var_id,
                "name": VARIABLES[var_id].local(lang)["name"],
                "theme": VARIABLES[var_id].theme,
                "analysis_id": r["id"],
                "per_decade": st["per_decade"]["sen"],
                "units": r["units"],
                "direction": st["direction"],
                "significant": st["significant"],
                "p_joint": p_joint,
                "effect": st["effect_label"],
                "headline": r["verdict"]["headline"],
                "data_kind": r["data"]["kind"],
            }
        )
    ok = [r for r in rows if "p_joint" in r]
    q = benjamini_hochberg(np.array([r["p_joint"] for r in ok])) if ok else []
    for r, qq in zip(ok, q, strict=True):
        r["q"] = float(qq)
        r["passes_fdr"] = bool(r["significant"] and qq <= 0.05)
    ok.sort(key=lambda r: (not r["passes_fdr"], r["q"]))
    region = resolve_region(
        conn, {"place": region_spec["place"]} if region_spec.get("place") else region_spec
    )
    return {
        "region": region.public(with_geometry=False),
        "results": ok + [r for r in rows if "error" in r],
        "note": (
            "Control de Benjamini–Hochberg entre las variables evaluadas aquí (q ≤ 0,05), para que evaluar muchas "
            "variables no fabrique descubrimientos."
            if lang == "es"
            else "Benjamini–Hochberg control across the variables tested here (q ≤ 0.05), so testing many "
            "variables does not manufacture discoveries."
        ),
    }


# --------------------------------------------------------------------------------------
# Regions with opposite trends
# --------------------------------------------------------------------------------------


def run_opposites(conn, var_id: str, mode: str | None = None, max_pairs: int = 5, lang: str = "en") -> dict:
    """Preset regions whose trends point in opposite directions.

    About 137 regions are tested, so about 7 would pass at the 5 % level by chance alone: a region
    is listed only if its trend also passes Benjamini–Hochberg control across all the regions
    tested (q <= 0.05), as in the scan, and is robust.
    """
    from megavir.engine.cellmap import benjamini_hochberg
    from megavir.places.presets import PRESETS

    if var_id not in VARIABLES:
        raise AnalysisError("unknown variable")
    mode = mode or VARIABLES[var_id].default_mode
    tested = []
    for p in PRESETS:
        if p["id"] in ("globe",):
            continue
        try:
            r = run_trend(
                conn,
                {
                    "variable": var_id,
                    "region": {"place": f"preset:{p['id']}"},
                    "mode": mode,
                    "cell_map": False,
                    "lang": lang,
                },
            )
        except AnalysisError:
            continue
        st = r["stats"]
        p_joint = max(st["mk"]["p"], st["ols"]["p"]) if st["agree"] and st["ols"]["testable"] else 1.0
        tested.append((p, r, st, p_joint))
    q = benjamini_hochberg(np.array([t[3] for t in tested])) if tested else np.empty(0)
    rising, falling = [], []
    for (p, r, st, _), qq in zip(tested, q, strict=True):
        if not st["significant"] or st["robustness"]["fragile"] or not qq <= 0.05:
            continue
        item = {
            "place": f"preset:{p['id']}",
            "name": p["name"],
            "per_decade": st["per_decade"]["sen"],
            "q": float(qq),
            "analysis_id": r["id"],
        }
        (rising if st["direction"] == "rising" else falling).append(item)
    rising.sort(key=lambda x: -x["per_decade"])
    falling.sort(key=lambda x: x["per_decade"])
    pairs = []
    for a in rising[:max_pairs]:
        for b in falling[:max_pairs]:
            if len(pairs) >= max_pairs:
                break
            try:
                c = run_compare(
                    conn,
                    {
                        "variable": var_id,
                        "region_a": {"place": a["place"]},
                        "region_b": {"place": b["place"]},
                        "mode": mode,
                        "lang": lang,
                    },
                )
            except AnalysisError:
                continue
            if c["comparison"]["difference"]["significant"]:
                pairs.append(
                    {
                        "a": a,
                        "b": b,
                        "compare_id": c["id"],
                        "headline": c["verdict"]["headline"],
                        "difference_per_decade": c["comparison"]["difference"]["slope_per_decade"],
                    }
                )
    return {
        "variable": var_id,
        "rising": rising,
        "falling": falling,
        "pairs": pairs,
        "mode": mode,
        "regions_tested": len(tested),
        "note": (
            f"Solo se listan las tendencias robustas que siguen siendo significativas tras el control de falsos "
            f"descubrimientos entre las {len(tested)} regiones predefinidas evaluadas (Benjamini–Hochberg, q ≤ 0,05); "
            "después se prueba directamente la diferencia de cada par."
            if lang == "es"
            else f"Only robust trends that stay significant after false-discovery control across the {len(tested)} "
            "preset regions tested (Benjamini–Hochberg, q ≤ 0.05) are listed; each pair's difference is then tested "
            "directly."
        ),
    }


def month_detail(conn, var_id: str, region_spec: dict, year: int, month: int) -> dict:
    region = resolve_region(conn, region_spec)
    rd = regional_monthly(conn, var_id, region)
    z = month_zscore(rd.months, rd.values, year, month)
    if z is None:
        raise AnalysisError("no data for that month")
    return {
        "region": region.public(with_geometry=False),
        "variable": var_id,
        **z,
        "note": "Exploratory: how unusual one month was compared with the same month in other years.",
    }


# The landing page: what the site holds, and one live result (the whole Earth's surface temperature
# change, year by year).  Warmed by `precompute` in both languages.
LANDING_TREND = {"variable": "temp_change", "region": {"place": "preset:globe"}, "cell_map": False}
# The headline rate: warming is not a straight line since 1880 (about 0.08 °C per decade on average,
# about 0.2 since the mid-1970s), so the live result states the rate of the modern period and shows
# the whole record as context.  1975 is the start NASA uses for the recent rate.
LANDING_SINCE = 1975
LANDING_RECENT = {**LANDING_TREND, "start_year": LANDING_SINCE}


def landing_summary(conn, lang: str) -> dict:
    cat = catalog_with_status(conn)
    real = [v for v in cat["variables"] if (v.get("data") or {}).get("kind") == "real"]
    hero = None
    try:
        full = run_trend(conn, {**LANDING_TREND, "lang": lang})
        r = run_trend(conn, {**LANDING_RECENT, "lang": lang})
        if r["provenance"]["data_kind"] != "real":
            raise AnalysisError("the landing page shows real measurements only")
        s, st = full["series"], r["stats"]
        recent_line = dict(zip(r["series"]["labels"], r["series"]["trend_line"], strict=True))
        hero = {
            "analysis_id": r["id"],
            "variable": r["variable"],
            "region": r["region"]["name"],
            "units": r["units"],
            "labels": s["labels"],  # the whole record, for the chart and the stripes
            "values": s["values"],
            "trend_line": [recent_line.get(lab) for lab in s["labels"]],  # the recent trend only
            "since": LANDING_SINCE,
            "headline": r["verdict"]["headline"],
            "per_decade": st["per_decade"]["sen"],
            "significant": st["significant"],
            "full_since": int(full["stats"]["first"]),
            "full_per_decade": full["stats"]["per_decade"]["sen"],
            "product": r["provenance"]["product"],
            "doi": r["provenance"]["doi"],
            "last_month": r["data"]["last_month"],  # the last year may be partial
        }
    except (AnalysisError, KeyError):
        hero = None  # not loaded yet: the page shows the rest
    return {
        "variables": len(real),
        "themes": [t for t in cat["themes"] if any(v["theme"] == t for v in real)],
        "products": sorted({v["dataset_info"]["product"] for v in real}),
        "first_month": min((v["data"]["first_month"] for v in real), default=None),
        "last_month": max((v["data"]["last_month"] for v in real), default=None),
        "hero": hero,
    }


def catalog_with_status(conn) -> dict:
    from megavir.catalog import PLANNED_DATASETS, PLANNED_VARIABLES, THEMES

    versions = active_versions(conn)
    out = []
    for vid, var in VARIABLES.items():
        d = var.to_dict()
        ds = DATASETS[var.dataset]
        d["dataset_info"] = {
            k: getattr(ds, k)
            for k in (
                "product",
                "title",
                "archive",
                "doi",
                "paper_doi",
                "citation",
                "native_grid",
                "record_start",
                "cadence",
            )
        }
        v = versions.get(vid)
        d["data"] = v.to_public() if v else None
        out.append(d)
    return {
        "themes": THEMES,
        "variables": out,
        "planned": [
            {
                **p,
                "dataset_info": {
                    k: getattr(PLANNED_DATASETS[p["dataset"]], k) for k in ("product", "title", "doi")
                },
            }
            for p in PLANNED_VARIABLES
        ],
    }


def grid_spec_of(v: Version) -> GridSpec:
    return v.spec


# --------------------------------------------------------------------------------------
# Moves together (FR11)
# --------------------------------------------------------------------------------------


def run_related(conn, raw: dict, use_cache: bool = True) -> dict:
    from megavir.engine.related import lagged_relationship
    from megavir.engine.verdict import related_verdict

    va, vb = raw.get("variable_a"), raw.get("variable_b")
    if va not in VARIABLES or vb not in VARIABLES:
        raise AnalysisError("choose two known variables")
    if va == vb:
        raise AnalysisError("choose two different variables")
    max_lag = int(raw.get("max_lag") if raw.get("max_lag") is not None else 12)
    if not 0 <= max_lag <= 24:
        raise AnalysisError("the lag can be 0 to 24 months")
    region = raw.get("region") or {}
    region = (
        {"place": region["place"]}
        if region.get("place")
        else {
            "bbox": [round(float(x), 4) for x in (region.get("bbox") or [])],
            "name": (region.get("name") or "")[:80],
        }
    )
    lang = raw.get("lang") if raw.get("lang") in LANGUAGES else "en"
    req = {"variable_a": va, "variable_b": vb, "region": region, "max_lag": max_lag, "lang": lang}
    versions = active_versions(conn)
    if va not in versions or vb not in versions:
        raise AnalysisError("both variables must be loaded")
    ids = [versions[va].id, versions[vb].id]
    fid = fingerprint("related", req, ids)
    if use_cache and (hit := cached(conn, fid)):
        return hit
    reg = resolve_region(conn, region, lang)
    da = regional_monthly(conn, va, reg)
    db = regional_monthly(conn, vb, reg)
    months = np.union1d(da.months, db.months)
    a = np.full(months.size, np.nan)
    b = np.full(months.size, np.nan)
    a[np.searchsorted(months, da.months)] = np.where(da.coverage >= MIN_COVERAGE, da.values, np.nan)
    b[np.searchsorted(months, db.months)] = np.where(db.coverage >= MIN_COVERAGE, db.values, np.nan)
    rel = lagged_relationship(months, a, b, max_lag)
    if not rel.get("tested"):
        raise AnalysisError(
            f"Cannot compare {VARIABLES[va].name.lower()} and {VARIABLES[vb].name.lower()} here: {rel.get('reason')}."
        )
    kinds = {versions[va].kind, versions[vb].kind}
    kind = "synthetic" if "synthetic" in kinds else "test" if "test" in kinds else "real"
    verdict = related_verdict(
        rel, VARIABLES[va].local(lang)["name"], VARIABLES[vb].local(lang)["name"], reg.name, lang, kind
    )
    result = _jsonable(
        {
            "id": fid,
            "kind": "related",
            "request": req,
            "variable_a": VARIABLES[va].to_dict(),
            "variable_b": VARIABLES[vb].to_dict(),
            "region": reg.public(),
            "relationship": {**rel, "labels": [month_label(int(m)) for m in rel["months"]]},
            "verdict": verdict,
            "data_kind": kind,
            "provenance": {
                "a": provenance(va, versions[va], fid),
                "b": provenance(vb, versions[vb], fid),
            },
        }
    )
    store(conn, fid, "related", req, ids, result)
    return result
