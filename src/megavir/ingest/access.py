"""Can this server download each Earthdata product?  (``megavir-ingest access-check``)

For every product behind Earthdata Login the newest granule is looked up in NASA's public
catalogue, then fetched the way an import would: the OPeNDAP description (DMR) for subset
products, which also confirms the variables are there, or the first 1024 bytes of the file for
whole-file products.  Nothing is stored; the import dashboard keeps the result.
"""

from __future__ import annotations

import time

from . import download as dl
from .products import PRODUCTS

HINTS = {
    401: "Earthdata Login refused the username or password",
    403: "Earthdata Login refused access: approve this archive's application in your Earthdata Login profile",
    404: "the newest file is not where NASA's catalogue says",
}


def _short(e: Exception) -> str:
    status = getattr(getattr(e, "response", None), "status_code", None)
    if status in HINTS:
        return f"{HINTS[status]} (HTTP {status})"
    text = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
    return text[:200]


def check_product(pid: str, session) -> dict:
    p = PRODUCTS[pid]
    t0 = time.time()
    out = {"product": pid, "access": p.access, "ok": False, "detail": ""}
    try:
        newest = dl.cmr_summary(p.concept_id, p.granule_filter, sample=20)["newest"]
        if p.access == "opendap":
            if not newest.opendap_url:
                raise RuntimeError("the newest file has no OPeNDAP address")
            r = session.get(newest.opendap_url + ".dmr.xml", timeout=60)
            r.raise_for_status()
            found = [dl.find_var(dl.parse_dmr(r.text), f).path.split("/")[-1] for f in p.fields]
            out["detail"] = "OPeNDAP works, found " + ", ".join(found)
        else:
            r = session.get(newest.data_url, headers={"Range": "bytes=0-1023"}, stream=True, timeout=60)
            r.raise_for_status()
            chunk = next(r.iter_content(1024), b"")
            r.close()
            if chunk[:200].lstrip().lower().startswith((b"<!doctype html", b"<html")):
                raise RuntimeError("got a web page instead of the file (the login did not go through)")
            out["detail"] = f"downloads work (read {len(chunk)} bytes of the newest file)"
        out["ok"] = True
    except Exception as e:  # noqa: BLE001 - every failure is reported, none stops the others
        out["detail"] = _short(e)
    out["seconds"] = round(time.time() - t0, 1)
    return out


def check_access() -> dict:
    pids = [pid for pid, p in PRODUCTS.items() if p.access in ("opendap", "download")]
    try:
        session = dl.earthdata_session()
    except dl.LoginRequired as e:
        return {
            "login": False,
            "results": [
                {"product": pid, "access": PRODUCTS[pid].access, "ok": False, "detail": str(e)}
                for pid in pids
            ],
        }
    return {"login": True, "results": [check_product(pid, session) for pid in pids]}
