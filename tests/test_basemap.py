"""The base-map relay: only the files the style names, addresses rewritten, copies kept on disk.

No network: the upstream download is replaced by a fake that records what was asked for.
"""

from __future__ import annotations

import gzip
import json
import os
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from megavir.api import basemap
from megavir.api.main import app
from megavir.config import settings

UP = "https://tiles.example.org"
STYLE = {
    "version": 8,
    "sprite": f"{UP}/sprites/ofm_f384/ofm",
    "glyphs": f"{UP}/fonts/{{fontstack}}/{{range}}.pbf",
    "sources": {
        "openmaptiles": {"type": "vector", "url": f"{UP}/planet"},
        "ne2_shaded": {"type": "raster", "tiles": [f"{UP}/natural_earth/ne2sr/{{z}}/{{x}}/{{y}}.png"]},
    },
    "layers": [{"id": "background", "type": "background"}],
}
TILEJSON = {
    "tilejson": "3.0.0",
    "tiles": [f"{UP}/planet/20261101_080013_pt/{{z}}/{{x}}/{{y}}.pbf"],
    "attribution": '<img src=x onerror="alert(1)">',
}


@pytest.fixture
def relay(monkeypatch, tmp_path):
    s = settings()
    monkeypatch.setattr(s, "basemap_url", UP)
    monkeypatch.setattr(s, "basemap_public_path", "/api/basemap")
    monkeypatch.setattr(basemap, "cache_root", lambda: tmp_path / "basemap")
    calls: list[str] = []
    files = {
        f"{UP}/styles/liberty": json.dumps(STYLE).encode(),
        f"{UP}/planet": json.dumps(TILEJSON).encode(),
        f"{UP}/planet/20261101_080013_pt/3/4/2.pbf": b"\x1a\x02vector",
        f"{UP}/fonts/Noto%20Sans%20Regular/0-255.pbf": b"glyphs",
        f"{UP}/sprites/ofm_f384/ofm@2x.png": b"\x89PNG",
    }
    state = {"down": False}

    def fake(url: str):
        calls.append(url)
        if state["down"]:
            raise httpx.ConnectError("offline")
        return (200, files[url]) if url in files else (404, b"")

    monkeypatch.setattr(basemap, "_download", fake)
    return TestClient(app, client=("203.0.113.9", 50000)), calls, state, tmp_path


def test_style_points_every_address_here_and_is_kept(relay):
    client, calls, _, _ = relay
    r = client.get("/basemap/style/light")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    style = r.json()
    assert UP not in r.text
    assert style["sources"]["openmaptiles"]["url"] == "/api/basemap/planet"
    assert style["glyphs"] == "/api/basemap/fonts/{fontstack}/{range}.pbf"
    assert style["sprite"] == "/api/basemap/sprites/ofm_f384/ofm"
    assert client.get("/basemap/style/light").json() == style
    assert calls == [f"{UP}/styles/liberty"]  # the second visitor got the stored copy
    assert client.get("/basemap/style/sepia").status_code == 404


def test_tile_index_rewritten_with_our_attribution(relay):
    client, _, _, _ = relay
    doc = client.get("/basemap/planet").json()
    assert doc["tiles"] == ["/api/basemap/planet/20261101_080013_pt/{z}/{x}/{y}.pbf"]
    assert "onerror" not in doc["attribution"] and "OpenStreetMap" in doc["attribution"]


def test_tiles_fonts_and_icons_are_relayed_compressed(relay):
    client, calls, _, _ = relay
    r = client.get("/basemap/planet/20261101_080013_pt/3/4/2.pbf")
    assert r.status_code == 200 and r.content == b"\x1a\x02vector"
    assert r.headers["content-type"] == "application/x-protobuf"
    assert r.headers["content-encoding"] == "gzip" and "max-age" in r.headers["cache-control"]
    raw = client.get("/basemap/planet/20261101_080013_pt/3/4/2.pbf", headers={"Accept-Encoding": "identity"})
    assert raw.content == b"\x1a\x02vector" and "content-encoding" not in raw.headers
    assert client.get("/basemap/fonts/Noto Sans Regular/0-255.pbf").content == b"glyphs"
    assert client.get("/basemap/sprites/ofm_f384/ofm@2x.png").headers["content-type"] == "image/png"
    assert f"{UP}/fonts/Noto%20Sans%20Regular/0-255.pbf" in calls
    # an empty area of the world: no tile upstream, so an empty answer the map understands
    assert client.get("/basemap/planet/20261101_080013_pt/3/1/1.pbf").status_code == 204


@pytest.mark.parametrize(
    "path",
    [
        "styles/liberty",  # styles only through /style/{theme}
        "planet/v1/15/0/0.pbf",  # deeper than the tiles go
        "planet/v1/3/8/0.pbf",  # x outside the zoom level
        "natural_earth/ne2sr/7/0/0.png",
        "fonts/../../etc/passwd/0-255.pbf",
        "planet/../../secret",
        "data/v3.json",
        "sprites/ofm/ofm.svg",
    ],
)
def test_other_paths_are_refused(relay, path):
    client, calls, _, _ = relay
    assert client.get(f"/basemap/{path}").status_code == 404
    assert calls == []


def test_upstream_down_uses_a_stored_copy(relay):
    client, calls, state, tmp = relay
    assert client.get("/basemap/planet").status_code == 200
    stored = tmp / "basemap" / "planet.json.gz"
    old = time.time() - 2 * basemap.FRESH["tilejson"]
    os.utime(stored, (old, old))
    state["down"] = True
    assert client.get("/basemap/planet").json()["tiles"][0].startswith("/api/basemap/")
    assert client.get("/basemap/sprites/ofm_f384/ofm@2x.png").status_code == 502
    assert len(calls) == 3


def test_turned_off(relay, monkeypatch):
    client, calls, _, _ = relay
    monkeypatch.setattr(settings(), "basemap_url", "")
    assert client.get("/basemap/style/light").status_code == 404
    assert client.get("/basemap/planet").status_code == 404
    assert calls == []


def test_stored_copies_stay_under_the_cap(relay, monkeypatch):
    _, _, _, tmp = relay
    monkeypatch.setattr(settings(), "basemap_cache_mb", 1)
    root = tmp / "basemap" / "planet" / "v"
    root.mkdir(parents=True)
    for i in range(12):
        p = root / f"{i}.pbf.gz"
        p.write_bytes(gzip.compress(os.urandom(200_000)))
        os.utime(p, (1_000_000 + i, 1_000_000 + i))
    basemap._prune()
    left = sorted(int(p.name.split(".")[0]) for p in root.iterdir())
    assert sum(p.stat().st_size for p in root.iterdir()) <= 0.8 * 1024 * 1024
    assert left == list(range(12 - len(left), 12))  # the oldest went first
