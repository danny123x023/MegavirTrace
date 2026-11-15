"""Tables of the import dashboard, created on first use (also in store/schema.sql)."""

from __future__ import annotations

import json
import threading

SQL = """
CREATE TABLE IF NOT EXISTS import_job (
    id           BIGSERIAL PRIMARY KEY,
    product      TEXT NOT NULL,
    variables    TEXT[] NOT NULL,
    mode         TEXT NOT NULL DEFAULT 'full',
    status       TEXT NOT NULL CHECK (status IN ('queued', 'running', 'done', 'failed')),
    requested_by TEXT NOT NULL DEFAULT '',          -- 'local' | 'admin'
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at   TIMESTAMPTZ,
    finished_at  TIMESTAMPTZ,
    progress     JSONB NOT NULL DEFAULT '{}'::jsonb, -- stage, done, total, variable
    results      JSONB NOT NULL DEFAULT '{}'::jsonb, -- variable -> {action, version, months, detail}
    summary      TEXT NOT NULL DEFAULT '',
    log_tail     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS import_job_status ON import_job (status, id);
CREATE TABLE IF NOT EXISTS import_state (
    key        TEXT PRIMARY KEY,
    value      JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_ready: set[str] = set()
_lock = threading.Lock()


def ensure(conn) -> None:
    """Create the tables once per database and process."""
    key = conn.info.dbname + "@" + str(conn.info.host) + ":" + str(conn.info.port)
    if key in _ready:
        return
    with _lock:
        conn.execute(SQL)
        conn.commit()
        _ready.add(key)


def get_state(conn, key: str) -> dict | None:
    ensure(conn)
    r = conn.execute("SELECT value, updated_at FROM import_state WHERE key = %s", (key,)).fetchone()
    if not r:
        return None
    return {**r["value"], "updated_at": r["updated_at"].isoformat()}


def set_state(conn, key: str, value: dict) -> None:
    ensure(conn)
    conn.execute(
        """INSERT INTO import_state (key, value) VALUES (%s, %s::jsonb)
           ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()""",
        (key, json.dumps(value)),
    )
    conn.commit()
