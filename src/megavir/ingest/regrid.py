"""Harmonisation: orientation fixes and conservative regridding to the common grid.

Regular latitude-longitude cells are rectangles in (lon, sin lat), so conservative
regridding separates into a latitude overlap matrix (weighted by the change in sin(lat),
i.e. true area) and a longitude overlap matrix.  Missing input is handled by regridding the
valid-area mask alongside the data: an output cell gets a value only when at least
``min_valid`` of its area had data, and that value is the area-weighted mean of the valid
part.  The global area-weighted mean is preserved.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import sparse

from megavir.store import GridSpec


@dataclass
class NativeGrid:
    lat_edges: np.ndarray  # increasing, south -> north, len ny + 1
    lon_edges: np.ndarray  # increasing, -180 -> 180, len nx + 1

    @staticmethod
    def from_centres(lats: np.ndarray, lons: np.ndarray) -> NativeGrid:
        return NativeGrid(_edges(np.asarray(lats, float), clip=(-90, 90)), _edges(np.asarray(lons, float)))


def _edges(c: np.ndarray, clip: tuple[float, float] | None = None) -> np.ndarray:
    if c.size == 1:
        raise ValueError("need at least two centres")
    mid = (c[1:] + c[:-1]) / 2
    e = np.concatenate([[c[0] - (mid[0] - c[0])], mid, [c[-1] + (c[-1] - mid[-1])]])
    if clip:
        e = np.clip(e, *clip)
    return e


def spec_edges(spec: GridSpec) -> tuple[np.ndarray, np.ndarray]:
    h = spec.res / 2
    lat_e = np.concatenate([spec.lats - h, [spec.lats[-1] + h]])
    lon_e = np.concatenate([spec.lons - h, [spec.lons[-1] + h]])
    return np.clip(lat_e, -90, 90), lon_e


def _overlap_matrix(dst: np.ndarray, src: np.ndarray, transform=None) -> sparse.csr_matrix:
    """M[i, k] = length of overlap between dst cell i and src cell k (after ``transform``)."""
    if transform is not None:
        dst, src = transform(dst), transform(src)
    rows, cols, vals = [], [], []
    k0 = 0
    for i in range(dst.size - 1):
        lo, hi = dst[i], dst[i + 1]
        while k0 < src.size - 1 and src[k0 + 1] <= lo:
            k0 += 1
        k = k0
        while k < src.size - 1 and src[k] < hi:
            ov = min(hi, src[k + 1]) - max(lo, src[k])
            if ov > 0:
                rows.append(i)
                cols.append(k)
                vals.append(ov)
            k += 1
    return sparse.csr_matrix((vals, (rows, cols)), shape=(dst.size - 1, src.size - 1))


def _lon_matrix(dst: np.ndarray, src: np.ndarray) -> sparse.csr_matrix:
    """Longitude overlaps; a source grid spanning 360° wraps around the dateline."""
    nx = src.size - 1
    if abs((src[-1] - src[0]) - 360.0) < 1e-6:
        ext = np.concatenate([src[:-1] - 360.0, src[:-1], src + 360.0])
        M = _overlap_matrix(dst, ext).tocoo()
        M = sparse.csr_matrix((M.data, (M.row, M.col % nx)), shape=(dst.size - 1, nx))
    else:
        M = _overlap_matrix(dst, src)
    return M.T.tocsr()


class Regridder:
    def __init__(self, src: NativeGrid, dst: GridSpec, min_valid: float = 0.5):
        dlat, dlon = spec_edges(dst)
        sin = lambda e: np.sin(np.deg2rad(e))  # noqa: E731
        self.A = _overlap_matrix(dlat, src.lat_edges, sin)  # (ny_dst, ny_src), area in sin(lat)
        self.B = _lon_matrix(dlon, src.lon_edges)  # (nx_src, nx_dst)
        self.dst_area = np.outer(np.diff(np.sin(np.deg2rad(dlat))), np.diff(dlon))
        self.min_valid = min_valid
        self.dst = dst

    def __call__(self, field: np.ndarray) -> np.ndarray:
        """field: (ny_src, nx_src) south->north, west->east, NaN for missing."""
        f = np.asarray(field, float)
        valid = np.isfinite(f)
        num = self.A @ sparse.csr_matrix(np.where(valid, f, 0.0)) @ self.B
        den = self.A @ sparse.csr_matrix(valid.astype(float)) @ self.B
        num = num.toarray()
        den = den.toarray()
        with np.errstate(invalid="ignore", divide="ignore"):
            out = num / den
            frac = den / self.dst_area
        out[(den <= 0) | (frac < self.min_valid - 1e-9)] = np.nan
        return out.astype(np.float32)


# --------------------------------------------------------------------------------------
# Orientation helpers ("known traps")
# --------------------------------------------------------------------------------------


def to_standard(field: np.ndarray, lats: np.ndarray, lons: np.ndarray, lon_first: bool = False):
    """Return (field[lat, lon] south->north, lons in -180..180 increasing, lats, lons).

    Handles longitude-first storage (IMERG), north->south latitude (MODIS CMG, AIRS) and
    0..360 longitudes (NASA-SSH, GRACE mascons).
    """
    f = np.asarray(field)
    if lon_first:
        f = f.T
    lats = np.asarray(lats, float)
    lons = np.asarray(lons, float)
    if lats[0] > lats[-1]:
        f = f[::-1]
        lats = lats[::-1]
    if lons.max() > 180:
        lons = np.where(lons > 180, lons - 360, lons)
    order = np.argsort(lons, kind="stable")
    if not np.all(order == np.arange(lons.size)):
        f = f[:, order]
        lons = lons[order]
    return f, lats, lons


def apply_fill(a: np.ndarray, fill_values=(), valid_range: tuple[float, float] | None = None) -> np.ndarray:
    a = np.asarray(a, float).copy()
    for fv in fill_values:
        if fv is None:
            continue
        a[np.isclose(a, fv, rtol=1e-6, atol=0)] = np.nan
    if valid_range is not None:
        lo, hi = valid_range
        a[(a < lo) | (a > hi)] = np.nan
    return a


def days_in_month(month_abs: int) -> int:
    y, m = month_abs // 12, month_abs % 12 + 1
    if m == 12:
        return 31
    import datetime as _dt

    return (_dt.date(y, m + 1, 1) - _dt.date(y, m, 1)).days
