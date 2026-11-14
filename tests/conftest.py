"""Shared fixtures.  API tests run on a small synthetic store in a separate test database.

MEGAVIR_TEST_DATABASE_URL (default: the local development container's megavir_test database)
is set as the app's database before anything imports the settings.  Tests that need the
database are skipped when it is not reachable.
"""

from __future__ import annotations

import json
import os

import pytest

TEST_DB = os.environ.get(
    "MEGAVIR_TEST_DATABASE_URL", "postgresql://megavir:megavir@localhost:5433/megavir_test"
)
os.environ["MEGAVIR_DATABASE_URL"] = TEST_DB
os.environ.setdefault("MEGAVIR_ALLOWED_ORIGINS", '["http://localhost:3000"]')
os.environ["MEGAVIR_SERVE_KINDS"] = '["synthetic"]'
os.environ["MEGAVIR_AI_PROVIDER"] = "none"


def _db_ok() -> bool:
    try:
        import psycopg

        with psycopg.connect(TEST_DB, connect_timeout=3):
            return True
    except Exception:  # noqa: BLE001
        return False


TEST_PLACES = [
    # id, name, kind, context, lat, lon, population, bbox, geometry
    (
        "country:TST",
        "Testland",
        "country",
        "Test continent",
        30.0,
        -92.5,
        1000,
        [-97.0, 26.0, -88.0, 34.0],
        {"type": "Polygon", "coordinates": [[[-97, 26], [-88, 26], [-88, 34], [-97, 34], [-97, 26]]]},
    ),
    (
        "admin1:TS-W",
        "West Testshire",
        "admin1",
        "State, Testland",
        30.0,
        -95.0,
        0,
        [-97.0, 26.0, -93.0, 34.0],
        {"type": "Polygon", "coordinates": [[[-97, 26], [-93, 26], [-93, 34], [-97, 34], [-97, 26]]]},
    ),
    (
        "admin1:TS-E",
        "East Testshire",
        "admin1",
        "State, Testland",
        30.0,
        -90.0,
        0,
        [-92.0, 26.0, -88.0, 34.0],
        {"type": "Polygon", "coordinates": [[[-92, 26], [-88, 26], [-88, 34], [-92, 34], [-92, 26]]]},
    ),
    (
        "city:1",
        "Testville",
        "city",
        "West Testshire, Testland",
        30.0,
        -95.0,
        50000,
        [-95.5, 29.5, -94.5, 30.5],
        None,
    ),
]


@pytest.fixture(scope="session")
def db():
    if not _db_ok():
        pytest.skip("test database not reachable")
    from megavir.ingest.synthetic import build_synthetic
    from megavir.places.load import normalise
    from megavir.places.presets import PRESETS
    from megavir.store import direct_connect, init_schema

    conn = direct_connect(TEST_DB)
    init_schema(conn)
    conn.execute("TRUNCATE grid_version, grid_tile, analysis, place, ai_usage CASCADE")
    conn.commit()
    build_synthetic(conn, years=24)
    for pid, name, kind, ctx, lat, lon, pop, bbox, geom in TEST_PLACES:
        conn.execute(
            "INSERT INTO place (id, name, kind, context, lat, lon, population, bbox, geometry, search) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (pid, name, kind, ctx, lat, lon, pop, bbox, json.dumps(geom) if geom else None, normalise(name)),
        )
    for p in PRESETS[:5]:
        conn.execute(
            "INSERT INTO place (id, name, kind, context, lat, lon, population, bbox, search) VALUES (%s,%s,'preset',%s,0,0,0,%s,%s)",
            (f"preset:{p['id']}", p["name"], p["group"], [float(x) for x in p["bbox"]], normalise(p["name"])),
        )
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def client(db):
    from fastapi.testclient import TestClient

    from megavir.api.main import app

    return TestClient(app)


ORIGIN = {"Origin": "http://localhost:3000"}
