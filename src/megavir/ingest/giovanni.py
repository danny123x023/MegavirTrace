"""Cross-check against NASA Giovanni (design success criterion).

Target: regional IMERG and MERRA-2 series match Giovanni, with correlation >= 0.98 and mean
difference within 5 %.

Giovanni's programmatic time-series service returns one grid point at a time (no area
averages), so the area average for the test box is built from a regular grid of points across
the box, each answered by Giovanni from the product's native grid.  It is compared with
MegavirTrace's area-weighted mean of the same box from the stored (regridded) data.  Both
sides use the product's own units as Giovanni reports them, converted to ours.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import time

import numpy as np

from megavir.catalog import VARIABLES
from megavir.store import active_versions, read_cells

from .download import LoginRequired, earthdata_bearer
from .pipeline import TEST_BOX
from .regrid import days_in_month

GIOVANNI_TS = "https://api.giovanni.earthdata.nasa.gov/timeseries"

# Giovanni data ids and the conversion from Giovanni's units to MegavirTrace's.
# The time-series service serves MERRA-2 hourly (M2T1NXSLV), not the monthly collection; the monthly
# mean of the hourly values is by definition what M2TMNXSLV holds.  IMERG monthly is served directly.
CHECKS = {
    "air_temp": {"data": "M2T1NXSLV_5_12_4_T2M", "to_ours": lambda v, m: v - 273.15, "years": 3},
    "rainfall": {
        "data": "GPM_3IMERGM_07_precipitation",
        "to_ours": lambda v, m: v * 24 * days_in_month(m),
        "years": 10,
    },
}


def _parse_csv(text: str) -> dict[int, float]:
    """Giovanni time-series CSV -> monthly means.

    Layout: metadata lines (prod_name, unit, undef, ...), a blank line, then
    'Timestamp (UTC),Data' and rows 'YYYY-MM-DD HH:MM,value'.  Hourly or half-hourly rows are
    averaged within each calendar month; monthly rows pass through unchanged.
    """
    undef = None
    sums: dict[int, float] = {}
    counts: dict[int, int] = {}
    started = False
    for r in csv.reader(io.StringIO(text)):
        if not r:
            continue
        if not started:
            if r[0].strip().lower() == "undef" and len(r) > 1:
                try:
                    undef = float(r[1])
                except ValueError:
                    pass
            if r[0].lower().startswith("timestamp"):
                started = True
            continue
        if len(r) < 2:
            continue
        try:
            d = dt.datetime.fromisoformat(r[0].strip().replace("Z", ""))
            v = float(r[1])
        except ValueError:
            continue
        if not np.isfinite(v) or (undef is not None and abs(v - undef) <= 1e-6 * max(1.0, abs(undef))):
            continue
        m = d.year * 12 + d.month - 1
        sums[m] = sums.get(m, 0.0) + v
        counts[m] = counts.get(m, 0) + 1
    return {m: sums[m] / counts[m] for m in sums}


def giovanni_point(
    session, data_id: str, lat: float, lon: float, start: str, end: str, retries: int = 3
) -> dict[int, float]:
    params = {"data": data_id, "location": f"[{lat:.4f},{lon:.4f}]", "time": f"{start}/{end}"}
    for attempt in range(retries):
        r = session.get(GIOVANNI_TS, params=params)
        if r.status_code in (401, 403):
            raise LoginRequired(
                f"Giovanni refused the request ({r.status_code}); an Earthdata bearer token is needed"
            )
        if r.status_code == 200:
            return _parse_csv(r.text)
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"Giovanni error {r.status_code}: {r.text[:200]}")


def regional_ours(conn, var_id: str, bbox: tuple[float, float, float, float]) -> dict[int, float]:
    from megavir.engine.aggregate import region_mean
    from megavir.places.geometry import box_cells

    v = active_versions(conn).get(var_id)
    if not v:
        raise RuntimeError(f"{var_id} is not loaded")
    w, s, e, n = bbox
    rc = box_cells([w, s, e, n], v.spec)
    cube = read_cells(conn, v, rc.ii, rc.jj)
    mean, cov = region_mean(cube, rc.area)
    return {
        int(m): float(x) for m, x, c in zip(v.months, mean, cov, strict=True) if np.isfinite(x) and c >= 0.9
    }


def check(conn, var_id: str, points_per_side: int = 5, years: int | None = None) -> dict:
    spec = CHECKS[var_id]
    years = years or spec["years"]
    w, s, e, n = TEST_BOX
    import httpx

    session = httpx.Client(timeout=180, headers={"Authorization": f"Bearer {earthdata_bearer()}"})
    end = dt.date.today().replace(day=1) - dt.timedelta(days=1)
    start = dt.date(end.year - years, end.month, 1)
    lats = np.linspace(s, n, points_per_side + 2)[1:-1]
    lons = np.linspace(w, e, points_per_side + 2)[1:-1]
    weights, series = [], []
    for la in lats:
        for lo in lons:
            pts = giovanni_point(
                session, spec["data"], la, lo, f"{start.isoformat()}T00:00:00", f"{end.isoformat()}T23:59:59"
            )
            series.append({m: spec["to_ours"](v, m) for m, v in pts.items()})
            weights.append(np.cos(np.deg2rad(la)))
    months = sorted(set.intersection(*(set(x) for x in series))) if series else []
    gio = {m: float(np.average([x[m] for x in series], weights=weights)) for m in months}
    ours = regional_ours(conn, var_id, TEST_BOX)
    shared = [m for m in months if m in ours]
    a = np.array([ours[m] for m in shared])
    b = np.array([gio[m] for m in shared])
    if len(shared) < 12:
        raise RuntimeError(f"only {len(shared)} shared months between Giovanni and the stored data")
    r = float(np.corrcoef(a, b)[0, 1])
    rel = float(abs(a.mean() - b.mean()) / abs(b.mean())) if b.mean() != 0 else float("inf")
    result = {
        "variable": var_id,
        "giovanni_data": spec["data"],
        "box": list(TEST_BOX),
        "points": len(series),
        "months": len(shared),
        "period": [
            f"{shared[0] // 12}-{shared[0] % 12 + 1:02d}",
            f"{shared[-1] // 12}-{shared[-1] % 12 + 1:02d}",
        ],
        "correlation": r,
        "mean_ours": float(a.mean()),
        "mean_giovanni": float(b.mean()),
        "relative_mean_difference": rel,
        "units": VARIABLES[var_id].units,
        "ok": bool(r >= 0.98 and rel <= 0.05),
        "method": "Giovanni point time series on a regular grid across the box, cos(latitude)-weighted, against the stored area-weighted box mean",
    }
    v = active_versions(conn)[var_id]
    conn.execute(
        "UPDATE grid_version SET validation = validation || %s::jsonb WHERE id = %s",
        (json.dumps({"giovanni_check": result}), v.id),
    )
    conn.commit()
    return result
