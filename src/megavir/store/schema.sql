-- MegavirTrace store.  One monthly grid per variable, kept as compressed 20 x 20-cell tiles.

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;

-- Each import writes a new grid version; the active one is swapped in within a transaction.
CREATE TABLE IF NOT EXISTS grid_version (
    id            BIGSERIAL PRIMARY KEY,
    variable      TEXT NOT NULL,
    kind          TEXT NOT NULL CHECK (kind IN ('real', 'test', 'synthetic')),
    res_deg       DOUBLE PRECISION NOT NULL,
    lat0          DOUBLE PRECISION NOT NULL,  -- centre of the southernmost row
    lon0          DOUBLE PRECISION NOT NULL,  -- centre of the westernmost column
    ny            INTEGER NOT NULL,
    nx            INTEGER NOT NULL,
    month0        INTEGER NOT NULL,           -- absolute month index year*12 + month-1
    n_months      INTEGER NOT NULL,
    tile          INTEGER NOT NULL DEFAULT 20,
    units         TEXT NOT NULL,
    source        JSONB NOT NULL DEFAULT '{}'::jsonb,   -- product, files, checks, timings
    validation    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    active        BOOLEAN NOT NULL DEFAULT false
);
CREATE UNIQUE INDEX IF NOT EXISTS grid_version_one_active ON grid_version (variable) WHERE active;

CREATE TABLE IF NOT EXISTS grid_tile (
    version_id  BIGINT NOT NULL REFERENCES grid_version(id) ON DELETE CASCADE,
    ty          INTEGER NOT NULL,
    tx          INTEGER NOT NULL,
    data        BYTEA NOT NULL,     -- zstd(byte-shuffled float32[n_months, 20, 20]), NaN = missing
    PRIMARY KEY (version_id, ty, tx)
);

-- Static masks per grid shape (land fraction), so land/ocean variables use the right cells.
CREATE TABLE IF NOT EXISTS grid_mask (
    name     TEXT NOT NULL,         -- 'land'
    res_deg  DOUBLE PRECISION NOT NULL,
    lat0     DOUBLE PRECISION NOT NULL,
    lon0     DOUBLE PRECISION NOT NULL,
    ny       INTEGER NOT NULL,
    nx       INTEGER NOT NULL,
    data     BYTEA NOT NULL,        -- zstd(float32[ny, nx]) land fraction 0..1
    PRIMARY KEY (name, res_deg, lat0, lon0)
);

-- Places: countries and states with real outlines, cities and presets.
CREATE TABLE IF NOT EXISTS place (
    id          TEXT PRIMARY KEY,           -- e.g. 'country:USA', 'admin1:US-TX', 'city:5128581', 'preset:sahel'
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL,              -- country | admin1 | city | preset
    context     TEXT NOT NULL DEFAULT '',   -- e.g. 'Texas, United States'
    lat         DOUBLE PRECISION NOT NULL,
    lon         DOUBLE PRECISION NOT NULL,
    population  BIGINT NOT NULL DEFAULT 0,
    bbox        DOUBLE PRECISION[] NOT NULL, -- [west, south, east, north]
    geometry    JSONB,                       -- simplified GeoJSON geometry (NULL = use bbox)
    search      TEXT NOT NULL                -- unaccented lower-case name + alternates
);
CREATE INDEX IF NOT EXISTS place_search_trgm ON place USING gin (search gin_trgm_ops);
CREATE INDEX IF NOT EXISTS place_kind ON place (kind);

-- Cached region weights per (region fingerprint, grid shape)
CREATE TABLE IF NOT EXISTS region_weights (
    key         TEXT PRIMARY KEY,
    y0          INTEGER NOT NULL,
    x0          INTEGER NOT NULL,
    ny          INTEGER NOT NULL,
    nx          INTEGER NOT NULL,
    data        BYTEA NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Statistics are computed once per data version and reused.
CREATE TABLE IF NOT EXISTS analysis (
    id           TEXT PRIMARY KEY,          -- fingerprint: sha256 of request + data versions + engine version
    kind         TEXT NOT NULL,             -- trend | compare | scan
    request      JSONB NOT NULL,
    versions     BIGINT[] NOT NULL,
    result       JSONB NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS analysis_versions ON analysis USING gin (versions);

-- AI usage records (FR20): counts only, never the visitor's text or IP.
CREATE TABLE IF NOT EXISTS ai_usage (
    day         DATE NOT NULL,
    outcome     TEXT NOT NULL,              -- answered | fallback | failed | limited
    n           INTEGER NOT NULL DEFAULT 0,
    tokens_in   BIGINT NOT NULL DEFAULT 0,
    tokens_out  BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (day, outcome)
);

-- Import dashboard (also created on first use by megavir.imports.state)
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

-- administrator sign-in sessions (Admin panel, Data import)
CREATE TABLE IF NOT EXISTS admin_session (
    id_hash    TEXT PRIMARY KEY,                    -- sha256 of the secret the browser holds
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    remember   BOOLEAN NOT NULL DEFAULT false,      -- "keep me signed in": 30 days instead of 12 hours
    user_agent TEXT NOT NULL DEFAULT ''
);

-- a region's monthly mean, kept once per data version (reused by comparisons, scans and cases)
CREATE TABLE IF NOT EXISTS region_series (
    version_id INTEGER NOT NULL,
    region_key TEXT NOT NULL,
    mean       DOUBLE PRECISION[] NOT NULL,
    coverage   DOUBLE PRECISION[] NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (version_id, region_key)
);
