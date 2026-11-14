"""Downloads: resumable HTTPS, CMR granule search, Earthdata Login, OPeNDAP (DAP4) subsets.

Credentials are never stored by this code.  Earthdata Login is taken from the standard
places that ``earthaccess`` reads: the EARTHDATA_TOKEN or EARTHDATA_USERNAME /
EARTHDATA_PASSWORD environment variables, or ~/.netrc.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import httpx

CMR_GRANULES = "https://cmr.earthdata.nasa.gov/search/granules.umm_json"
USER_AGENT = "MegavirTrace-ingest/0.1 (+https://github.com/; open-source NASA Space Apps project)"


class LoginRequired(RuntimeError):
    pass


# --------------------------------------------------------------------------------------
# CMR
# --------------------------------------------------------------------------------------


@dataclass
class Granule:
    ur: str
    begin: str  # ISO date-time
    end: str
    data_url: str | None
    opendap_url: str | None
    size_mb: float | None = None
    extra: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return (self.data_url or self.ur).rstrip("/").split("/")[-1]


def cmr_granules(concept_id: str, start: str, end: str, page_size: int = 2000) -> list[Granule]:
    """All granules of a collection in a time range (public, no login)."""
    out: list[Granule] = []
    headers = {"User-Agent": USER_AGENT}
    search_after = None
    with httpx.Client(timeout=120, headers=headers) as client:
        while True:
            h = dict(headers)
            if search_after:
                h["CMR-Search-After"] = search_after
            r = client.get(
                CMR_GRANULES,
                params={
                    "collection_concept_id": concept_id,
                    "temporal": f"{start},{end}",
                    "page_size": page_size,
                    "sort_key": "start_date",
                },
                headers=h,
            )
            r.raise_for_status()
            items = r.json().get("items", [])
            for it in items:
                u = it["umm"]
                rng = (u.get("TemporalExtent") or {}).get("RangeDateTime") or {}
                data_url = opendap = None
                for ru in u.get("RelatedUrls", []):
                    url = ru.get("URL", "")
                    if url.startswith("s3://"):
                        continue
                    if (
                        ru.get("Type") == "GET DATA"
                        and not data_url
                        and not url.endswith((".xml", ".md5", ".sha512"))
                    ):
                        data_url = url
                    if ru.get("Type") == "USE SERVICE API" and "opendap" in url.lower():
                        opendap = url
                size = None
                for ai in (u.get("DataGranule") or {}).get("ArchiveAndDistributionInformation", []) or []:
                    if ai.get("SizeInBytes"):
                        size = ai["SizeInBytes"] / 1e6
                    elif ai.get("Size") and ai.get("SizeUnit") == "MB":
                        size = float(ai["Size"])
                out.append(
                    Granule(
                        u["GranuleUR"],
                        rng.get("BeginningDateTime", ""),
                        rng.get("EndingDateTime", ""),
                        data_url,
                        opendap,
                        size,
                    )
                )
            search_after = r.headers.get("CMR-Search-After")
            if not items or not search_after:
                break
    return out


# --------------------------------------------------------------------------------------
# Sessions
# --------------------------------------------------------------------------------------


def earthdata_session():
    """An authenticated requests.Session for Earthdata archives, or raise LoginRequired."""
    import earthaccess

    has_env = os.environ.get("EARTHDATA_TOKEN") or (
        os.environ.get("EARTHDATA_USERNAME") and os.environ.get("EARTHDATA_PASSWORD")
    )
    has_netrc = (Path.home() / ".netrc").exists() or (Path.home() / "_netrc").exists()
    if not (has_env or has_netrc):
        raise LoginRequired(
            "This product needs a free NASA Earthdata Login. Set EARTHDATA_TOKEN (or EARTHDATA_USERNAME and "
            "EARTHDATA_PASSWORD), or add 'machine urs.earthdata.nasa.gov login ... password ...' to ~/.netrc."
        )
    auth = earthaccess.login(strategy="environment" if has_env else "netrc", persist=False)
    if not auth or not getattr(auth, "authenticated", False):
        raise LoginRequired("Earthdata Login failed: check the credentials.")
    s = earthaccess.get_requests_https_session()
    s.headers["User-Agent"] = USER_AGENT
    return s


class PublicSession:
    """Minimal requests-like wrapper around httpx for public archives."""

    def __init__(self):
        self.client = httpx.Client(
            timeout=httpx.Timeout(60, read=300), follow_redirects=True, headers={"User-Agent": USER_AGENT}
        )

    def get(self, url, headers=None, stream=False, timeout=None):  # noqa: ARG002
        return _HttpxResponse(self.client, url, headers or {})


class _HttpxResponse:
    def __init__(self, client, url, headers):
        self._cm = client.stream("GET", url, headers=headers)
        self._r = self._cm.__enter__()
        self.status_code = self._r.status_code
        self.headers = self._r.headers

    def iter_content(self, chunk_size=1 << 20):
        yield from self._r.iter_bytes(chunk_size)

    @property
    def text(self):
        return self._r.read().decode()

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(f"HTTP {self.status_code}", request=self._r.request, response=self._r)

    def close(self):
        self._cm.__exit__(None, None, None)


# --------------------------------------------------------------------------------------
# Resumable download
# --------------------------------------------------------------------------------------


def download(url: str, dest: Path, session, retries: int = 5) -> dict:
    """Download to ``dest`` (resuming a ``.part`` file).  Returns {"bytes", "seconds", "skipped"}."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return {"bytes": dest.stat().st_size, "seconds": 0.0, "skipped": True}
    part = dest.with_name(dest.name + ".part")
    t0 = time.time()
    for attempt in range(retries):
        have = part.stat().st_size if part.exists() else 0
        headers = {"Range": f"bytes={have}-"} if have else {}
        try:
            r = session.get(url, headers=headers, stream=True, timeout=300)
            if r.status_code == 416:  # already complete
                r.close()
                break
            if r.status_code in (401, 403):
                r.close()
                raise LoginRequired(f"access denied ({r.status_code}) for {url}")
            r.raise_for_status()
            mode = "ab" if have and r.status_code == 206 else "wb"
            with open(part, mode) as fh:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    if chunk:
                        fh.write(chunk)
            r.close()
            break
        except LoginRequired:
            raise
        except Exception:  # noqa: BLE001 - network hiccups: back off and resume
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))
    _check_not_html(part, url)
    part.rename(dest)
    return {"bytes": dest.stat().st_size, "seconds": time.time() - t0, "skipped": False}


def _check_not_html(path: Path, url: str) -> None:
    with open(path, "rb") as fh:
        head = fh.read(512).lstrip().lower()
    if head.startswith(b"<!doctype html") or head.startswith(b"<html"):
        path.unlink(missing_ok=True)
        raise LoginRequired(f"got an HTML page instead of data (probably a login page) from {url}")


# --------------------------------------------------------------------------------------
# OPeNDAP (DAP4)
# --------------------------------------------------------------------------------------


@dataclass
class DapVar:
    path: (
        str  # full DAP4 path, e.g. /HDFEOS/GRIDS/ColumnAmountNO2/Data_Fields/ColumnAmountNO2TropCloudScreened
    )
    dims: list[tuple[str, int]]


def parse_dmr(xml_text: str) -> dict[str, DapVar]:
    """Map every variable's full path to its dimensions, from a DAP4 DMR document."""
    root = ET.fromstring(xml_text)
    ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""
    types = {
        "Float32",
        "Float64",
        "Int8",
        "Int16",
        "Int32",
        "Int64",
        "UInt8",
        "UInt16",
        "UInt32",
        "UInt64",
        "Byte",
    }
    dim_sizes: dict[str, int] = {}
    out: dict[str, DapVar] = {}

    def walk(node, prefix):
        for child in node:
            tag = child.tag.replace(ns, "")
            if tag == "Dimension":
                dim_sizes[f"{prefix}/{child.get('name')}"] = int(child.get("size"))
                dim_sizes[child.get("name")] = int(child.get("size"))
            elif tag == "Group":
                walk(child, f"{prefix}/{child.get('name')}")
            elif tag in types:
                dims = []
                for d in child:
                    if d.tag.replace(ns, "") == "Dim":
                        name = d.get("name") or ""
                        size = d.get("size")
                        key = name if name.startswith("/") else f"{prefix}/{name}"
                        sz = int(size) if size else dim_sizes.get(key, dim_sizes.get(name.split("/")[-1], -1))
                        dims.append((name.split("/")[-1], sz))
                path = f"{prefix}/{child.get('name')}"
                out[path] = DapVar(path, dims)

    walk(root, "")
    return out


def sanitize(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name)


def find_var(vars_: dict[str, DapVar], wanted: str) -> DapVar:
    w = sanitize(wanted).lower()
    hits = [v for p, v in vars_.items() if sanitize(p.split("/")[-1]).lower() == w]
    if not hits:
        raise KeyError(f"variable {wanted!r} not found; available: {sorted(vars_)[:40]}")
    return sorted(hits, key=lambda v: len(v.path))[0]


def dap4_url(base: str, constraints: list[str]) -> str:
    ce = ";".join(constraints)
    return f"{base}.dap.nc4?dap4.ce=" + urllib.parse.quote(ce, safe="/:")


def slice_constraint(var: DapVar, ranges: dict[int, tuple[int, int]]) -> str:
    """ranges maps a dimension *size* to (start, stop_inclusive); other dims are taken whole."""
    parts = []
    for _, size in var.dims:
        if size in ranges:
            a, b = ranges[size]
            parts.append(f"[{a}:1:{b}]")
        else:
            parts.append(f"[0:1:{size - 1}]")
    return var.path + "".join(parts)


def save_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, default=str))
