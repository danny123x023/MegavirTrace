"""Detailed base map (OpenStreetMap data), served from this origin.

The browser never talks to a map server directly.  These routes fetch the map style, vector tiles,
fonts and icons from one upstream (OpenFreeMap by default: free, no key, OpenStreetMap data), keep a
copy on disk and rewrite the upstream address to ours.  So visitors' addresses and the places they
look at stay here, the page keeps its strict Content-Security-Policy (connect-src 'self'), and a
tile fetched once is served from disk afterwards.

MEGAVIR_BASEMAP_URL="" turns it off: the map then shows the built-in country outlines only.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import threading
import time
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from megavir.config import settings

router = APIRouter(prefix="/basemap", tags=["base map"])

USER_AGENT = "MegavirTrace/0.1 (NASA Space Apps open-source project)"
DAY = 86_400

# What may be fetched, and how: (pattern, kind, highest zoom).  Anything else is a 404, so the
# relay cannot be pointed at other paths of the upstream (or at other hosts: the host is fixed).
PATHS = [
    (re.compile(r"planet"), "tilejson", None),
    (re.compile(r"planet/[A-Za-z0-9_]{1,40}/(\d{1,2})/(\d{1,5})/(\d{1,5})\.pbf"), "tile", 14),
    (re.compile(r"natural_earth/ne2sr/(\d{1,2})/(\d{1,5})/(\d{1,5})\.png"), "tile", 6),
    (re.compile(r"fonts/[A-Za-z0-9 ,_-]{1,120}/\d{1,5}-\d{1,5}\.pbf"), "font", None),
    (re.compile(r"sprites/[A-Za-z0-9_]{1,40}/[A-Za-z0-9_]{1,40}(@2x)?\.(json|png)"), "sprite", None),
]
# how long a stored copy is used before asking the upstream again (tile paths carry the data
# version, so a stored tile never goes stale; the style and tile index change when data is rebuilt)
FRESH = {"style": 6 * 3600, "tilejson": 6 * 3600, "tile": 30 * DAY, "font": 30 * DAY, "sprite": 7 * DAY}
BROWSER_CACHE = {"style": 3600, "tilejson": 3600, "tile": 7 * DAY, "font": 30 * DAY, "sprite": DAY}
TYPES = {".pbf": "application/x-protobuf", ".png": "image/png", ".json": "application/json"}

_upstream_slots = threading.BoundedSemaphore(6)  # be polite: at most 6 downloads at once
_locks = [threading.Lock() for _ in range(64)]  # one download per file, however many ask at once
_writes = 0
_client: httpx.Client | None = None


def upstream() -> str:
    return settings().basemap_url.rstrip("/")


def cache_root() -> Path:
    return Path(settings().data_dir) / "basemap"


def _http() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(
            timeout=httpx.Timeout(15.0, connect=5.0),
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=8),
        )
    return _client


def _download(url: str) -> tuple[int, bytes]:
    """GET one upstream file.  Replaced in tests; never called with an unchecked path."""
    with _upstream_slots:
        r = _http().get(url)
    return r.status_code, r.content


def classify(path: str) -> str:
    """The kind of an allowed upstream path, or HTTPException(404)."""
    for pattern, kind, max_zoom in PATHS:
        m = pattern.fullmatch(path)
        if not m:
            continue
        if max_zoom is not None:
            z, x, y = (int(g) for g in m.groups())
            if z > max_zoom or x >= 2**z or y >= 2**z:
                break
        return kind
    raise HTTPException(404, "not a base-map file")


def _rewrite(raw: bytes, kind: str) -> bytes:
    """Point every upstream address in a style or tile index at this server."""
    text = raw.decode("utf-8").replace(upstream(), settings().basemap_public_path.rstrip("/"))
    if kind == "tilejson":
        doc = json.loads(text)
        doc["attribution"] = settings().basemap_attribution  # ours, not upstream HTML
        text = json.dumps(doc, separators=(",", ":"))
    return text.encode("utf-8")


def _store_path(key: str) -> Path:
    root = cache_root()
    p = (root / key).resolve()
    if root.resolve() not in p.parents:
        raise HTTPException(404, "not a base-map file")
    return p


def _prune() -> None:
    """Keep the stored copies under MEGAVIR_BASEMAP_CACHE_MB (oldest downloads go first)."""
    cap = settings().basemap_cache_mb * 1024 * 1024
    files = []
    total = 0
    for dirpath, _, names in os.walk(cache_root()):
        for n in names:
            p = Path(dirpath) / n
            try:
                st = p.stat()
            except OSError:
                continue
            files.append((st.st_mtime, st.st_size, p))
            total += st.st_size
    if total <= cap:
        return
    for _, size, p in sorted(files):
        p.unlink(missing_ok=True)
        total -= size
        if total <= cap * 0.8:
            break


def _save(p: Path, data: bytes) -> None:
    global _writes
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.{threading.get_ident()}")
    tmp.write_bytes(data)
    os.replace(tmp, p)
    _writes += 1
    if _writes % 500 == 0:
        _prune()


def fetch(key: str, url: str, kind: str) -> bytes | None:
    """The file's bytes (gzip-compressed), from disk while fresh, else from the upstream.

    None when the upstream has no such file.  When the upstream cannot be reached, a stored copy
    is used however old it is; without one this is a 502."""
    p = _store_path(key + ".gz")

    def stored_age() -> float | None:
        try:
            return time.time() - p.stat().st_mtime
        except OSError:
            return None

    age = stored_age()
    if age is not None and age < FRESH[kind]:
        return p.read_bytes()
    with _locks[hash(key) % len(_locks)]:
        age = stored_age()  # another request may have just fetched it
        if age is not None and age < FRESH[kind]:
            return p.read_bytes()
        try:
            status, raw = _download(url)
        except httpx.HTTPError:
            status, raw = 0, b""
        if status == 200:
            if kind in ("style", "tilejson"):
                raw = _rewrite(raw, kind)
            data = gzip.compress(raw, 6)
            _save(p, data)
            return data
        if age is not None:
            return p.read_bytes()
        if status in (204, 404):
            return None
        raise HTTPException(502, "the base map is not reachable just now")


def _reply(request: Request, data: bytes | None, kind: str, suffix: str) -> Response:
    if data is None:
        return Response(status_code=204, headers={"Cache-Control": f"public, max-age={DAY}"})
    headers = {"Cache-Control": f"public, max-age={BROWSER_CACHE[kind]}", "Vary": "Accept-Encoding"}
    if "gzip" in request.headers.get("accept-encoding", ""):
        headers["Content-Encoding"] = "gzip"
    else:
        data = gzip.decompress(data)
    return Response(data, media_type=TYPES[suffix], headers=headers)


def _enabled() -> None:
    if not upstream():
        raise HTTPException(404, "the detailed base map is turned off on this server")


@router.get("/style/{theme}")
def style(theme: str, request: Request):
    """The map style for the light or dark page, with every address pointing here."""
    _enabled()
    names = {"light": settings().basemap_style_light, "dark": settings().basemap_style_dark}
    if theme not in names or not re.fullmatch(r"[a-z0-9_-]{1,40}", names[theme]):
        raise HTTPException(404, "unknown map style")
    data = fetch(f"styles/{names[theme]}.json", f"{upstream()}/styles/{names[theme]}", "style")
    if data is None:
        raise HTTPException(404, "unknown map style")
    return _reply(request, data, "style", ".json")


@router.get("/{path:path}")
def relay(path: str, request: Request):
    """Tiles, fonts, icons and the tile index named in the style."""
    _enabled()
    kind = classify(path)
    suffix = Path(path).suffix if kind != "tilejson" else ".json"
    key = path if kind != "tilejson" else "planet.json"
    url = f"{upstream()}/{quote(path, safe='/@,-_.')}"
    return _reply(request, fetch(key, url, kind), kind, suffix)
