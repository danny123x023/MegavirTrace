"""What is stored, side by side with NASA, and the import history."""

from __future__ import annotations

import datetime as dt

from megavir.catalog import DATASETS, VARIABLES
from megavir.ingest.products import PRODUCTS

from .nasa import cached_catalog, month_abs, month_label, product_info
from .state import ensure

VARIABLE_PRODUCT = {v: pid for pid, p in PRODUCTS.items() for v in p.outputs}
PRODUCT_BY_NAME = {DATASETS[pid].product: pid for pid in PRODUCTS}


def _active(conn) -> dict[str, dict]:
    rows = conn.execute(
        """SELECT id, variable, kind, res_deg, month0, n_months, source, created_at
           FROM grid_version WHERE active ORDER BY variable"""
    ).fetchall()
    return {r["variable"]: dict(r) for r in rows}


def _iso(t) -> str | None:
    return t.isoformat() if t else None


def _compare(nasa: dict, db_last: int | None) -> tuple[str, int]:
    """('up_to_date' | 'newer' | 'unknown', newer months at NASA)."""
    if db_last is None or not nasa.get("last_month"):
        return "unknown", 0
    newer = month_abs(nasa["last_month"]) - db_last
    return ("newer", newer) if newer > 0 else ("up_to_date", 0)


def catalog_rows(conn) -> dict:
    nasa_all = cached_catalog(conn)
    active = _active(conn)
    rows = []
    for pid in PRODUCTS:
        info = product_info(pid)
        nasa = nasa_all["products"].get(pid, {})
        vs = [active[v] for v in info["variables"] if v in active]
        real = [v for v in vs if v["kind"] == "real"]
        db = None
        if real:
            db = {
                "first_month": month_label(min(v["month0"] for v in real)),
                # the variable that lags decides whether the source is up to date
                "last_month": month_label(min(v["month0"] + v["n_months"] - 1 for v in real)),
                "imported_at": _iso(max(v["created_at"] for v in real)),
                "variables": [v["variable"] for v in real],
            }
            compare, newer = _compare(nasa, month_abs(db["last_month"]))
            status = {"newer": "newer", "up_to_date": "up_to_date"}.get(compare, "in_database")
        else:
            newer = 0
            status = "stand_in" if vs else "not_imported"
        rows.append({**info, "nasa": nasa, "db": db, "status": status, "newer_months": newer})
    counts = {
        "all": len(rows),
        "in_database": sum(r["db"] is not None for r in rows),
        "newer": sum(r["status"] == "newer" for r in rows),
        "not_imported": sum(r["db"] is None for r in rows),
        "up_to_date": sum(r["status"] == "up_to_date" for r in rows),
    }
    return {"checked_at": nasa_all.get("checked_at"), "rows": rows, "counts": counts}


def database_rows(conn) -> dict:
    nasa_all = cached_catalog(conn)
    active = _active(conn)
    sizes = {}
    if active:
        ids = [v["id"] for v in active.values()]
        sizes = {
            r["version_id"]: int(r["size"])
            for r in conn.execute(
                "SELECT version_id, sum(pg_column_size(data)) AS size FROM grid_tile WHERE version_id = ANY(%s) GROUP BY version_id",
                (ids,),
            ).fetchall()
        }
    now = dt.datetime.now(dt.UTC)
    rows = []
    for vid, var in VARIABLES.items():
        pid = VARIABLE_PRODUCT.get(vid)
        d = DATASETS[pid] if pid else None
        v = active.get(vid)
        row = {
            "variable": vid,
            "name": var.name,
            "theme": var.theme,
            "product": pid,
            "product_title": d.product if d else None,
            "archive": d.archive if d else None,
            "kind": v["kind"] if v else None,
        }
        if v:
            last = v["month0"] + v["n_months"] - 1
            compare, newer = (
                _compare(nasa_all["products"].get(pid, {}), last) if v["kind"] == "real" else ("stand_in", 0)
            )
            row.update(
                {
                    "version": v["id"],
                    "first_month": month_label(v["month0"]),
                    "last_month": month_label(last),
                    "months": v["n_months"],
                    "res_deg": v["res_deg"],
                    "size_bytes": sizes.get(v["id"]),
                    "download_bytes": (v["source"] or {}).get("bytes"),
                    "imported_at": _iso(v["created_at"]),
                    "stored_days": round((now - v["created_at"]).total_seconds() / 86400, 1),
                    "compare": compare,
                    "newer_months": newer,
                    "nasa_last_month": (nasa_all["products"].get(pid) or {}).get("last_month"),
                }
            )
        rows.append(row)
    counts = {
        "all": len(rows),
        "real": sum(r["kind"] == "real" for r in rows),
        "stand_in": sum(r["kind"] in ("test", "synthetic") for r in rows),
        "nothing": sum(r["kind"] is None for r in rows),
    }
    return {"rows": rows, "counts": counts}


def history(
    conn, status: str | None = None, variable: str | None = None, page: int = 1, per_page: int = 15
) -> dict:
    """Dashboard jobs, plus versions imported from the command line (not made by any job)."""
    ensure(conn)
    jobs = conn.execute("SELECT * FROM import_job ORDER BY id DESC LIMIT 1000").fetchall()
    by_jobs = {r["version"] for j in jobs for r in (j["results"] or {}).values() if r.get("version")}
    items = []
    for j in jobs:
        took = None
        if j["started_at"] and j["finished_at"]:
            took = (j["finished_at"] - j["started_at"]).total_seconds()
        items.append(
            {
                "kind": "job",
                "id": j["id"],
                "product": j["product"],
                "product_title": DATASETS[j["product"]].product if j["product"] in DATASETS else j["product"],
                "variables": j["variables"],
                "status": j["status"],
                "started_at": _iso(j["started_at"] or j["created_at"]),
                "took_s": took,
                "summary": j["summary"],
                "results": j["results"],
                "requested_by": j["requested_by"],
            }
        )
    versions = conn.execute(
        """SELECT id, variable, kind, n_months, source, created_at FROM grid_version
           WHERE kind IN ('real', 'test') ORDER BY id DESC LIMIT 1000"""
    ).fetchall()
    for v in versions:
        if v["id"] in by_jobs:
            continue
        src = v["source"] or {}
        pid = VARIABLE_PRODUCT.get(v["variable"]) or PRODUCT_BY_NAME.get(src.get("product"))
        items.append(
            {
                "kind": "command_line",
                "id": f"v{v['id']}",
                "product": pid,
                "product_title": src.get("product") or pid,
                "variables": [v["variable"]],
                "status": "done",
                "started_at": _iso(v["created_at"]),
                "took_s": None,
                "summary": f"imported from the command line ({'test box' if v['kind'] == 'test' else 'whole record'}, {v['n_months']} months)",
                "results": {
                    v["variable"]: {"action": "imported", "version": v["id"], "months": v["n_months"]}
                },
                "requested_by": "command line",
            }
        )
    if status:
        items = [i for i in items if i["status"] == status]
    if variable:
        q = variable.lower()
        items = [
            i
            for i in items
            if any(q in x.lower() for x in i["variables"]) or q in (i["product"] or "").lower()
        ]
    items.sort(key=lambda i: i["started_at"] or "", reverse=True)
    total = len(items)
    page = max(1, page)
    return {
        "items": items[(page - 1) * per_page : page * per_page],
        "total": total,
        "page": page,
        "per_page": per_page,
    }
