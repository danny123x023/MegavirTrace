"""What NASA holds now, per product (public catalogue queries, no login).

* Products in NASA's Common Metadata Repository (CMR): oldest and newest granule, number of
  files, and an estimated total size (mean of the newest files x count).
* GISTEMP: NASA GISS's official global table gives the newest month; a HEAD request the size.
* GRACE (GSFC mascons): the file name on NASA GSFC's page carries the first and last month.

For daily and weekly products only complete months count, so an import never looks out of date
just because NASA has added a few days of the current month.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
from concurrent.futures import ThreadPoolExecutor

import httpx

from megavir.catalog import DATASETS
from megavir.ingest import download as dl
from megavir.ingest.products import PRODUCTS
from megavir.ingest.validate import GISTEMP_GLOBAL_CSV

from .state import get_state, set_state

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def month_abs(label: str) -> int:
    return int(label[:4]) * 12 + int(label[5:7]) - 1


def month_label(m: int) -> str:
    return f"{m // 12:04d}-{m % 12 + 1:02d}"


def last_complete_month(iso_end: str) -> str:
    """The newest month fully covered by daily or weekly files ending at ``iso_end``."""
    d = dt.date.fromisoformat(iso_end[:10])
    if (d + dt.timedelta(days=1)).month != d.month:
        return d.strftime("%Y-%m")
    return month_label(month_abs(d.strftime("%Y-%m")) - 1)


def _head_size(url: str) -> int | None:
    r = httpx.head(url, timeout=30, follow_redirects=True, headers={"User-Agent": dl.USER_AGENT})
    r.raise_for_status()
    n = r.headers.get("content-length")
    return int(n) if n and n.isdigit() else None


def _gistemp() -> dict:
    text = httpx.get(
        GISTEMP_GLOBAL_CSV, timeout=30, follow_redirects=True, headers={"User-Agent": dl.USER_AGENT}
    ).text
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("Year"))
    last = None
    for row in csv.DictReader(io.StringIO("\n".join(lines[start:]))):
        for k, name in enumerate(MONTHS):
            v = (row.get(name) or "").strip()
            if v and "*" not in v:
                last = f"{int(row['Year']):04d}-{k + 1:02d}"
    url = PRODUCTS["gistemp"].public_urls("full", 1880, 1880)[0][0]
    return {
        "first_month": "1880-01",
        "last_month": last,
        "files": 1,
        "bytes": _head_size(url),
        "approx_size": False,
    }


def _grace() -> dict:
    from megavir.ingest.pipeline import _resolve_grace_url

    url, name = _resolve_grace_url()
    m = re.search(r"(\d{6})_(\d{6})", name)
    first = f"{m.group(1)[:4]}-{m.group(1)[4:]}" if m else None
    last = f"{m.group(2)[:4]}-{m.group(2)[4:]}" if m else None
    return {
        "first_month": first,
        "last_month": last,
        "files": 1,
        "bytes": _head_size(url),
        "approx_size": False,
    }


def check_product(pid: str) -> dict:
    p = PRODUCTS[pid]
    try:
        if p.concept_id:
            s = dl.cmr_summary(p.concept_id, p.granule_filter)
            if p.multi_time:
                last = s["last_end"][:7]
            elif p.cadence == "monthly":
                last = s["last_begin"][:7]
            else:
                last = last_complete_month(s["last_end"] or s["last_begin"])
            first = s["first_begin"][:7]
            if p.cadence != "monthly" and s["first_begin"][8:10] != "01":  # first month only partly covered
                first = month_label(month_abs(first) + 1)
            return {
                "first_month": first,
                "last_month": last,
                "files": s["files"],
                "bytes": s["bytes"],
                "approx_size": True,
            }
        if pid == "gistemp":
            return _gistemp()
        if pid == "grace":
            return _grace()
        return {"error": "NASA's catalogue does not list this source"}
    except Exception as e:  # noqa: BLE001 - one source failing must not hide the others
        return {"error": (str(e).strip().splitlines() or [type(e).__name__])[0][:200]}


def refresh_catalog(connect, workers: int = 8) -> dict:
    started = dt.datetime.now(dt.UTC)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = dict(zip(PRODUCTS, ex.map(check_product, PRODUCTS), strict=True))
    value = {"checked_at": started.isoformat(), "products": results}
    with connect() as conn:
        set_state(conn, "nasa_catalog", value)
    return value


def cached_catalog(conn) -> dict:
    return get_state(conn, "nasa_catalog") or {"checked_at": None, "products": {}}


def access_note(pid: str) -> str:
    p = PRODUCTS[pid]
    if p.access == "opendap":
        return (
            "OPeNDAP subset: only "
            + ", ".join(f.split("/")[-1] for f in p.fields)
            + " (far smaller than the whole files)"
        )
    if p.access == "download":
        return "whole files over HTTPS"
    return "public file" + ("s" if p.public_urls and p.id == "micasa" else "")


def product_info(pid: str) -> dict:
    p, d = PRODUCTS[pid], DATASETS[pid]
    return {
        "id": pid,
        "title": d.title,
        "short_name": d.product,
        "archive": d.archive,
        "login_required": p.access in ("opendap", "download"),
        "access_note": access_note(pid),
        "cadence": p.cadence,
        "variables": list(p.outputs),
    }
