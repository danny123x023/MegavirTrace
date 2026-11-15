# MegavirTrace

**Is this place really changing?** An honest, checkable answer for any place on Earth, from NASA data:
what is changing, where, how much, and whether it is significant.

NASA Space Apps Challenge 2026, *"Be An Earth System Trend Detective!"* · Team **Space Pirates Paradigm** ·
Apache 2.0.

The design is in [`Project-Design.md`](Project-Design.md). The method is in [`docs/methods.md`](docs/methods.md).

## What it does

- **Explore:** pick a variable and a place (search about 39,000 places, 138 presets, or draw or type a box).
  You get a plain-language verdict, a chart with the trend and its 95% range, the statistics, and a cell map
  showing where inside the region the change is happening. The map switches between a flat 2D map and a 3D globe.
  Big regions, up to the whole Earth, get a map too: cells are merged into blocks (for example 2° from 0.5°)
  so the whole region fits, and zooming in loads full detail for the area in view, with the false-discovery
  test run over the cells shown.
  It is a detailed street map (OpenStreetMap data): zoom in to streets, places and buildings in your own area,
  or use the location button. The trend colours fade as you zoom in and have a strength slider.
- **Compare:** tests whether two regions' trends really differ, using the trend of their difference series.
  It also finds pairs of preset regions with opposite trends.
- **Detective cases:** 20 guided investigations of real events and documented changes: Europe's 2003
  heatwave, Pakistan's 2022 floods, Australia's Black Summer, the 2020 lockdowns, northwest India's groundwater,
  Arctic amplification and more. Each one names its regions and NASA variables. The story says only what
  happened and where to look; every step is computed live from the stored data. It shows how unusual the event
  month was, the trend behind it, and whether later years went past it, and the findings are written from
  those numbers. Cards show the measured key finding and a small chart of the real series.
- **Related variables:** do two variables rise and fall together in one place, possibly with a delay? Seasonal
  cycles and trends are removed first, and significance allows for month-to-month memory and for the lags
  searched. Always labelled "related, not caused by".
- **Where do I start?** suggests variables by place type and curiosity. It can also test every variable for
  one place, with false-discovery control across the variables.
- **Ask the AI scientist (optional):** the AI turns a question into engine runs, then explains the results.
  It never computes. Every number and direction word it writes is checked against the stored results, and if
  anything fails the check you see the template verdict instead.
- **Ground truth from NASA GLOBE:** for temperature and rainfall, measurements by GLOBE schools and volunteers in
  the same place are shown beside the series as monthly anomalies, with how well the two move together.
  Over Texas, 18 GLOBE sites track GISTEMP with r = 0.89. This is context only and never enters the trend tests.
- **Climate projections (context):** for temperature and rainfall, what five NASA NEX-GDDP-CMIP6 models simulate
  under SSP2-4.5 and SSP5-8.5, beside the observed change. Computed on NASA's servers in about 2 minutes per
  region the first time, then stored. Not a forecast, and never part of the trend tests.
- **English and Spanish, offline, phone-first:** switch language from the header (verdicts come from Spanish
  templates with Spanish number formats). After one visit, pages and recent results open without a connection.
- **Take it away:** download CSV, Excel, PDF, or a notebook that recomputes every number with NumPy and SciPy
  alone. There are also embeddable trend cards and an open, read-only data API at `/api/docs`.

### Honest significance

A trend is "significant" only when an autocorrelation-corrected Mann–Kendall test and a least-squares t-test
agree, and all slopes point the same way. False alarms are measured in CI on 2,000 AR(1) series per setting.

| Lag-1 autocorrelation | Target | Measured (20 and 30 years) |
| --- | --- | --- |
| 0.3 | ≤ 5% | 3.5% and 4.1% |
| 0.5 | ≤ 7% | 4.4% and 4.7% |

The two-region difference test keeps false alarms between 3.7% and 4.8% for correlations from −0.5 to 0.95.
A non-significant verdict says how many more years of data a trend of that size would need.

## Data status

| Variable(s) | Product | Status |
| --- | --- | --- |
| Air temperature (2 m) | MERRA-2 M2TMNXSLV | **Real, global, 1980 to present.** Matches NASA Giovanni over the test box: r = 0.9998, mean difference 1.6% (target r ≥ 0.98, within 5%) |
| Surface temperature change | GISTEMP v4 | **Real, global, 1880 to present.** Matches NASA's official global series: r = 0.9997, mean difference 0.008 °C, warming since 1975 of 0.209 vs 0.207 °C per decade, same warmest year (2024). |
| Water stored on land | GSFC GRACE/GRACE-FO mascons | **Real, global, 2002 to present** (analysed month by month because of mission gaps) |
| Fire carbon emissions | MiCASA v1 | **Real, global, 2001–2024** |
| The other 19 variables | OMI, GLDAS, GPM IMERG, MODIS (×3), NASA-SSH, MERRA-2 (×3), AIRS, CERES, NSIDC, OCO-2 | Code ready; needs a free NASA Earthdata Login (see below) |

The **test box** is about 5° × 5° on the US Gulf Coast (95–90°W, 27.5–32.5°N): Louisiana, east Texas, Houston
and the Gulf of Mexico, so both land-only and sea-only variables have cells there. Test data are always
labelled as such and never presented as real results.

## Quick start (local)

Requirements: Python 3.12+ (3.14 tested), Node 22, Docker.

```bash
python3 -m venv .venv && .venv/bin/pip install uv
UV_PROJECT_ENVIRONMENT=.venv .venv/bin/uv sync --locked --extra ingest --extra dev
(cd web && npm ci)
cp .env.example .env

scripts/dev.sh start        # PostgreSQL (Docker, port 5433), API on :8000, web on :3000

I=".venv/bin/python -I -m megavir.ingest.cli"
$I init-db
$I places --download        # GeoNames + Natural Earth (public)
$I masks                    # land fraction on 0.5°, 1° and 2° grids
$I full gistemp             # 25 MB, public; then:
$I gistemp-check            # compare with NASA's official global series
$I giovanni-check           # MERRA-2 and IMERG test-box series vs NASA Giovanni (needs Earthdata Login)
$I test grace               # public, 0.5 GB single file
$I test micasa              # public, ~2 GB for the last 10 years
$I precompute               # store statistics for all presets (once per data version)
```

Open <http://localhost:3000>. `scripts/dev.sh status` and `scripts/dev.sh stop` check and stop the servers.

### NASA Earthdata products

Fourteen products need a free [Earthdata Login](https://urs.earthdata.nasa.gov). Set `EARTHDATA_TOKEN`, or
`EARTHDATA_USERNAME` and `EARTHDATA_PASSWORD`, or add a `~/.netrc` entry for `urs.earthdata.nasa.gov`. Then:

```bash
$I test all      # every product, test box and recent years only: small, quick, records time and size per product
$I full all      # after development: the whole globe and record (about 47 GB), each product swapped in as a new version
```

Downloads resume after a break and raw files stay on disk. Only the fields needed are requested through
NASA's cloud OPeNDAP. The variable paths are read from each product's DMR at run time, so HDF4, HDF-EOS5 and
netCDF products all arrive as netCDF4. Each run writes `data/ingest_<mode>_report.json` and a quick-look map
per variable in `data/quicklook/`.

### Data import dashboard

The **Data import** page (`/imports`) shows what NASA holds now for each product (from NASA's public
catalogues), what is stored and for how long, and runs imports as background jobs with live progress. Each job
runs the same `megavir-ingest full <product>` as above, then records what happened to every variable:
imported, unchanged (identical data keeps the stored version), skipped or failed. The page can also check that
the Earthdata Login works for every product, and replace or remove it (it is written only to the netrc file,
owner-only, never to the database).

Anyone can view the page. Imports, deletions and account changes need the administrator token, because the
web app's proxy hides the visitor's address. Read it on the server with:

```bash
$I admin-token   # MEGAVIR_ADMIN_TOKEN from .env, or a random one kept in data/admin_token
```

An import of a product never runs twice at once: the dashboard and the command line share a per-product lock.

### Detective cases

The cases are defined in `src/megavir/cases/catalog.py`: a story, a question, and 2 to 4 steps (one month
against the same month of every year, a trend, or a comparison of two regions), each naming a region and
variable. `cases/run.py` runs every step through the engine and writes the findings from the results, in
English or Spanish. Results are cached like any analysis, and `precompute` prepares them after each import.
Stories may state only widely reported facts about what happened, never a measured result. Bump `CASES_REV`
when a case changes.

### The street map

The map under the trend colours is [OpenFreeMap](https://openfreemap.org): free vector tiles of
OpenStreetMap data, with no key. Browsers never contact it. The API relays the style, tiles, fonts and icons
from `/api/basemap/*`, keeps a copy in `data/basemap/` (capped by `MEGAVIR_BASEMAP_CACHE_MB`, default 2 GB),
and limits each visitor to `MEGAVIR_BASEMAP_PER_MINUTE_PER_IP` requests. So visitors' addresses stay with
you, the page keeps `connect-src 'self'`, and an area viewed once loads from your server afterwards. The
service worker keeps the last 2,000 map files, so places you looked at work offline. To use your own tile
server, set `MEGAVIR_BASEMAP_URL` (and the `_STYLE_LIGHT` and `_STYLE_DARK` names). An empty URL turns the
street map off. The map then shows the built-in country outlines, as it also does when the tiles cannot load.

### The AI scientist (optional, off by default)

Set it up in `.env`, never in the browser:

```
MEGAVIR_AI_PROVIDER=zai          # or openai, openai_compatible, anthropic
MEGAVIR_AI_MODEL=<model id>      # anthropic defaults to claude-opus-5-5
MEGAVIR_AI_API_KEY=<key used only by this site>
MEGAVIR_AI_HOURLY_LIMIT_PER_IP=20
MEGAVIR_AI_DAILY_CAP=500
```

Also set a spend limit in the provider's own console. For Anthropic, the server-side refusal fallback
(`fallbacks: "default"`) is enabled. Daily answers, fallbacks, failures and token counts are kept in the
`ai_usage` table: counts only, never visitors' text or IP addresses.

## Tests

```bash
.venv/bin/python -m pytest -m "not db" -n auto   # statistics vs scipy/pymannkendall, Monte Carlo, AI number check, readers
.venv/bin/python -m pytest -m db                 # every endpoint on a synthetic store (PostgreSQL)
(cd web && npx playwright test)                  # browser flows + axe-core gate in light and dark (needs the app running)
```

CI (`.github/workflows/ci.yml`) runs all of these, plus installs from the lock files only, a gitleaks secret
scan, `pip-audit` and `npm audit`.

## Architecture

```
web/ (Next.js 16, MapLibre)  ──/api──>  FastAPI (src/megavir/api)  ──>  science engine (src/megavir/engine)
                                               │                                   │
                                               └──> AI layer (src/megavir/ai) ─tools┘
ingest jobs (src/megavir/ingest) ──> PostgreSQL: versioned grids as compressed 20×20-cell tiles, places, stored results
```

- `engine/`: deterministic statistics (`stats.py`), aggregation, cell maps with FDR, the comparison, and the
  verdict templates (English and Spanish).
- `catalog/`: the 16 variables and 11 datasets. Every DOI was resolved against NASA CMR or Crossref.
- `store/`: tiles are byte-shuffled float32 compressed with zstd. A region reads only the tiles it touches,
  and each import is swapped in within one transaction.
- `places/`: region masks with fractional cell weights, presets, and loaders.
- `exports/`: CSV, Excel, PDF and the recomputing notebook.

Deployment: `deploy/` has an nginx site (one origin, `/api` → FastAPI), systemd units and a nightly
`pg_dump` backup.

## Requirements status

| ID | Requirement | Priority | Status |
| --- | --- | --- | --- |
| FR1 | Variable catalog | Must | Done: 22 variables, 7 themes, 17 products |
| FR3 | Region selection | Must | Done: 39,089 places, 138 presets, drawn or typed box, real outlines |
| FR4 | Regional time series | Must | Done: area-weighted, coverage per month, 4 modes, table view |
| FR5 | Trend statistics | Must | Done, Monte Carlo verified |
| FR6 | Template verdicts | Must | Done (English; Spanish templates in the engine) |
| FR10 | Compare two regions | Must | Done, plus the opposite-trend finder |
| FR20 | Security and cost | Must | Done |
| FR2 | Six more variables | Should | Code ready: MODIS land surface temperature and snow cover, MERRA-2 aerosols, CERES energy budget, NSIDC sea ice, OCO-2 CO₂ (readers tested on fake files; downloads need Earthdata Login) |
| FR7 | Speeding-up trends | Should | Done: curvature test with memory correction, calibrated so false "speeding up" claims stay within the targets |
| FR8 | Cell trend map with FDR | Should | Done |
| FR9 | 2D/3D Earth view | Should | Done (animated switch; instant with reduced motion) |
| FR12 | Variable guidance and scan | Should | Done |
| FR14 | NASA GLOBE ground data | Should | Done: GLOBE air temperature and rain gauges beside the series, as monthly anomalies with their correlation |
| FR16 | Downloads | Should | Done; the notebook reproduces every number |
| FR11 | "Moves together" explorer | Could | Done: lagged relationships with memory-aware significance; false "related" claims ≤ 3.5% in Monte Carlo |
| FR13 | AI scientist and tutor | Could | Done; tested with fake clients, not yet with a live service |
| FR15 | CMIP6 projections | Could | Done: NASA NEX-GDDP-CMIP6, 5 models, SSP2-4.5 and SSP5-8.5, sample years, each model's change from its own baseline, beside the observed change, with strong caveats |
| FR17 | Embeds and open API | Could | Done |
| FR18 | Methods paper and contributor guide | Could | Drafts in `docs/` and `CONTRIBUTING.md` |
| FR19 | Languages, offline | Could | Done: English and Spanish (interface, catalog and verdicts); works offline after one visit (service worker plus recent results kept on the device); phone-first layout checked at 390 px |

## Credits and licences

Data: NASA (GES DISC, LP DAAC, PO.DAAC, GISS, GSFC, NCCS) the NASA [GLOBE Program](https://www.globe.gov) and NASA NEX-GDDP-CMIP6 (via NCCS). Each product is cited with its DOI in the app and
the exports. Place names: [GeoNames](https://www.geonames.org) (CC BY 4.0). Outlines and land:
[Natural Earth](https://www.naturalearthdata.com) (public domain). Street map: © [OpenStreetMap
contributors](https://www.openstreetmap.org/copyright) (ODbL), tiles by [OpenFreeMap](https://openfreemap.org),
© [OpenMapTiles](https://www.openmaptiles.org). Code: Apache 2.0 (see `LICENSE`).
