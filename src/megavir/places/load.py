"""Load places (FR3) and the land mask into PostgreSQL.

Sources (public, downloaded by ``megavir-ingest places --download``):
* GeoNames cities15000 (cities with 15,000+ people), countryInfo, admin1 codes — CC BY 4.0;
* Natural Earth 1:50m countries and 1:10m states/provinces, 1:50m land — public domain.
"""

from __future__ import annotations

import csv
import json
import sys
import unicodedata
from pathlib import Path

import numpy as np
import shapefile  # pyshp
import shapely
from shapely.geometry import mapping, shape

from megavir.store import GridSpec, write_mask

from .presets import PRESETS

csv.field_size_limit(sys.maxsize)

CITY_HALF_BOX = 0.5  # a city is analysed as a 1 deg x 1 deg box around it


def normalise(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().replace("-", " ").replace("'", "").split())


def _shapes(path: Path):
    with shapefile.Reader(str(path), encoding="utf-8", encodingErrors="replace") as r:
        fields = [f[0] for f in r.fields[1:]]
        for sr in r.iterShapeRecords():
            rec = dict(zip(fields, sr.record, strict=False))
            geo = sr.shape.__geo_interface__
            if not geo.get("coordinates"):
                continue
            yield rec, geo


def _simplify(geo: dict, tol: float) -> tuple[dict, list[float]]:
    g = shape(geo)
    if not g.is_valid:
        g = shapely.make_valid(g)
    gs = g.simplify(tol, preserve_topology=True)
    if gs.is_empty:
        gs = g
    gs = shapely.set_precision(gs, 0.001)
    return mapping(gs), list(g.bounds)


def place_rows(raw: Path) -> list[tuple]:
    rows: list[tuple] = []
    countries: dict[str, str] = {}
    for line in (raw / "geonames" / "countryInfo.txt").read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        f = line.split("\t")
        countries[f[0]] = f[4]
    admin1: dict[str, str] = {}
    for line in (raw / "geonames" / "admin1CodesASCII.txt").read_text(encoding="utf-8").splitlines():
        f = line.split("\t")
        if len(f) >= 2:
            admin1[f[0]] = f[1]

    # countries with real outlines
    for rec, geo in _shapes(raw / "ne_countries" / "ne_50m_admin_0_countries.shp"):
        code = rec.get("ADM0_A3") or rec.get("ISO_A3")
        name = rec.get("NAME") or rec.get("ADMIN")
        g, bbox = _simplify(geo, 0.02)
        lat = float(rec.get("LABEL_Y") or (bbox[1] + bbox[3]) / 2)
        lon = float(rec.get("LABEL_X") or (bbox[0] + bbox[2]) / 2)
        alt = " ".join(
            normalise(str(rec.get(k) or "")) for k in ("NAME_LONG", "ADMIN", "FORMAL_EN", "NAME_ES")
        )
        rows.append(
            (
                f"country:{code}",
                name,
                "country",
                rec.get("CONTINENT") or "",
                lat,
                lon,
                int(rec.get("POP_EST") or 0),
                bbox,
                json.dumps(g),
                (normalise(name) + " " + alt).strip(),
            )
        )

    # states and provinces with real outlines
    for rec, geo in _shapes(raw / "ne_admin1" / "ne_10m_admin_1_states_provinces.shp"):
        name = rec.get("name") or rec.get("name_en")
        if not name:
            continue
        code = rec.get("iso_3166_2") or rec.get("adm1_code")
        if not code or code.endswith("~"):
            code = rec.get("adm1_code")
        g, bbox = _simplify(geo, 0.01)
        ctx = rec.get("admin") or ""
        kind_word = rec.get("type_en") or ""
        lat = float(rec.get("latitude") or (bbox[1] + bbox[3]) / 2)
        lon = float(rec.get("longitude") or (bbox[0] + bbox[2]) / 2)
        alt = normalise(str(rec.get("name_en") or ""))
        rows.append(
            (
                f"admin1:{code}",
                name,
                "admin1",
                f"{kind_word + ', ' if kind_word else ''}{ctx}",
                lat,
                lon,
                0,
                bbox,
                json.dumps(g),
                (normalise(name) + " " + alt + " " + normalise(ctx)).strip(),
            )
        )

    # cities (box around each)
    with open(raw / "geonames" / "cities15000.txt", encoding="utf-8", newline="") as fh:
        for f in csv.reader(fh, delimiter="\t", quoting=csv.QUOTE_NONE):
            gid, name, ascii_name = f[0], f[1], f[2]
            lat, lon = float(f[4]), float(f[5])
            cc, a1, pop = f[8], f[10], int(f[14] or 0)
            ctx = ", ".join(x for x in (admin1.get(f"{cc}.{a1}", ""), countries.get(cc, cc)) if x)
            w, e = lon - CITY_HALF_BOX, lon + CITY_HALF_BOX
            if w < -180:
                w += 360
            if e > 180:
                e -= 360
            bbox = [w, max(-90, lat - CITY_HALF_BOX), e, min(90, lat + CITY_HALF_BOX)]
            rows.append(
                (
                    f"city:{gid}",
                    name,
                    "city",
                    ctx,
                    lat,
                    lon,
                    pop,
                    bbox,
                    None,
                    (normalise(name) + (" " + normalise(ascii_name) if ascii_name != name else "")).strip(),
                )
            )

    for p in PRESETS:
        w, s, e, n = p["bbox"]
        lat = (s + n) / 2
        lon = (w + e) / 2 if w <= e else ((w + e + 360) / 2 + 180) % 360 - 180
        rows.append(
            (
                f"preset:{p['id']}",
                p["name"],
                "preset",
                p["group"],
                lat,
                lon,
                0,
                p["bbox"],
                None,
                normalise(p["name"] + " " + p["group"]),
            )
        )
    return rows


def load_places(conn, raw: Path) -> int:
    rows = place_rows(raw)
    with conn.transaction():
        conn.execute("DELETE FROM place")
        with conn.cursor() as cur:
            with cur.copy(
                "COPY place (id, name, kind, context, lat, lon, population, bbox, geometry, search) FROM STDIN"
            ) as cp:
                seen = set()
                for r in rows:
                    if r[0] in seen:
                        continue
                    seen.add(r[0])
                    r = list(r)
                    r[7] = [float(x) for x in r[7]]  # bbox as float8[]
                    cp.write_row(r)
    return len(seen)


# --------------------------------------------------------------------------------------
# Land fraction mask
# --------------------------------------------------------------------------------------


def land_fraction(spec: GridSpec, land) -> np.ndarray:
    """Fraction of each cell that is land, band by band to keep memory small."""
    out = np.zeros((spec.ny, spec.nx), np.float32)
    half = spec.res / 2
    shapely.prepare(land)
    for i, lat in enumerate(spec.lats):
        boxes = shapely.box(spec.lons - half, lat - half, spec.lons + half, lat + half)
        hit = shapely.intersects(land, boxes)
        if not hit.any():
            continue
        inside = np.zeros(spec.nx, bool)
        inside[hit] = shapely.contains_properly(land, boxes[hit])
        frac = np.zeros(spec.nx)
        frac[inside] = 1.0
        edge = hit & ~inside
        if edge.any():
            frac[edge] = shapely.area(shapely.intersection(boxes[edge], land)) / (spec.res * spec.res)
        out[i] = np.clip(frac, 0, 1)
    return out


def load_land_masks(conn, raw: Path, resolutions=(0.5, 1.0, 2.0)) -> dict:
    polys = [shape(geo) for _, geo in _shapes(raw / "ne_land" / "ne_50m_land.shp")]
    land = shapely.union_all([p if p.is_valid else shapely.make_valid(p) for p in polys])
    report = {}
    for res in resolutions:
        spec = GridSpec.global_grid(res)
        lf = land_fraction(spec, land)
        write_mask(conn, "land", spec, lf)
        w = np.cos(np.deg2rad(spec.lats))[:, None]
        report[res] = float((lf * w).sum() / (w.sum() * spec.nx))
    return report  # area share of land, about 0.29
