"""Validation before use: area means, plausibility ranges, quick-look maps, NASA cross-checks."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import numpy as np

from megavir.store import GridSpec

# Published global-mean ranges used as plausibility checks on full (global) imports.
PLAUSIBLE_GLOBAL = {
    "rainfall": (70.0, 95.0, "mm/month; IMERG global mean is about 2.7 mm/day ≈ 82 mm/month"),
    "air_temp": (13.0, 16.5, "°C; global 2 m air temperature is about 14–15 °C"),
    "temp_change": (-1.0, 1.5, "°C anomaly against 1951–1980"),
    "sea_surface_temp": (15.0, 22.0, "°C; open-ocean mean skin temperature"),
    "ndvi": (0.2, 0.45, "NDVI over land"),
}


def area_mean_series(cube: np.ndarray, spec: GridSpec) -> np.ndarray:
    w = np.cos(np.deg2rad(spec.lats))[:, None] * np.ones((1, spec.nx))
    valid = np.isfinite(cube)
    sw = np.where(valid, w[None], 0).sum(axis=(1, 2))
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(sw > 0, np.nansum(np.where(valid, cube, 0) * w[None], axis=(1, 2)) / sw, np.nan)


def validate_cube(
    var: str, cube: np.ndarray, spec: GridSpec, month0: int, kind: str, quicklook_dir: Path
) -> dict:
    series = area_mean_series(cube, spec)
    finite = np.isfinite(cube)
    out = {
        "months": int(cube.shape[0]),
        "valid_share": float(finite.mean()),
        "area_mean": float(np.nanmean(series)) if np.isfinite(series).any() else None,
        "min": float(np.nanmin(cube)) if finite.any() else None,
        "max": float(np.nanmax(cube)) if finite.any() else None,
        "months_without_data": int((~np.isfinite(series)).sum()),
        "is_global": spec.is_global_lon and spec.ny * spec.res >= 179.9,
    }
    if out["is_global"] and var in PLAUSIBLE_GLOBAL and out["area_mean"] is not None:
        lo, hi, why = PLAUSIBLE_GLOBAL[var]
        out["plausible"] = {"ok": bool(lo <= out["area_mean"] <= hi), "range": [lo, hi], "note": why}
    try:
        out["quicklook"] = str(quicklook(var, cube, spec, kind, quicklook_dir))
    except Exception as e:  # noqa: BLE001 - a missing plot must not block an import
        out["quicklook_error"] = str(e)
    return out


def quicklook(var: str, cube: np.ndarray, spec: GridSpec, kind: str, folder: Path) -> Path:
    """A PNG of the time-mean field, to see that the continents are in the right place."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    folder.mkdir(parents=True, exist_ok=True)
    with np.errstate(all="ignore"):
        mean = np.nanmean(cube, axis=0)
    h = spec.res / 2
    extent = [spec.lons[0] - h, spec.lons[-1] + h, spec.lats[0] - h, spec.lats[-1] + h]
    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=110)
    im = ax.imshow(mean, origin="lower", extent=extent, cmap="viridis", aspect="auto")
    ax.set_title(f"{var} — time mean ({kind})")
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    fig.colorbar(im, ax=ax, shrink=0.8)
    path = folder / f"{var}_{kind}.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


# --------------------------------------------------------------------------------------
# GISTEMP against NASA's official global series
# --------------------------------------------------------------------------------------

GISTEMP_GLOBAL_CSV = "https://data.giss.nasa.gov/gistemp/tabledata_v4/GLB.Ts+dSST.csv"


def parse_official_gistemp(text: str) -> dict[int, float]:
    """Year -> J-D annual mean anomaly (°C) from GLB.Ts+dSST.csv."""
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("Year"))
    out = {}
    for row in csv.DictReader(io.StringIO("\n".join(lines[start:]))):
        try:
            out[int(row["Year"])] = float(row["J-D"])
        except (ValueError, KeyError, TypeError):
            continue
    return out


def compare_gistemp(our_years: np.ndarray, our_values: np.ndarray, official: dict[int, float]) -> dict:
    yrs = [int(y) for y in our_years if int(y) in official]
    a = np.array([our_values[list(our_years).index(y)] for y in yrs])
    b = np.array([official[y] for y in yrs])
    r = float(np.corrcoef(a, b)[0, 1])
    sel = np.array(yrs) >= 1975
    slope_ours = float(np.polyfit(np.array(yrs)[sel], a[sel], 1)[0] * 10)
    slope_nasa = float(np.polyfit(np.array(yrs)[sel], b[sel], 1)[0] * 10)
    return {
        "years": [yrs[0], yrs[-1]],
        "correlation": r,
        "mean_abs_difference": float(np.mean(np.abs(a - b))),
        "warming_since_1975_per_decade": {"ours": slope_ours, "nasa": slope_nasa},
        "warmest_year": {"ours": int(yrs[int(np.argmax(a))]), "nasa": int(yrs[int(np.argmax(b))])},
        "ok": bool(
            r >= 0.98
            and abs(slope_ours - slope_nasa) <= 0.02
            and yrs[int(np.argmax(a))] == yrs[int(np.argmax(b))]
        ),
    }
