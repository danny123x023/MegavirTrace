"""Ground versus satellite with NASA GLOBE (FR14).

GLOBE (Global Learning and Observations to Benefit the Environment) collects measurements
made by schools and citizen scientists.  For a stored analysis we fetch the GLOBE
observations for the same place, build a monthly regional series and show it beside the
satellite series as monthly anomalies, with how well they move together.

GLOBE values are context only: they never enter the trend tests.  Sites are few, change over
time and measure one point, while the satellite or model value is an area average.

The GLOBE API answers 202 while it prepares a result and 200 once it is ready, so requests
are polled with back-off.  Results are cached in PostgreSQL for 30 days.
"""

from __future__ import annotations

import calendar
import datetime as dt
import hashlib
import json
import time
from dataclasses import dataclass

import httpx
import numpy as np

GLOBE_API = "https://api.globe.gov/search/v1/measurement/protocol/measureddate/lat/lon/"
USER_AGENT = "MegavirTrace/0.1 (NASA Space Apps open-source project)"
CACHE_DAYS = 30
MAX_SPAN_DEG = 20.0  # bbox side limit: GLOBE results for bigger regions are too large to fetch on demand
MAX_YEARS = 15
MIN_DAYS_PER_SITE_MONTH = 10  # air temperature: days with readings a site needs in a month
MIN_COVERED_DAYS_PRECIP = 20  # precipitation: days the gauge readings must cover in a month


@dataclass(frozen=True)
class Pairing:
    protocol: str
    quantity: str  # "air_mean" | "air_max" | "air_min" | "precip"
    label: str
    units: str


PAIRINGS: dict[str, Pairing] = {
    "air_temp": Pairing(
        "air_temp_dailies", "air_mean", "GLOBE air temperature (mean of daily high and low)", "°C"
    ),
    "temp_change": Pairing(
        "air_temp_dailies", "air_mean", "GLOBE air temperature (mean of daily high and low)", "°C"
    ),
    "daily_high": Pairing("air_temp_dailies", "air_max", "GLOBE daily high temperature", "°C"),
    "nightly_low": Pairing("air_temp_dailies", "air_min", "GLOBE daily low temperature", "°C"),
    "rainfall": Pairing("precipitations", "precip", "GLOBE rain gauge totals", "mm/month"),
}

CAVEATS = [
    "GLOBE measurements are made by schools and volunteers at a few points; the satellite value is an average over the whole region.",
    "Sites start and stop over time, so the ground series can jump when the set of sites changes.",
    "Ground observations are shown as context only; they are not used in the trend tests.",
]


class GlobeError(RuntimeError):
    pass


# --------------------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------------------


def _get_with_polling(client: httpx.Client, params: dict, max_wait_s: float = 90.0) -> list[dict]:
    waited, delay = 0.0, 2.0
    while True:
        r = client.get(GLOBE_API, params=params)
        if r.status_code == 200 and r.content:
            return r.json().get("results", [])
        if r.status_code not in (202, 200, 429, 503):
            raise GlobeError(f"GLOBE API error {r.status_code}")
        if waited >= max_wait_s:
            raise GlobeError("GLOBE is still preparing these observations; please try again in a minute")
        time.sleep(delay)
        waited += delay
        delay = min(delay * 1.5, 15.0)


def fetch_observations(
    protocol: str, bbox: list[float], start: dt.date, end: dt.date, client: httpx.Client | None = None
) -> list[dict]:
    """All GLOBE records for a protocol, box and period (fetched year by year)."""
    w, s, e, n = bbox
    own = client is None
    client = client or httpx.Client(timeout=120, headers={"User-Agent": USER_AGENT})
    out: list[dict] = []
    try:
        for year in range(start.year, end.year + 1):
            a = max(start, dt.date(year, 1, 1))
            b = min(end, dt.date(year, 12, 31))
            params = {
                "protocols": protocol,
                "startdate": a.isoformat(),
                "enddate": b.isoformat(),
                "minlat": s,
                "maxlat": n,
                "minlon": w,
                "maxlon": e,
                "geojson": "FALSE",
                "sample": "FALSE",
            }
            out.extend(_get_with_polling(client, params))
    finally:
        if own:
            client.close()
    return out


# --------------------------------------------------------------------------------------
# Monthly series
# --------------------------------------------------------------------------------------


def _value(rec: dict, quantity: str) -> tuple[float, int] | None:
    d = rec.get("data") or {}
    if quantity in ("air_mean", "air_max", "air_min"):
        hi, lo = d.get("airtempdailiesMaximumTemp"), d.get("airtempdailiesMinimumTemp")
        if quantity == "air_max":
            v = hi
        elif quantity == "air_min":
            v = lo
        else:
            v = (hi + lo) / 2 if isinstance(hi, int | float) and isinstance(lo, int | float) else None
        if not isinstance(v, int | float) or not (-90 <= v <= 60):
            return None
        return float(v), 1
    if quantity == "precip":
        mm, days = d.get("precipitationsLiquidAccumulation"), d.get("precipitationsDaysAccumulated")
        if (
            not isinstance(mm, int | float)
            or not isinstance(days, int | float)
            or days <= 0
            or mm < 0
            or mm > 2000
        ):
            return None
        return float(mm), int(days)
    return None


def monthly_series(records: list[dict], quantity: str, inside=None) -> dict:
    """Regional monthly series: per-site monthly values first, then the mean over sites.

    Air temperature: a site-month needs readings on at least 10 days.  Precipitation: the
    gauge readings must cover at least 20 days; the total is scaled to the whole month.
    ``inside(lat, lon)`` optionally keeps only sites inside a polygon.
    """
    per: dict[tuple[int, str], dict] = {}
    sites: dict[int, dict] = {}
    for rec in records:
        lat, lon = rec.get("latitude"), rec.get("longitude")
        if lat is None or lon is None or (inside and not inside(lat, lon)):
            continue
        got = _value(rec, quantity)
        if got is None:
            continue
        v, days = got
        month = str(rec.get("measuredDate", ""))[:7]
        if len(month) != 7:
            continue
        sid = int(rec.get("siteId") or 0)
        sites.setdefault(
            sid,
            {
                "id": sid,
                "name": rec.get("siteName") or f"site {sid}",
                "lat": lat,
                "lon": lon,
                "months": set(),
            },
        )
        cell = per.setdefault((sid, month), {"sum": 0.0, "n": 0, "days": 0, "dates": set()})
        cell["sum"] += v
        cell["n"] += 1
        cell["days"] += days
        cell["dates"].add(rec.get("measuredDate"))

    site_month: dict[str, list[float]] = {}
    for (sid, month), c in per.items():
        if quantity == "precip":
            y, m = int(month[:4]), int(month[5:])
            dim = calendar.monthrange(y, m)[1]
            covered = min(c["days"], dim)
            if covered < MIN_COVERED_DAYS_PRECIP:
                continue
            value = c["sum"] * dim / covered
        else:
            if len(c["dates"]) < MIN_DAYS_PER_SITE_MONTH:
                continue
            value = c["sum"] / c["n"]
        site_month.setdefault(month, []).append(value)
        sites[sid]["months"].add(month)

    months = sorted(site_month)
    return {
        "months": months,
        "values": [float(np.mean(site_month[m])) for m in months],
        "n_sites": [len(site_month[m]) for m in months],
        "sites": sorted(
            (
                {**{k: v for k, v in s.items() if k != "months"}, "n_months": len(s["months"])}
                for s in sites.values()
                if s["months"]
            ),
            key=lambda s: -s["n_months"],
        ),
    }


def anomalies(months: list[str], values: list[float]) -> np.ndarray:
    v = np.asarray(values, float)
    cal = np.array([int(m[5:7]) for m in months])
    out = np.full_like(v, np.nan)
    for c in range(1, 13):
        sel = (cal == c) & np.isfinite(v)
        if sel.sum() >= 2:
            out[sel] = v[sel] - v[sel].mean()
    return out


def compare_with_satellite(globe: dict, sat_months: list[str], sat_values: list[float | None]) -> dict:
    """Monthly anomalies of both series over the months they share, and their correlation."""
    sat = {m: v for m, v in zip(sat_months, sat_values, strict=True) if v is not None}
    shared = [m for m in globe["months"] if m in sat]
    g = [globe["values"][globe["months"].index(m)] for m in shared]
    s = [sat[m] for m in shared]
    ga, sa = anomalies(shared, g), anomalies(shared, s)
    ok = np.isfinite(ga) & np.isfinite(sa)
    r = float(np.corrcoef(ga[ok], sa[ok])[0, 1]) if ok.sum() >= 12 else None
    return {
        "months": shared,
        "globe_anomaly": [None if not np.isfinite(x) else float(x) for x in ga],
        "satellite_anomaly": [None if not np.isfinite(x) else float(x) for x in sa],
        "n_shared": int(ok.sum()),
        "anomaly_correlation": r,
    }


# --------------------------------------------------------------------------------------
# Cache and entry point
# --------------------------------------------------------------------------------------

CACHE_SQL = """CREATE TABLE IF NOT EXISTS globe_cache (
    key TEXT PRIMARY KEY, fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(), payload JSONB NOT NULL)"""


def _cache_get(conn, key: str):
    conn.execute(CACHE_SQL)
    r = conn.execute(
        "SELECT payload FROM globe_cache WHERE key = %s AND fetched_at > now() - make_interval(days => %s)",
        (key, CACHE_DAYS),
    ).fetchone()
    return r["payload"] if r else None


def _cache_put(conn, key: str, payload: dict) -> None:
    conn.execute(
        "INSERT INTO globe_cache (key, payload) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET payload = EXCLUDED.payload, fetched_at = now()",
        (key, json.dumps(payload)),
    )
    conn.commit()


def ground_context(conn, analysis: dict, fetch=None) -> dict:
    """GLOBE observations beside a stored trend analysis."""
    fetch = fetch or fetch_observations  # resolved at call time (tests replace it)
    var = analysis["variable"]["id"]
    pairing = PAIRINGS.get(var)
    if pairing is None:
        raise GlobeError(f"No GLOBE protocol is paired with {analysis['variable']['name'].lower()} yet.")
    region = analysis["region"]
    w, s, e, n = region["bbox"]
    span_lon = (e - w) if e >= w else (e + 360 - w)
    if span_lon > MAX_SPAN_DEG or (n - s) > MAX_SPAN_DEG:
        raise GlobeError(
            f"Ground observations are fetched for regions up to {MAX_SPAN_DEG:g}° across; choose a smaller place."
        )
    months = analysis["monthly"]["labels"]
    end = dt.date.today()
    first = dt.date(int(months[0][:4]), 1, 1) if months else end
    start = max(first, dt.date(end.year - MAX_YEARS + 1, 1, 1), dt.date(1995, 1, 1))  # GLOBE began in 1995

    key = hashlib.sha256(
        json.dumps(
            [
                pairing.protocol,
                pairing.quantity,
                region.get("id"),
                region["bbox"],
                start.isoformat(),
                end.year,
            ],
            sort_keys=True,
        ).encode()
    ).hexdigest()[:32]
    cached = _cache_get(conn, key)
    if cached is None:
        boxes = [[w, s, 180.0, n], [-180.0, s, e, n]] if e < w else [[w, s, e, n]]
        records = []
        for b in boxes:
            records.extend(fetch(pairing.protocol, b, start, end))
        inside = None
        if region.get("geometry"):
            import shapely
            from shapely.geometry import Point, shape

            geom = shape(region["geometry"])
            shapely.prepare(geom)
            inside = lambda lat, lon: geom.covers(Point(lon, lat))  # noqa: E731
        cached = monthly_series(records, pairing.quantity, inside)
        cached["n_records"] = len(records)
        _cache_put(conn, key, cached)

    cmp = compare_with_satellite(cached, months, analysis["monthly"]["values"])
    return {
        "variable": var,
        "protocol": pairing.protocol,
        "label": pairing.label,
        "units": pairing.units,
        "period": [start.isoformat(), end.isoformat()],
        "globe": {k: cached[k] for k in ("months", "values", "n_sites")},
        "sites": cached["sites"][:200],
        "n_sites": len(cached["sites"]),
        "n_records": cached.get("n_records"),
        "comparison": cmp,
        "caveats": CAVEATS,
        "source": "NASA GLOBE Program (https://www.globe.gov), GLOBE API",
    }
