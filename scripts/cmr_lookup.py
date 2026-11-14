"""Look up collections in NASA's public Common Metadata Repository (no login needed).

Usage: python scripts/cmr_lookup.py SHORT_NAME[:VERSION] ...
Prints DOI, provider, concept id, title and temporal start for each match.
"""

from __future__ import annotations

import sys

import httpx

CMR = "https://cmr.earthdata.nasa.gov/search/collections.umm_json"


def lookup(arg: str) -> None:
    short, _, version = arg.partition(":")
    params = {"short_name": short, "page_size": 5}
    if version:
        params["version"] = version
    r = httpx.get(CMR, params=params, timeout=60)
    r.raise_for_status()
    items = r.json().get("items", [])
    if not items:
        print(f"{arg:45s} NOT FOUND")
    for it in items:
        u, m = it["umm"], it["meta"]
        doi = (u.get("DOI") or {}).get("DOI")
        te = (u.get("TemporalExtents") or [{}])[0]
        rng = (te.get("RangeDateTimes") or [{}])[0]
        print(
            f"{arg:45s} v={u.get('Version')!s:10s} doi={doi!s:35s} {m['provider-id']:12s} "
            f"{m['concept-id']:22s} start={rng.get('BeginningDateTime')} | {u.get('EntryTitle', '')[:90]}"
        )


if __name__ == "__main__":
    for a in sys.argv[1:]:
        try:
            lookup(a)
        except Exception as e:  # noqa: BLE001
            print(f"{a:45s} ERROR {e}")
