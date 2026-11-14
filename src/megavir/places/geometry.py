"""Region -> grid cells with area weights.

Weight of a cell = (fraction of the cell inside the region) x cos(latitude) x (land or sea
fraction for land-only or sea-only variables).  Boxes may cross the dateline (west > east).
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass

import numpy as np
import shapely
from shapely.geometry import shape

from megavir.store import GridSpec


@dataclass
class RegionCells:
    ii: np.ndarray  # row index in the grid
    jj: np.ndarray  # column index in the grid
    frac: np.ndarray  # fraction of the cell inside the region
    area: np.ndarray  # frac * cos(lat)
    lat: np.ndarray
    lon: np.ndarray

    @property
    def size(self) -> int:
        return int(self.ii.size)


def _overlap_1d(centres: np.ndarray, half: float, lo: float, hi: float) -> np.ndarray:
    return np.clip(np.minimum(centres + half, hi) - np.maximum(centres - half, lo), 0.0, None) / (2 * half)


def _box_parts(bbox: list[float]) -> list[tuple[float, float, float, float]]:
    w, s, e, n = (float(v) for v in bbox)
    s, n = max(-90.0, min(s, n)), min(90.0, max(s, n))
    if w > e:  # crosses the dateline
        return [(w, s, 180.0, n), (-180.0, s, e, n)]
    return [(w, s, e, n)]


def box_cells(bbox: list[float], spec: GridSpec) -> RegionCells:
    half = spec.res / 2
    parts = []
    for w, s, e, n in _box_parts(bbox):
        fy = _overlap_1d(spec.lats, half, s, n)
        fx = _overlap_1d(spec.lons, half, w, e)
        iy = np.flatnonzero(fy > 1e-9)
        jx = np.flatnonzero(fx > 1e-9)
        if iy.size == 0 or jx.size == 0:
            continue
        I, J = np.meshgrid(iy, jx, indexing="ij")
        F = fy[I] * fx[J]
        parts.append((I.ravel(), J.ravel(), F.ravel()))
    return _assemble(parts, spec)


def polygon_cells(geometry: dict, spec: GridSpec) -> RegionCells:
    geom = shape(geometry)
    if not geom.is_valid:
        geom = shapely.make_valid(geom)
    w, s, e, n = geom.bounds
    half = spec.res / 2
    iy = np.flatnonzero((spec.lats + half > s) & (spec.lats - half < n))
    jx = np.flatnonzero((spec.lons + half > w) & (spec.lons - half < e))
    if iy.size == 0 or jx.size == 0:
        return _assemble([], spec)
    I, J = np.meshgrid(iy, jx, indexing="ij")
    I, J = I.ravel(), J.ravel()
    lat, lon = spec.lats[I], spec.lons[J]
    boxes = shapely.box(lon - half, lat - half, lon + half, lat + half)
    shapely.prepare(geom)
    hit = shapely.intersects(geom, boxes)
    I, J, boxes = I[hit], J[hit], boxes[hit]
    inside = shapely.contains_properly(geom, boxes)
    frac = np.ones(I.size)
    edge = ~inside
    if edge.any():
        frac[edge] = shapely.area(shapely.intersection(boxes[edge], geom)) / (spec.res * spec.res)
    keep = frac > 1e-6
    return _assemble([(I[keep], J[keep], np.clip(frac[keep], 0, 1))], spec)


def _assemble(parts: list, spec: GridSpec) -> RegionCells:
    if parts:
        ii = np.concatenate([p[0] for p in parts]).astype(int)
        jj = np.concatenate([p[1] for p in parts]).astype(int)
        fr = np.concatenate([p[2] for p in parts]).astype(float)
    else:
        ii = jj = np.empty(0, int)
        fr = np.empty(0)
    lat = spec.lats[ii] if ii.size else np.empty(0)
    lon = spec.lons[jj] if jj.size else np.empty(0)
    return RegionCells(ii, jj, fr, fr * np.cos(np.deg2rad(lat)), lat, lon)


# --------------------------------------------------------------------------------------
# Region descriptions coming from the API
# --------------------------------------------------------------------------------------


def region_key(region: dict) -> str:
    return hashlib.sha256(json.dumps(region, sort_keys=True).encode()).hexdigest()[:24]


_CACHE: OrderedDict[str, RegionCells] = OrderedDict()
_CACHE_MAX = 512


def cells_for(region: dict, spec: GridSpec) -> RegionCells:
    """region: {"bbox": [...]} or {"geometry": GeoJSON} (already resolved from a place id)."""
    key = region_key({k: region.get(k) for k in ("bbox", "geometry", "id")}) + spec.key()
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    if region.get("geometry"):
        rc = polygon_cells(region["geometry"], spec)
    else:
        rc = box_cells(region["bbox"], spec)
    _CACHE[key] = rc
    if len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return rc


def apply_domain(
    rc: RegionCells, domain: str, land_frac: np.ndarray | None, offset: tuple[int, int] = (0, 0)
) -> np.ndarray:
    """Weights after the land/sea mask.  land_frac is on the global grid; offset maps window cells into it."""
    if domain == "all" or land_frac is None or rc.size == 0:
        return rc.area
    gi = rc.ii + offset[0]
    gj = rc.jj + offset[1]
    ok = (gi >= 0) & (gi < land_frac.shape[0]) & (gj >= 0) & (gj < land_frac.shape[1])
    lf = np.zeros(rc.size)
    lf[ok] = land_frac[gi[ok], gj[ok]]
    return rc.area * (lf if domain == "land" else 1.0 - lf)
