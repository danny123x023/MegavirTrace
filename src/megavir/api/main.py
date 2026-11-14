"""MegavirTrace HTTP API (FastAPI).

| Endpoint                                   | Purpose                                         |
| GET  /variables, /datasets                 | catalog: definitions, units, sources, records   |
| GET  /places/search?q=, /places/{id}       | place search and outlines                       |
| GET  /places/presets                       | curated preset regions                          |
| POST /analysis/trend                       | one region: series, statistics, verdict, map    |
| POST /analysis/compare                     | two regions and the difference test             |
| POST /analysis/scan, GET /analysis/opposites | every variable for one place; opposite trends |
| GET  /analysis/month                       | how unusual one month was (exploratory)         |
| POST /ai/ask, /ai/explain                  | AI scientist (explain takes an analysis id)     |
| GET  /reports/{id}, /reports/{id}/export   | saved results; CSV, Excel, PDF, notebook        |
| GET  /v1/...  (public: /api/v1/...)        | documented, read-only, rate-limited data API    |
"""

from __future__ import annotations

import math
import os

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from megavir.catalog import DATASETS, PLANNED_DATASETS
from megavir.places.load import normalise
from megavir.places.presets import PRESETS
from megavir.store import connect

from . import service
from .security import OriginAndHeaders

app = FastAPI(
    title="MegavirTrace API",
    version=service.ENGINE_VERSION,
    description="Honest, checkable Earth-system trends from NASA data. Every number comes from one deterministic engine.",
    docs_url="/docs",
    root_path=os.environ.get("MEGAVIR_ROOT_PATH", ""),
    openapi_url="/openapi.json",
)
app.add_middleware(OriginAndHeaders)


@app.exception_handler(service.AnalysisError)
async def _analysis_error(_: Request, exc: service.AnalysisError):
    return JSONResponse({"detail": str(exc)}, status_code=422)


# --------------------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------------------


class RegionIn(BaseModel):
    place: str | None = Field(None, max_length=80)
    bbox: list[float] | None = Field(None, min_length=4, max_length=4)
    name: str | None = Field(None, max_length=80)


class TrendIn(BaseModel):
    variable: str = Field(max_length=40)
    region: RegionIn
    mode: str | None = None  # default: the variable's own (monthly for gappy records)
    season: str | None = None
    start_year: int | None = Field(None, ge=1850, le=2100)
    end_year: int | None = Field(None, ge=1850, le=2100)
    cell_map: bool = True
    lang: str = "en"


class CompareIn(BaseModel):
    variable: str = Field(max_length=40)
    region_a: RegionIn
    region_b: RegionIn
    mode: str | None = None  # default: the variable's own (monthly for gappy records)
    season: str | None = None
    start_year: int | None = Field(None, ge=1850, le=2100)
    end_year: int | None = Field(None, ge=1850, le=2100)
    lang: str = "en"


class ScanIn(BaseModel):
    region: RegionIn
    lang: str = "en"


def _region(r: RegionIn) -> dict:
    return {k: v for k, v in r.model_dump().items() if v is not None}


# --------------------------------------------------------------------------------------
# Catalog
# --------------------------------------------------------------------------------------


@app.get("/health")
def health():
    with connect() as conn:
        n = conn.execute("SELECT count(*) AS n FROM grid_version WHERE active").fetchone()["n"]
    return {"ok": True, "active_grids": n, "engine": service.ENGINE_VERSION}


@app.get("/variables")
def variables():
    with connect() as conn:
        return service.catalog_with_status(conn)


@app.get("/datasets")
def datasets():
    return {
        "available": [d.__dict__ for d in DATASETS.values()],
        "planned": [d.__dict__ for d in PLANNED_DATASETS.values()],
    }


# --------------------------------------------------------------------------------------
# Places
# --------------------------------------------------------------------------------------


@app.get("/places/search")
def places_search(q: str = Query(min_length=1, max_length=80), limit: int = Query(10, ge=1, le=25)):
    nq = normalise(q)
    if not nq:
        return {"results": []}
    with connect() as conn:
        if len(nq) < 3:
            rows = conn.execute(
                """SELECT id, name, kind, context, lat, lon, bbox, population FROM place
                   WHERE search LIKE %(p)s
                   ORDER BY (lower(name) = %(q)s) DESC, (kind IN ('country','preset')) DESC, population DESC
                   LIMIT %(n)s""",
                {"p": nq + "%", "q": nq, "n": limit},
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, name, kind, context, lat, lon, bbox, population,
                          similarity(search, %(q)s) AS sim,
                          (search LIKE %(p)s) AS prefix,
                          (lower(unaccent(name)) = %(q)s) AS exact
                   FROM place
                   WHERE search %% %(q)s OR search LIKE %(p)s OR search LIKE %(w)s
                   ORDER BY exact DESC,
                            (CASE WHEN search LIKE %(p)s THEN 0.5 ELSE 0 END) + similarity(search, %(q)s)
                            + (CASE kind WHEN 'country' THEN 0.25 WHEN 'preset' THEN 0.2 WHEN 'admin1' THEN 0.15 ELSE 0 END)
                            + ln(population + 1) / 60 DESC
                   LIMIT %(n)s""",
                {"q": nq, "p": nq + "%", "w": "% " + nq + "%", "n": limit},
            ).fetchall()
    return {
        "results": [
            {k: r[k] for k in ("id", "name", "kind", "context", "lat", "lon", "bbox", "population")}
            for r in rows
        ]
    }


@app.get("/places/presets")
def places_presets():
    groups: dict[str, list] = {}
    for p in PRESETS:
        groups.setdefault(p["group"], []).append(
            {"id": f"preset:{p['id']}", "name": p["name"], "bbox": p["bbox"], "try": p["try"]}
        )
    return {"groups": [{"name": k, "presets": v} for k, v in groups.items()], "count": len(PRESETS)}


@app.get("/places/{place_id}")
def place(place_id: str):
    with connect() as conn:
        r = conn.execute(
            "SELECT id, name, kind, context, lat, lon, bbox, population, geometry FROM place WHERE id = %s",
            (place_id,),
        ).fetchone()
    if not r:
        raise HTTPException(404, "unknown place")
    return dict(r)


# --------------------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------------------


@app.post("/analysis/trend")
def analysis_trend(body: TrendIn):
    req = body.model_dump()
    req["region"] = _region(body.region)
    with connect() as conn:
        return service.run_trend(conn, req)


@app.post("/analysis/compare")
def analysis_compare(body: CompareIn):
    req = body.model_dump()
    req["region_a"], req["region_b"] = _region(body.region_a), _region(body.region_b)
    with connect() as conn:
        return service.run_compare(conn, req)


@app.post("/analysis/scan")
def analysis_scan(body: ScanIn):
    with connect() as conn:
        return service.run_scan(conn, {"region": _region(body.region), "lang": body.lang})


@app.get("/analysis/opposites")
def analysis_opposites(variable: str = Query(max_length=40), mode: str = "annual", lang: str = "en"):
    with connect() as conn:
        return service.run_opposites(conn, variable, mode=mode, lang=lang)


@app.get("/analysis/month")
def analysis_month(
    variable: str,
    year: int,
    month: int = Query(ge=1, le=12),
    place: str | None = None,
    west: float | None = None,
    south: float | None = None,
    east: float | None = None,
    north: float | None = None,
):
    region = {"place": place} if place else {"bbox": [west, south, east, north]}
    with connect() as conn:
        return service.month_detail(conn, variable, region, year, month)


# --------------------------------------------------------------------------------------
# Reports and exports
# --------------------------------------------------------------------------------------


@app.get("/reports/{rid}")
def report(rid: str):
    with connect() as conn:
        r = service.get_report(conn, rid)
    if not r:
        raise HTTPException(404, "unknown report")
    return r["result"]


@app.get("/reports/{rid}/export")
def report_export(rid: str, format: str = Query("csv", pattern="^(csv|xlsx|pdf|ipynb|json)$")):
    from megavir.exports import export_report

    with connect() as conn:
        r = service.get_report(conn, rid)
    if not r:
        raise HTTPException(404, "unknown report")
    content, media, filename = export_report(r["result"], format)
    return Response(
        content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


# --------------------------------------------------------------------------------------
# Context beside the observed trend: NASA GLOBE ground observations (FR14)
# --------------------------------------------------------------------------------------


@app.get("/context/globe")
def context_globe(analysis_id: str = Query(min_length=8, max_length=64)):
    from megavir.context.globe import GlobeError, ground_context

    with connect() as conn:
        rep = service.get_report(conn, analysis_id)
        if not rep or rep["result"].get("kind") != "trend":
            raise HTTPException(404, "unknown trend analysis")
        try:
            return ground_context(conn, rep["result"])
        except GlobeError as e:
            raise HTTPException(422, str(e)) from None
        except httpx.HTTPError:
            raise HTTPException(
                502, "The GLOBE service could not be reached; please try again later."
            ) from None


# --------------------------------------------------------------------------------------
# AI scientist (optional; never computes)
# --------------------------------------------------------------------------------------


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=600)
    lang: str = "en"
    mode: str = Field("explain", pattern="^(explain|tutor)$")
    history: list[dict] = Field(default_factory=list, max_length=8)


class ExplainIn(BaseModel):
    analysis_id: str = Field(min_length=8, max_length=64)
    lang: str = "en"


@app.post("/ai/ask")
def ai_ask(body: AskIn, request: Request):
    from megavir.ai import ask
    from megavir.api.security import client_ip

    return ask(body.question, body.lang, body.mode, body.history, client_ip(request))


@app.post("/ai/explain")
def ai_explain(body: ExplainIn, request: Request):
    from megavir.ai import explain
    from megavir.api.security import client_ip

    return explain(body.analysis_id, body.lang, client_ip(request))


@app.get("/ai/status")
def ai_status():
    from megavir.ai import status

    return status()


# --------------------------------------------------------------------------------------
# Open data API (FR17): read-only, documented, rate-limited
# --------------------------------------------------------------------------------------


@app.get("/v1/trend")
def api_trend(
    variable: str,
    place: str | None = None,
    west: float | None = None,
    south: float | None = None,
    east: float | None = None,
    north: float | None = None,
    mode: str | None = None,
    season: str | None = None,
):
    """Trend card data for one region (no cell map).  Same engine and cache as the app."""
    if place:
        region = {"place": place}
    elif None not in (west, south, east, north):
        region = {"bbox": [west, south, east, north]}
    else:
        raise HTTPException(422, "give place=... or west/south/east/north")
    with connect() as conn:
        r = service.run_trend(
            conn, {"variable": variable, "region": region, "mode": mode, "season": season, "cell_map": False}
        )
    return {
        "id": r["id"],
        "variable": r["variable"]["id"],
        "region": {k: r["region"][k] for k in ("id", "name", "kind", "bbox")},
        "units": r["units"],
        "headline": r["verdict"]["headline"],
        "status": r["verdict"]["status"],
        "per_decade": r["stats"]["per_decade"],
        "p_mann_kendall": r["stats"]["mk"]["p"],
        "p_least_squares": r["stats"]["ols"]["p"],
        "series": {"labels": r["series"]["labels"], "values": r["series"]["values"]},
        "provenance": r["provenance"],
        "caveats": r["verdict"]["caveats"],
    }


@app.get("/v1/variables")
def api_variables():
    return variables()


def run() -> None:
    import uvicorn

    uvicorn.run("megavir.api.main:app", host="127.0.0.1", port=8000, workers=2, proxy_headers=False)


def _finite(x):
    return x if (x is None or (isinstance(x, float) and math.isfinite(x))) else None
