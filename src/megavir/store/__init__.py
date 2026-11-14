"""PostgreSQL store: versioned monthly grids as compressed 20 x 20-cell tiles."""

from __future__ import annotations

import atexit
import json
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import numpy as np
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from megavir.config import settings

try:  # Python 3.14+
    from compression import zstd as _zstd

    def _compress(b: bytes) -> bytes:
        return _zstd.compress(b, level=6)

    def _decompress(b: bytes) -> bytes:
        return _zstd.decompress(b)

except ImportError:  # pragma: no cover - older Pythons
    import zlib

    def _compress(b: bytes) -> bytes:
        return zlib.compress(b, 6)

    def _decompress(b: bytes) -> bytes:
        return zlib.decompress(b)


TILE = 20
SCHEMA = Path(__file__).with_name("schema.sql")

_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


def pool() -> ConnectionPool:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ConnectionPool(
                settings().database_url, min_size=1, max_size=8, kwargs={"row_factory": dict_row}, open=True
            )
            atexit.register(close_pool)
    return _pool


def close_pool() -> None:
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None


@contextmanager
def connect():
    with pool().connection() as conn:
        yield conn


def direct_connect(url: str | None = None) -> psycopg.Connection:
    return psycopg.connect(url or settings().database_url, row_factory=dict_row)


def init_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA.read_text())
    conn.commit()


# --------------------------------------------------------------------------------------
# Array encoding
# --------------------------------------------------------------------------------------


def encode_array(a: np.ndarray) -> bytes:
    """float32, byte-shuffled (better compression of smooth fields), then zstd."""
    a = np.ascontiguousarray(a, dtype="<f4")
    shuffled = a.view(np.uint8).reshape(-1, 4).T.copy()
    header = json.dumps({"shape": list(a.shape)}).encode()
    return len(header).to_bytes(4, "little") + header + _compress(shuffled.tobytes())


def decode_array(b: bytes) -> np.ndarray:
    hlen = int.from_bytes(b[:4], "little")
    shape = tuple(json.loads(b[4 : 4 + hlen])["shape"])
    raw = np.frombuffer(_decompress(b[4 + hlen :]), dtype=np.uint8).reshape(4, -1).T.copy()
    return raw.view("<f4").reshape(shape)


# --------------------------------------------------------------------------------------
# Grid geometry
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class GridSpec:
    res: float
    lat0: float  # centre of the southernmost row
    lon0: float  # centre of the westernmost column
    ny: int
    nx: int

    @staticmethod
    def global_grid(res: float) -> GridSpec:
        return GridSpec(res, -90 + res / 2, -180 + res / 2, int(round(180 / res)), int(round(360 / res)))

    @cached_property
    def lats(self) -> np.ndarray:
        return self.lat0 + self.res * np.arange(self.ny)

    @cached_property
    def lons(self) -> np.ndarray:
        return self.lon0 + self.res * np.arange(self.nx)

    @property
    def is_global_lon(self) -> bool:
        return abs(self.nx * self.res - 360) < 1e-6

    def key(self) -> str:
        return f"{self.res:g}:{self.lat0:g}:{self.lon0:g}:{self.ny}:{self.nx}"

    def window(self, south: float, north: float, west: float, east: float) -> GridSpec:
        """A sub-grid aligned to this one, covering the box (used for test-area versions)."""
        i0 = max(0, int(np.floor((south - (self.lat0 - self.res / 2)) / self.res)))
        i1 = min(self.ny, int(np.ceil((north - (self.lat0 - self.res / 2)) / self.res)))
        j0 = max(0, int(np.floor((west - (self.lon0 - self.res / 2)) / self.res)))
        j1 = min(self.nx, int(np.ceil((east - (self.lon0 - self.res / 2)) / self.res)))
        return GridSpec(self.res, self.lats[i0], self.lons[j0], i1 - i0, j1 - j0)

    def offset_in(self, parent: GridSpec) -> tuple[int, int]:
        i = int(round((self.lat0 - parent.lat0) / parent.res))
        j = int(round((self.lon0 - parent.lon0) / parent.res))
        return i, j


@dataclass
class Version:
    id: int
    variable: str
    kind: str
    spec: GridSpec
    month0: int
    n_months: int
    units: str
    source: dict
    validation: dict
    created_at: str

    @property
    def months(self) -> np.ndarray:
        return self.month0 + np.arange(self.n_months)

    def to_public(self) -> dict:
        m_end = self.month0 + self.n_months - 1
        return {
            "id": self.id,
            "variable": self.variable,
            "kind": self.kind,
            "res_deg": self.spec.res,
            "bbox": [
                self.spec.lon0 - self.spec.res / 2,
                self.spec.lat0 - self.spec.res / 2,
                self.spec.lon0 + self.spec.res * (self.spec.nx - 0.5),
                self.spec.lat0 + self.spec.res * (self.spec.ny - 0.5),
            ],
            "first_month": f"{self.month0 // 12:04d}-{self.month0 % 12 + 1:02d}",
            "last_month": f"{m_end // 12:04d}-{m_end % 12 + 1:02d}",
            "units": self.units,
            "created_at": str(self.created_at),
            "validation": self.validation,
        }


def _row_to_version(r: dict) -> Version:
    return Version(
        id=r["id"],
        variable=r["variable"],
        kind=r["kind"],
        spec=GridSpec(r["res_deg"], r["lat0"], r["lon0"], r["ny"], r["nx"]),
        month0=r["month0"],
        n_months=r["n_months"],
        units=r["units"],
        source=r["source"] or {},
        validation=r["validation"] or {},
        created_at=r["created_at"],
    )


def active_versions(conn: psycopg.Connection) -> dict[str, Version]:
    kinds = settings().serve_kinds
    rows = conn.execute(
        "SELECT * FROM grid_version WHERE active AND kind = ANY(%s) ORDER BY variable", (kinds,)
    ).fetchall()
    return {r["variable"]: _row_to_version(r) for r in rows}


def get_version(conn: psycopg.Connection, version_id: int) -> Version | None:
    r = conn.execute("SELECT * FROM grid_version WHERE id = %s", (version_id,)).fetchone()
    return _row_to_version(r) if r else None


# --------------------------------------------------------------------------------------
# Writing and reading
# --------------------------------------------------------------------------------------


def write_version(
    conn: psycopg.Connection,
    variable: str,
    kind: str,
    spec: GridSpec,
    month0: int,
    cube: np.ndarray,
    units: str,
    source: dict | None = None,
    validation: dict | None = None,
    activate: bool = True,
) -> int:
    """Write a whole grid as a new version; swap it in atomically when ``activate``."""
    cube = np.asarray(cube, np.float32)
    nt, ny, nx = cube.shape
    assert (ny, nx) == (spec.ny, spec.nx), "cube does not match grid"
    with conn.transaction():
        vid = conn.execute(
            """INSERT INTO grid_version (variable, kind, res_deg, lat0, lon0, ny, nx, month0, n_months, tile,
                                         units, source, validation, active)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,false) RETURNING id""",
            (
                variable,
                kind,
                spec.res,
                spec.lat0,
                spec.lon0,
                ny,
                nx,
                month0,
                nt,
                TILE,
                units,
                json.dumps(source or {}),
                json.dumps(validation or {}),
            ),
        ).fetchone()["id"]
        with conn.cursor() as cur:
            with cur.copy("COPY grid_tile (version_id, ty, tx, data) FROM STDIN") as cp:
                for ty in range(0, (ny + TILE - 1) // TILE):
                    for tx in range(0, (nx + TILE - 1) // TILE):
                        block = np.full((nt, TILE, TILE), np.nan, np.float32)
                        part = cube[:, ty * TILE : (ty + 1) * TILE, tx * TILE : (tx + 1) * TILE]
                        if not np.isfinite(part).any():
                            continue  # empty tiles are simply absent
                        block[:, : part.shape[1], : part.shape[2]] = part
                        cp.write_row((vid, ty, tx, encode_array(block)))
        if activate:
            conn.execute("UPDATE grid_version SET active = false WHERE variable = %s AND active", (variable,))
            conn.execute("UPDATE grid_version SET active = true WHERE id = %s", (vid,))
    return vid


def read_cells(conn: psycopg.Connection, version: Version, ii: np.ndarray, jj: np.ndarray) -> np.ndarray:
    """Values (n_months, n_cells) for the given cell indices, reading only the tiles touched."""
    ii = np.asarray(ii, int)
    jj = np.asarray(jj, int)
    out = np.full((version.n_months, ii.size), np.nan, np.float32)
    inside = (ii >= 0) & (ii < version.spec.ny) & (jj >= 0) & (jj < version.spec.nx)
    if not inside.any():
        return out
    ty = ii // TILE
    tx = jj // TILE
    keys = sorted({(int(a), int(b)) for a, b, k in zip(ty, tx, inside, strict=True) if k})
    rows = conn.execute(
        "SELECT ty, tx, data FROM grid_tile WHERE version_id = %s AND (ty, tx) IN (SELECT * FROM unnest(%s::int[], %s::int[]))",
        (version.id, [k[0] for k in keys], [k[1] for k in keys]),
    ).fetchall()
    for r in rows:
        block = decode_array(bytes(r["data"]))
        sel = inside & (ty == r["ty"]) & (tx == r["tx"])
        out[:, sel] = block[:, ii[sel] - r["ty"] * TILE, jj[sel] - r["tx"] * TILE]
    return out


def read_full(conn: psycopg.Connection, version: Version) -> np.ndarray:
    s = version.spec
    cube = np.full((version.n_months, s.ny, s.nx), np.nan, np.float32)
    for r in conn.execute("SELECT ty, tx, data FROM grid_tile WHERE version_id = %s", (version.id,)):
        block = decode_array(bytes(r["data"]))
        y0, x0 = r["ty"] * TILE, r["tx"] * TILE
        h, w = min(TILE, s.ny - y0), min(TILE, s.nx - x0)
        cube[:, y0 : y0 + h, x0 : x0 + w] = block[:, :h, :w]
    return cube


def write_mask(conn: psycopg.Connection, name: str, spec: GridSpec, data: np.ndarray) -> None:
    conn.execute(
        """INSERT INTO grid_mask (name, res_deg, lat0, lon0, ny, nx, data) VALUES (%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (name, res_deg, lat0, lon0) DO UPDATE SET data = EXCLUDED.data, ny = EXCLUDED.ny, nx = EXCLUDED.nx""",
        (name, spec.res, spec.lat0, spec.lon0, spec.ny, spec.nx, encode_array(data)),
    )
    conn.commit()


_mask_cache: dict[tuple, np.ndarray] = {}


def read_mask(conn: psycopg.Connection, name: str, res: float) -> tuple[GridSpec, np.ndarray] | None:
    """Global mask at a resolution (windows of the global grid use an offset into it)."""
    g = GridSpec.global_grid(res)
    key = (name, g.res, g.lat0, g.lon0)
    if key not in _mask_cache:
        r = conn.execute(
            "SELECT data FROM grid_mask WHERE name=%s AND res_deg=%s AND lat0=%s AND lon0=%s", key
        ).fetchone()
        if not r:
            return None
        _mask_cache[key] = decode_array(bytes(r["data"]))
    return g, _mask_cache[key]
