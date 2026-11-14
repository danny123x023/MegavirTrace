"""Ingest pipeline: download -> read -> harmonise -> validate -> versioned swap-in.

Two modes (see the design's "Test data first, full download after development"):

* ``test``: one ~5° x 5° test box, the most recent 10 years for monthly products and the
  most recent 12 months for daily and weekly ones.  Stored as kind='test' and always labelled.
* ``full``: the whole globe and the whole record; replaces the test version.

Both modes use the same code; only the box and the time range differ.  Raw files stay on
disk so an import can be rerun without downloading again.  Each run records time and size per
product (to plan the full download).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from megavir.catalog import DATASETS, VARIABLES
from megavir.store import GridSpec, read_mask, write_version

from . import download as dl
from .products import PRODUCTS, Product, gunzip, month_abs_from_iso, standard_fields
from .regrid import NativeGrid, Regridder
from .validate import validate_cube

log = logging.getLogger("megavir.ingest")

# About 5° x 5° on the US Gulf Coast: land (Louisiana, east Texas, Houston) and sea (Gulf of
# Mexico), so land-only and sea-only variables both have test cells.
TEST_BOX = (-95.0, 27.5, -90.0, 32.5)  # west, south, east, north
TEST_PAD = 1.0  # extra degrees fetched around the box so edge cells regrid conservatively


@dataclass
class RunReport:
    product: str
    mode: str
    files: int = 0
    bytes: int = 0
    download_s: float = 0.0
    process_s: float = 0.0
    versions: dict = field(default_factory=dict)
    skipped_files: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__


# --------------------------------------------------------------------------------------
# Time ranges
# --------------------------------------------------------------------------------------


def time_range(p: Product, mode: str, today: dt.date | None = None) -> tuple[str, str]:
    today = today or dt.date.today()
    if mode == "full":
        return f"{p.record_start}-01T00:00:00Z", f"{today.isoformat()}T23:59:59Z"
    if p.cadence == "monthly":
        start = dt.date(today.year - 10, today.month, 1)
    else:
        start = dt.date(today.year - 1, today.month, 1)
    return f"{start.isoformat()}T00:00:00Z", f"{today.isoformat()}T23:59:59Z"


def target_spec(p: Product, mode: str) -> GridSpec:
    g = GridSpec.global_grid(p.target_res)
    if mode == "test":
        w, s, e, n = TEST_BOX
        return g.window(s, n, w, e)
    return g


# --------------------------------------------------------------------------------------
# Accumulating fields into monthly cubes
# --------------------------------------------------------------------------------------


class MonthlyAccumulator:
    """Sums and counts per month and variable on the target grid."""

    def __init__(self, spec: GridSpec, variables: list[str], min_count: int):
        self.spec = spec
        self.vars = variables
        self.min_count = min_count
        self.sum: dict[tuple[str, int], np.ndarray] = {}
        self.cnt: dict[tuple[str, int], np.ndarray] = {}

    def add(self, var: str, month: int, field: np.ndarray) -> None:
        key = (var, month)
        ok = np.isfinite(field)
        if key not in self.sum:
            self.sum[key] = np.zeros(field.shape)
            self.cnt[key] = np.zeros(field.shape, np.int32)
        self.sum[key][ok] += field[ok]
        self.cnt[key][ok] += 1

    def cube(self, var: str) -> tuple[int, np.ndarray] | None:
        months = sorted(m for v, m in self.sum if v == var)
        if not months:
            return None
        m0, m1 = months[0], months[-1]
        out = np.full((m1 - m0 + 1, self.spec.ny, self.spec.nx), np.nan, np.float32)
        for m in months:
            s, c = self.sum[(var, m)], self.cnt[(var, m)]
            with np.errstate(invalid="ignore", divide="ignore"):
                out[m - m0] = np.where(c >= self.min_count, s / c, np.nan)
        return m0, out


# --------------------------------------------------------------------------------------
# OPeNDAP products
# --------------------------------------------------------------------------------------


def _index_range(coords: np.ndarray, lo: float, hi: float) -> tuple[int, int]:
    idx = np.flatnonzero((coords >= lo) & (coords <= hi))
    if idx.size == 0:
        raise ValueError("test box outside the product grid")
    return int(idx.min()), int(idx.max())


def _opendap_files(
    p: Product, mode: str, raw: Path, report: RunReport, limit: int | None
) -> list[tuple[int, Path, dict]]:
    start, end = time_range(p, mode)
    granules = dl.cmr_granules(p.concept_id, start, end)
    if limit:
        granules = granules[-limit:]
    if not granules:
        raise RuntimeError(f"no granules for {p.id} in {start}..{end}")
    session = dl.earthdata_session()
    folder = raw / p.id / mode
    folder.mkdir(parents=True, exist_ok=True)

    # resolve variable paths and dimension order once, from the newest granule's DMR
    meta_path = folder / "_dmr.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
    else:
        g0 = granules[-1]
        r = session.get(g0.opendap_url + ".dmr.xml", timeout=120)
        r.raise_for_status()
        vars_ = dl.parse_dmr(r.text)
        meta = {"vars": {}}
        for name in p.fields:
            v = dl.find_var(vars_, name)
            meta["vars"][name] = {"path": v.path, "dims": v.dims}
        dl.save_json(meta_path, meta)

    lats, lons = p.native_lats, p.native_lons
    ny, nx = lats.size, lons.size
    if mode == "test":
        w, s, e, n = TEST_BOX
        i0, i1 = _index_range(lats, s - TEST_PAD, n + TEST_PAD)
        j0, j1 = _index_range(lons, w - TEST_PAD, e + TEST_PAD)
    else:
        i0, i1, j0, j1 = 0, ny - 1, 0, nx - 1
    ranges = {ny: (i0, i1), nx: (j0, j1)}
    out = []
    for g in granules:
        if not g.opendap_url:
            report.skipped_files.append(g.ur)
            continue
        cons = [
            dl.slice_constraint(dl.DapVar(v["path"], [tuple(d) for d in v["dims"]]), ranges)
            for v in meta["vars"].values()
        ]
        url = dl.dap4_url(g.opendap_url, cons)
        dest = folder / (re.sub(r"[^0-9A-Za-z._-]", "_", g.name) + ".sub.nc4")
        info = dl.download(url, dest, session)
        report.files += 1
        report.bytes += info["bytes"]
        report.download_s += info["seconds"]
        dims = list(meta["vars"].values())[0]["dims"]
        lon_axis_first = [d[1] for d in dims if d[1] in (ny, nx)][:1] == [nx]
        out.append(
            (
                g.begin,
                dest,
                {"lats": lats[i0 : i1 + 1], "lons": lons[j0 : j1 + 1], "lon_first": lon_axis_first},
            )
        )
    return out


# --------------------------------------------------------------------------------------
# Public products
# --------------------------------------------------------------------------------------


def _resolve_grace_url() -> tuple[str, str]:
    import httpx

    page = httpx.get(
        "https://earth.gsfc.nasa.gov/geo/data/grace-mascons", timeout=60, follow_redirects=True
    ).text
    m = re.findall(r'href="([^"]*GSFC\.glb_\.[^"]*HALFDEGREE\.nc)"', page, flags=re.I)
    if not m:
        raise RuntimeError("could not find the GSFC mascon file link")
    href = m[0]
    url = href if href.startswith("http") else "https://earth.gsfc.nasa.gov" + href
    return url, url.split("/")[-1]


def _public_files(p: Product, mode: str, raw: Path, report: RunReport, limit: int | None) -> list[Path]:
    start, end = time_range(p, mode)
    y0, y1 = int(start[:4]), int(end[:4])
    urls = p.public_urls(mode, y0, y1)
    if urls and urls[0][1] == "__resolve__":
        urls = [_resolve_grace_url()]
    if limit:
        urls = urls[-limit:]
    session = dl.PublicSession()
    folder = raw / p.id  # shared by test and full: the full run reuses the test downloads
    paths = []
    for url, name in urls:
        dest = folder / name
        try:
            info = dl.download(url, dest, session)
        except Exception as e:  # noqa: BLE001 - e.g. months not yet published
            if "404" in str(e):
                report.skipped_files.append(name)
                continue
            raise
        report.files += 1
        report.bytes += info["bytes"]
        report.download_s += info["seconds"]
        paths.append(dest)
    return paths


def _read_public(p: Product, path: Path) -> list[tuple[int, dict, np.ndarray, np.ndarray]]:
    """[(month_abs, fields, lats, lons)] for a public file (GISTEMP, GRACE: many months; MiCASA: one)."""
    import xarray as xr

    if path.suffix == ".gz":
        path = gunzip(path)
    ds = xr.open_dataset(path, decode_times=True, mask_and_scale=True)
    try:
        latn = next(n for n in ("lat", "latitude") if n in ds.variables)
        lonn = next(n for n in ("lon", "longitude") if n in ds.variables)
        lats = ds[latn].values.astype(float)
        lons = ds[lonn].values.astype(float)
        out = []
        times = ds["time"].values if "time" in ds.dims else [None]
        for k, tv in enumerate(times):
            if tv is None:
                m = _month_from_name(path.name)
            else:
                ts = np.datetime64(tv, "D").astype(object)
                m = ts.year * 12 + ts.month - 1
            fields = {}
            for name in p.fields:
                da = ds[name]
                if "time" in da.dims:
                    da = da.isel(time=k)
                a = np.asarray(da.values, float)
                while a.ndim > 2:
                    a = a[0]
                if da.dims[-2:] == (lonn, latn):
                    a = a.T
                if p.valid_range:
                    lo, hi = p.valid_range
                    a[(a < lo) | (a > hi)] = np.nan
                fields[name] = a
            out.append((m, fields, lats, lons))
        return out
    finally:
        ds.close()


def _month_from_name(name: str) -> int:
    m = re.search(r"(\d{4})(\d{2})(?:\D|$)", name)
    if not m:
        raise ValueError(f"no YYYYMM in {name}")
    return int(m.group(1)) * 12 + int(m.group(2)) - 1


# --------------------------------------------------------------------------------------
# Run
# --------------------------------------------------------------------------------------


def _land_mask_for(conn, spec: GridSpec) -> np.ndarray | None:
    got = read_mask(conn, "land", spec.res)
    if not got:
        return None
    g, lf = got
    oi, oj = spec.offset_in(g)
    return lf[oi : oi + spec.ny, oj : oj + spec.nx]


def run(
    product_id: str, mode: str, conn, raw: Path, limit: int | None = None, activate: bool = True
) -> RunReport:
    if mode not in ("test", "full"):
        raise ValueError("mode must be 'test' or 'full'")
    p = PRODUCTS[product_id]
    report = RunReport(product_id, mode)
    spec = target_spec(p, mode)
    var_ids = list(p.outputs)
    acc = MonthlyAccumulator(spec, var_ids, p.min_per_month)
    regridders: dict[tuple, Regridder] = {}
    t0 = time.time()

    def regrid(field: np.ndarray, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
        key = (lats[0], lats[-1], lats.size, lons[0], lons[-1], lons.size)
        if key not in regridders:
            regridders[key] = Regridder(NativeGrid.from_centres(lats, lons), spec)
        return regridders[key](field)

    if p.access == "opendap":
        files = _opendap_files(p, mode, raw, report, limit)
        t0 = time.time()
        for begin, path, info in files:
            month = month_abs_from_iso(begin)
            fields, la, lo = standard_fields(path, p, info["lats"], info["lons"], info["lon_first"])
            for v in var_ids:
                acc.add(v, month, regrid(p.outputs[v](fields, month), la, lo))
    else:
        paths = _public_files(p, mode, raw, report, limit)
        t0 = time.time()
        start, end = time_range(p, mode)
        m_lo, m_hi = month_abs_from_iso(start), month_abs_from_iso(end)
        for path in paths:
            for month, fields, lats, lons in _read_public(p, path):
                if not (m_lo <= month <= m_hi):
                    continue
                for v in var_ids:
                    f = p.outputs[v](fields, month)
                    f, la, lo = _std(f, lats, lons)
                    acc.add(v, month, regrid(f, la, lo))

    land = _land_mask_for(conn, spec)
    kind = "test" if mode == "test" else "real"
    ds = DATASETS[p.id]
    for v in var_ids:
        got = acc.cube(v)
        if got is None:
            continue
        m0, cube = got
        dom = p.domain_mask.get(v)
        if dom and land is not None:  # AIRS skin temperature split into ground and sea
            cube[:, (land < 0.5) if dom == "land" else (land >= 0.5)] = np.nan
        validation = validate_cube(v, cube, spec, m0, kind, raw.parent / "quicklook")
        source = {
            "product": ds.product,
            "doi": ds.doi,
            "mode": mode,
            "box": TEST_BOX if mode == "test" else None,
            "files": report.files,
            "bytes": report.bytes,
            "download_s": round(report.download_s, 1),
        }
        vid = write_version(conn, v, kind, spec, m0, cube, VARIABLES[v].units, source, validation, activate)
        report.versions[v] = {"version": vid, "months": int(cube.shape[0]), "validation": validation}
    conn.commit()
    report.process_s = time.time() - t0
    return report


def _std(f, lats, lons):
    from .regrid import to_standard

    return to_standard(f, lats, lons)
