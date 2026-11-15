"""Command-line ingest (a server job; there are no admin pages).

    megavir-ingest init-db
    megavir-ingest places            # countries, states, cities, presets (public sources)
    megavir-ingest masks             # land fraction on 0.5°, 1° and 2° grids
    megavir-ingest synthetic         # small made-up store for software tests
    megavir-ingest test PRODUCT|all  # test box, recent years
    megavir-ingest full PRODUCT|all  # whole globe, whole record (after development)
    megavir-ingest gistemp-check     # our GISTEMP global series against NASA's official one
    megavir-ingest access-check      # can this server download each Earthdata product?
    megavir-ingest admin-token       # the import dashboard's administrator token
    megavir-ingest status

The import dashboard (web page "Data import") runs the same commands as background jobs.

Run with ``python -I -m megavir.ingest.cli`` so nothing in the data folders is importable.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import httpx
import numpy as np

from megavir.config import settings
from megavir.store import active_versions, direct_connect, init_schema, read_full

PUBLIC_PLACE_FILES = {
    "geonames/cities15000.zip": "https://download.geonames.org/export/dump/cities15000.zip",
    "geonames/countryInfo.txt": "https://download.geonames.org/export/dump/countryInfo.txt",
    "geonames/admin1CodesASCII.txt": "https://download.geonames.org/export/dump/admin1CodesASCII.txt",
    "ne_countries/ne_50m_admin_0_countries.zip": "https://naciscdn.org/naturalearth/50m/cultural/ne_50m_admin_0_countries.zip",
    "ne_admin1/ne_10m_admin_1_states_provinces.zip": "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_1_states_provinces.zip",
    "ne_land/ne_50m_land.zip": "https://naciscdn.org/naturalearth/50m/physical/ne_50m_land.zip",
}


def _raw() -> Path:
    return settings().data_dir / "raw"


def fetch_place_sources(raw: Path) -> None:
    import zipfile

    from .download import PublicSession, download

    s = PublicSession()
    for rel, url in PUBLIC_PLACE_FILES.items():
        dest = raw / rel
        download(url, dest, s)
        if dest.suffix == ".zip":
            with zipfile.ZipFile(dest) as z:
                for member in z.namelist():
                    # extract only plain file names into the file's own folder (no paths from the archive)
                    name = Path(member).name
                    if not name or name.startswith("."):
                        continue
                    (dest.parent / name).write_bytes(z.read(member))


def cmd_status(conn) -> None:
    rows = conn.execute(
        "SELECT variable, kind, id, n_months, res_deg, ny, nx, created_at FROM grid_version WHERE active ORDER BY variable"
    ).fetchall()
    for r in rows:
        print(
            f"{r['variable']:20s} {r['kind']:10s} v{r['id']:<5d} {r['n_months']:5d} months  {r['res_deg']}° {r['ny']}x{r['nx']}  {r['created_at']:%Y-%m-%d %H:%M}"
        )
    n = conn.execute("SELECT kind, count(*) AS n FROM place GROUP BY kind ORDER BY kind").fetchall()
    print("places:", {r["kind"]: r["n"] for r in n})


def cmd_precompute(conn, variables: list[str], countries: bool) -> None:
    """Statistics are computed once per data version and stored: warm the presets (and countries)."""
    from megavir.api.service import AnalysisError, run_trend

    versions = active_versions(conn)
    var_ids = variables or [v for v, ver in versions.items() if ver.kind == "real"]
    kinds = ["preset"] + (["country"] if countries else [])
    places = [
        r["id"]
        for r in conn.execute("SELECT id FROM place WHERE kind = ANY(%s) ORDER BY id", (kinds,)).fetchall()
    ]
    for var in var_ids:
        t0, done, skipped = time.time(), 0, 0
        for pid in places:
            try:
                run_trend(conn, {"variable": var, "region": {"place": pid}, "cell_map": True})
                done += 1
            except AnalysisError:
                skipped += 1
        print(f"{var}: {done} regions stored, {skipped} without data, {time.time() - t0:.0f}s")
    # the detective cases (both languages), so their page opens without waiting
    from megavir.cases import CASES, run_case

    t0 = time.time()
    for lang in ("en", "es"):
        for case in CASES:
            r = run_case(conn, case.id, lang)
            for step in r["steps"]:
                if "error" in step:
                    print(f"case {case.id}: {step['title']}: {step['error']}")
    print(f"detective cases: {len(CASES)} stored in 2 languages, {time.time() - t0:.0f}s")


def cmd_gistemp_check(conn) -> dict:
    from megavir.engine.aggregate import build_series
    from megavir.store import GridSpec

    from .validate import GISTEMP_GLOBAL_CSV, area_mean_series, compare_gistemp, parse_official_gistemp

    v = active_versions(conn).get("temp_change")
    if not v:
        raise SystemExit("temp_change is not loaded")
    cube = read_full(conn, v)
    spec = GridSpec(v.spec.res, v.spec.lat0, v.spec.lon0, v.spec.ny, v.spec.nx)
    s = area_mean_series(cube, spec)
    ser = build_series(v.months, s, "annual")
    text = httpx.get(GISTEMP_GLOBAL_CSV, timeout=60, follow_redirects=True).text
    res = compare_gistemp(ser.years, ser.y, parse_official_gistemp(text))
    conn.execute(
        "UPDATE grid_version SET validation = validation || %s::jsonb WHERE id = %s",
        (json.dumps({"nasa_official_check": res}), v.id),
    )
    conn.commit()
    return res


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="megavir-ingest")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db")
    pp = sub.add_parser("places")
    pp.add_argument("--download", action="store_true", help="fetch the public source files first")
    sub.add_parser("masks")
    sy = sub.add_parser("synthetic")
    sy.add_argument("--years", type=int, default=24)
    for mode in ("test", "full"):
        m = sub.add_parser(mode)
        m.add_argument("product", help="product id or 'all'")
        m.add_argument("--limit", type=int, default=None, help="only the newest N files (smoke runs)")
        m.add_argument("--no-activate", action="store_true")
        m.add_argument(
            "--report-json", type=Path, default=None, help="also write this run's reports to a file"
        )
    pc = sub.add_parser(
        "precompute", help="compute and store statistics for presets and countries (once per data version)"
    )
    pc.add_argument("variables", nargs="*", help="variable ids (default: every loaded variable)")
    pc.add_argument("--countries", action="store_true", help="also every country")
    sub.add_parser("gistemp-check")
    gc = sub.add_parser(
        "giovanni-check", help="compare test-box series with NASA Giovanni (needs Earthdata Login)"
    )
    gc.add_argument("variables", nargs="*", default=["air_temp", "rainfall"])
    gc.add_argument("--points", type=int, default=5, help="points per side of the grid across the test box")
    sub.add_parser("access-check", help="check that each Earthdata product can be downloaded (prints JSON)")
    sub.add_parser("admin-token", help="print the import dashboard's administrator token (created if needed)")
    sub.add_parser("status")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    conn = direct_connect()
    if args.cmd == "init-db":
        init_schema(conn)
        print("schema ready")
    elif args.cmd == "places":
        from megavir.places.load import load_places

        if args.download:
            fetch_place_sources(_raw())
        n = load_places(conn, _raw())
        print(f"loaded {n} places")
    elif args.cmd == "masks":
        from megavir.places.load import load_land_masks

        print("land share of Earth's area:", load_land_masks(conn, _raw()))
    elif args.cmd == "synthetic":
        from .synthetic import build_synthetic

        print(build_synthetic(conn, years=args.years))
    elif args.cmd in ("test", "full"):
        from .download import LoginRequired
        from .pipeline import ProductBusy, run
        from .products import PRODUCTS

        todo = list(PRODUCTS) if args.product == "all" else [args.product]
        unknown = [pid for pid in todo if pid not in PRODUCTS]
        if unknown:
            raise SystemExit(f"unknown product: {', '.join(unknown)}")
        reports, failed = [], False
        for pid in todo:
            t0 = time.time()
            try:
                rep = run(pid, args.cmd, conn, _raw(), limit=args.limit, activate=not args.no_activate)
                d = rep.to_dict()
                d["total_s"] = round(time.time() - t0, 1)
                reports.append(d)
                print(
                    json.dumps(
                        {
                            k: d[k]
                            for k in (
                                "product",
                                "mode",
                                "files",
                                "bytes",
                                "download_s",
                                "process_s",
                                "total_s",
                            )
                        }
                    )
                )
                for var, info in rep.versions.items():
                    val = info["validation"]
                    print(
                        f"  {var}: v{info['version']} {info['months']} months, valid {val['valid_share']:.0%}, mean {val['area_mean']}"
                    )
            except (LoginRequired, ProductBusy) as e:
                conn.rollback()
                print(f"{pid}: SKIPPED, {e}", file=sys.stderr)
                reports.append({"product": pid, "skipped": str(e)})
            except Exception as e:  # noqa: BLE001 - record it, carry on with the next product
                conn.rollback()
                logging.exception("%s failed", pid)
                reports.append({"product": pid, "error": f"{type(e).__name__}: {e}"[:500]})
                failed = True
        log_path = settings().data_dir / f"ingest_{args.cmd}_report.json"
        old = json.loads(log_path.read_text()) if log_path.exists() else {}
        for r in reports:
            old[r["product"]] = r

        def dump(o) -> str:
            return json.dumps(
                o, indent=1, default=lambda x: x.tolist() if isinstance(x, np.ndarray) else str(x)
            )

        log_path.write_text(dump(old))
        if args.report_json:
            args.report_json.parent.mkdir(parents=True, exist_ok=True)
            args.report_json.write_text(dump(reports))
        if failed:
            conn.close()
            raise SystemExit(1)
    elif args.cmd == "precompute":
        cmd_precompute(conn, args.variables, args.countries)
    elif args.cmd == "giovanni-check":
        from .download import LoginRequired
        from .giovanni import check

        for var in args.variables:
            try:
                print(json.dumps(check(conn, var, points_per_side=args.points), indent=1))
            except (LoginRequired, RuntimeError, KeyError) as e:
                conn.rollback()
                print(f"{var}: not checked: {e}", file=sys.stderr)
    elif args.cmd == "gistemp-check":
        print(json.dumps(cmd_gistemp_check(conn), indent=1))
    elif args.cmd == "admin-token":
        from megavir.imports.admin import admin_token, token_file, token_source

        print(admin_token())
        where = "MEGAVIR_ADMIN_TOKEN" if token_source() == "setting" else str(token_file())
        print(f"(from {where}; enter it on the Data import page)", file=sys.stderr)
    elif args.cmd == "access-check":
        from .access import check_access

        print(json.dumps(check_access()))
    elif args.cmd == "status":
        cmd_status(conn)
    conn.close()


if __name__ == "__main__":
    main()
