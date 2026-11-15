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

import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import logging
import os
import re
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from megavir.catalog import DATASETS, VARIABLES
from megavir.store import GridSpec, read_land_mask, write_version

from . import download as dl
from .products import PRODUCTS, Product, gunzip, month_abs_from_iso, multi_time_fields, standard_fields
from .regrid import NativeGrid, Regridder, bin_to_grid
from .validate import validate_cube

log = logging.getLogger("megavir.ingest")


class ProductBusy(RuntimeError):
    """Another import of the same product is running (command line or dashboard)."""


def _progress(**fields) -> None:
    """One machine-readable progress line for the import dashboard's job runner (MEGAVIR_PROGRESS=1)."""
    if os.environ.get("MEGAVIR_PROGRESS") == "1":
        print("PROGRESS " + json.dumps(fields), flush=True)


@contextlib.contextmanager
def product_lock(raw: Path, product_id: str):
    """Only one import per product at a time: both would write the same raw files."""
    raw.mkdir(parents=True, exist_ok=True)
    with open(raw / f".{product_id}.lock", "w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ProductBusy(f"another import of {product_id} is already running") from None
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def cube_digest(cube: np.ndarray) -> str:
    """Checksum of the stored values (float32, NaN included), to recognise an unchanged import."""
    return hashlib.blake2b(np.ascontiguousarray(cube, dtype=np.float32).tobytes(), digest_size=16).hexdigest()


def unchanged_version(
    conn, variable: str, kind: str, spec: GridSpec, month0: int, n_months: int, digest: str
):
    """The active version's id when it holds exactly these values on this grid, else None."""
    r = conn.execute(
        """SELECT id FROM grid_version WHERE variable = %s AND active AND kind = %s AND source->>'checksum' = %s
           AND res_deg = %s AND lat0 = %s AND lon0 = %s AND ny = %s AND nx = %s AND month0 = %s AND n_months = %s""",
        (variable, kind, digest, spec.res, spec.lat0, spec.lon0, spec.ny, spec.nx, month0, n_months),
    ).fetchone()
    return r["id"] if r else None


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
    no_data: list = field(default_factory=list)  # variables with no valid month in the files
    notes: dict = field(default_factory=dict)  # variable -> what was masked after regridding

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
    """Monthly means for one variable on the target grid, streaming in time order.

    Running sums are kept only for the months still being filled (inputs arrive sorted by
    time, so at most a couple are open); finished months are stored as a float32 mean and a
    uint16 count (so a late input can still be averaged in).  Memory is
    about one float32 field per month instead of float64 sums and counts for every month of
    every variable, which needed ~5 GB for MERRA-2 statistics at 0.5 degrees.
    """

    KEEP_OPEN = 2  # months kept open for slightly out-of-order inputs (e.g. north and south sea-ice files)

    def __init__(self, spec: GridSpec, min_count: int):
        self.spec = spec
        self.min_count = min_count
        self.open: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        self.done: dict[int, tuple[np.ndarray, np.ndarray]] = {}  # month -> (mean float32, count uint16)

    def add(self, month: int, field: np.ndarray) -> None:
        if month in self.done:  # a late input for a finished month: reopen it with its sums and counts
            mean, cnt = self.done.pop(month)
            c = cnt.astype(np.int32)
            self.open[month] = (np.where(c > 0, np.nan_to_num(mean.astype(float)) * c, 0.0), c)
        if month not in self.open:
            self.open[month] = (np.zeros(field.shape), np.zeros(field.shape, np.int32))
        s, c = self.open[month]
        ok = np.isfinite(field)
        s[ok] += field[ok]
        c[ok] += 1
        for m in sorted(self.open)[: -self.KEEP_OPEN]:
            self._finish(m)

    def _finish(self, month: int) -> None:
        s, c = self.open.pop(month)
        with np.errstate(invalid="ignore", divide="ignore"):
            mean = np.where(c > 0, s / c, np.nan).astype(np.float32)
        self.done[month] = (mean, np.minimum(c, 65535).astype(np.uint16))

    def cube(self) -> tuple[int, np.ndarray] | None:
        for m in list(self.open):
            self._finish(m)
        if not self.done:
            return None
        months = sorted(self.done)
        m0, m1 = months[0], months[-1]
        out = np.full((m1 - m0 + 1, self.spec.ny, self.spec.nx), np.nan, np.float32)
        for m in months:
            mean, cnt = self.done.pop(m)  # free each month as it is copied
            out[m - m0] = np.where(cnt >= self.min_count, mean, np.nan)
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
    granules = _granules(p, start, end, limit)
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
    t_offset = 0
    if p.multi_time:
        # the time dimension is the one that is neither latitude nor longitude
        dims = list(meta["vars"].values())[0]["dims"]
        tsize = next((d[1] for d in dims if d[1] not in (ny, nx) and d[1] > 1), 0)
        if tsize and mode == "test":
            t_offset = max(0, tsize - 120)  # the most recent 10 years
            ranges[tsize] = (t_offset, tsize - 1)
    out = []
    for k, g in enumerate(granules):
        _progress(stage="download", done=k, total=len(granules))
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
                {
                    "lats": lats[i0 : i1 + 1],
                    "lons": lons[j0 : j1 + 1],
                    "lon_first": lon_axis_first,
                    "t_offset": t_offset,
                },
            )
        )
    return out


def _granules(p: Product, start: str, end: str, limit: int | None) -> list:
    granules = dl.cmr_granules(p.concept_id, start, end)
    if p.granule_filter:
        granules = [g for g in granules if p.granule_filter(g)]
    # one file per name: some archives list the same file under two granule records (OB.DAAC)
    seen: set[str] = set()
    granules = [g for g in granules if not (g.name in seen or seen.add(g.name))]
    if limit:
        granules = granules[-limit:]
    if not granules:
        raise RuntimeError(f"no granules for {p.id} in {start}..{end}")
    return granules


def _download_files(
    p: Product, mode: str, raw: Path, report: RunReport, limit: int | None
) -> list[tuple[str, Path]]:
    """Whole files over HTTPS with Earthdata Login (products without OPeNDAP).

    The files are shared by the test and full runs; the test run crops to the test box after
    reading, so a later full run reuses every file already on disk.
    """
    start, end = time_range(p, mode)
    granules = _granules(p, start, end, limit)
    session = dl.earthdata_session()
    folder = raw / p.id
    out = []
    for k, g in enumerate(granules):
        _progress(stage="download", done=k, total=len(granules))
        if not g.data_url:
            report.skipped_files.append(g.ur)
            continue
        dest = folder / re.sub(r"[^0-9A-Za-z._-]", "_", g.data_url.rstrip("/").split("/")[-1])
        info = dl.download(g.data_url, dest, session)
        report.files += 1
        report.bytes += info["bytes"]
        report.download_s += info["seconds"]
        out.append((g.begin, dest))
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
    for k, (url, name) in enumerate(urls):
        _progress(stage="download", done=k, total=len(urls))
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
    got = read_land_mask(conn, spec.res)
    if not got:
        return None
    g, lf = got
    oi, oj = spec.offset_in(g)
    return lf[oi : oi + spec.ny, oj : oj + spec.nx]


SEA_ICE_EDGE = 15.0  # %: the usual ice-edge threshold (NSIDC sea ice extent)


def drop_sea_ice(conn, cube: np.ndarray, spec: GridSpec, m0: int, floor: float) -> str:
    """Remove the cell-months of a sea-surface field that are frozen sea (in place).

    A cell is dropped when any part of it had at least 15 % sea ice that month in the stored
    NSIDC record, or its value is below ``floor``.  Months the ice record does not cover use the
    same calendar month of the last five years it does cover (dropped if ice was there in any).
    """
    from megavir.store import active_versions, read_full

    cube[cube < floor] = np.nan
    v = active_versions(conn).get("sea_ice")
    if v is None or v.kind != "real":
        return f"values below {floor:g} dropped; no real sea-ice record to mask frozen sea"
    k = int(round(spec.res / v.spec.res))
    if k < 1 or abs(k * v.spec.res - spec.res) > 1e-6:
        raise ValueError(f"cannot aggregate the {v.spec.res}° sea-ice grid to {spec.res}°")
    ice = read_full(conn, v)  # (months, ny, nx) on the sea-ice grid, percent
    n, ny, nx = ice.shape
    coarse_spec = GridSpec(
        spec.res, v.spec.lat0 + (k - 1) * v.spec.res / 2, v.spec.lon0 + (k - 1) * v.spec.res / 2, ny // k, nx // k
    )
    oi, oj = spec.offset_in(coarse_spec)
    if oi < 0 or oj < 0 or oi + spec.ny > coarse_spec.ny or oj + spec.nx > coarse_spec.nx:
        raise ValueError("the sea-ice grid does not cover this field's grid")
    with np.errstate(invalid="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        coarse = np.nanmax(ice[:, : ny // k * k, : nx // k * k].reshape(n, ny // k, k, nx // k, k), axis=(2, 4))
    del ice
    coarse = coarse[:, oi : oi + spec.ny, oj : oj + spec.nx]
    frozen = np.nan_to_num(coarse, nan=0.0) >= SEA_ICE_EDGE
    have = np.isfinite(coarse).any(axis=(1, 2))
    months = m0 + np.arange(cube.shape[0])
    ice_months = v.month0 + np.arange(n)
    filled = 0
    for i, m in enumerate(months):
        j = int(m - v.month0)
        if 0 <= j < n and have[j]:
            mask = frozen[j]
        else:  # outside the ice record: the same calendar month of the last five years it covers
            same = np.flatnonzero((ice_months % 12 == m % 12) & have)[-5:]
            mask = frozen[same].any(axis=0) if same.size else np.zeros(cube.shape[1:], bool)
            filled += 1
        cube[i][mask] = np.nan
    note = f"values below {floor:g} and cell-months with >= {SEA_ICE_EDGE:g}% sea ice (NSIDC version {v.id}) dropped"
    if filled:
        note += f"; {filled} months beyond the ice record used the last five years' ice for that month"
    return note


def run(
    product_id: str, mode: str, conn, raw: Path, limit: int | None = None, activate: bool = True
) -> RunReport:
    if mode not in ("test", "full"):
        raise ValueError("mode must be 'test' or 'full'")
    with product_lock(raw, product_id):
        return _run(product_id, mode, conn, raw, limit, activate)


def _run(product_id: str, mode: str, conn, raw: Path, limit: int | None, activate: bool) -> RunReport:
    p = PRODUCTS[product_id]
    report = RunReport(product_id, mode)
    spec = target_spec(p, mode)
    regridders: dict[tuple, Regridder] = {}

    def regrid(field: np.ndarray, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
        key = (lats[0], lats[-1], lats.size, lons[0], lons[-1], lons.size)
        if key not in regridders:
            regridders[key] = Regridder(NativeGrid.from_centres(lats, lons), spec)
        return regridders[key](field)

    # 1. download (resumable; files stay on disk)
    if p.access == "opendap":
        files = _opendap_files(p, mode, raw, report, limit)
    elif p.access == "download":
        files = _download_files(p, mode, raw, report, limit)
    else:
        files = _public_files(p, mode, raw, report, limit)
    t0 = time.time()

    def records():
        """(month, fields, lats, lons) from the local files, in time order."""
        if p.access == "opendap":
            for begin, path, info in files:
                if p.multi_time:
                    m0 = month_abs_from_iso(begin) + info["t_offset"]
                    for k, fields, la, lo in multi_time_fields(
                        path, p, info["lats"], info["lons"], info["lon_first"]
                    ):
                        yield m0 + k, fields, la, lo
                    continue
                fields, la, lo = standard_fields(path, p, info["lats"], info["lons"], info["lon_first"])
                yield month_abs_from_iso(begin), fields, la, lo
        elif p.access == "download":
            for begin, path in files:
                yield from p.reader(path, begin)
        else:
            start, end = time_range(p, mode)
            m_lo, m_hi = month_abs_from_iso(start), month_abs_from_iso(end)
            for path in files:
                for month, fields, lats, lons in _read_public(p, path):
                    if m_lo <= month <= m_hi:
                        yield month, fields, lats, lons

    land = _land_mask_for(conn, spec)
    kind = "test" if mode == "test" else "real"
    ds = DATASETS[p.id]
    # 2. one variable at a time, so memory holds one variable's cube
    outputs = list(p.outputs)
    for i, v in enumerate(outputs):
        _progress(stage="build", variable=v, index=i, total=len(outputs))
        acc = MonthlyAccumulator(spec, p.min_per_month)
        for month, fields, la, lo in records():
            f = p.outputs[v](fields, month)
            if p.projected:
                acc.add(month, bin_to_grid(la, lo, f, spec))
            elif p.access == "public":
                f, la2, lo2 = _std(f, la, lo)
                acc.add(month, regrid(f, la2, lo2))
            else:
                acc.add(month, regrid(f, la, lo))
        got = acc.cube()
        del acc
        if got is None:
            report.no_data.append(v)
            _progress(stage="stored", variable=v, action="no_data")
            continue
        m0, cube = got
        dom = p.domain_mask.get(v)
        if dom and land is not None:  # e.g. AIRS skin temperature split into ground and sea
            cube[:, (land < 0.5) if dom == "land" else (land >= 0.5)] = np.nan
        if v in p.ice_mask:
            report.notes[v] = drop_sea_ice(conn, cube, spec, m0, p.ice_mask[v])
        validation = validate_cube(v, cube, spec, m0, kind, raw.parent / "quicklook")
        digest = cube_digest(cube)
        same = unchanged_version(conn, v, kind, spec, m0, int(cube.shape[0]), digest) if activate else None
        if same:  # identical to what is stored: keep the stored version (and its cached statistics)
            report.versions[v] = {
                "version": same,
                "months": int(cube.shape[0]),
                "validation": validation,
                "unchanged": True,
            }
            _progress(stage="stored", variable=v, action="unchanged", version=same)
            del cube
            continue
        source = {
            "product": ds.product,
            "doi": ds.doi,
            "mode": mode,
            "box": TEST_BOX if mode == "test" else None,
            "files": report.files,
            "bytes": report.bytes,
            "download_s": round(report.download_s, 1),
            "checksum": digest,
        }
        _progress(stage="swap", variable=v)
        vid = write_version(conn, v, kind, spec, m0, cube, VARIABLES[v].units, source, validation, activate)
        report.versions[v] = {"version": vid, "months": int(cube.shape[0]), "validation": validation}
        conn.commit()
        _progress(stage="stored", variable=v, action="imported", version=vid)
        del cube
    report.process_s = time.time() - t0
    return report


def _std(f, lats, lons):
    from .regrid import to_standard

    return to_standard(f, lats, lons)
