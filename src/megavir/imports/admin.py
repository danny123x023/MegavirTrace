"""Who may start imports, delete jobs or change the Earthdata account.

Viewing the dashboard is open.  Acting needs the administrator token (sent by the page as the
X-Admin-Token header), or a request that provably comes from the server itself.

Why the web page always needs the token: the web app's proxy (Next.js rewrites) forwards
requests to the API from 127.0.0.1 and does not pass the visitor's address on, and the
X-Forwarded-For header it gives its own handlers keeps whatever the visitor sent.  Behind it,
"this computer" cannot be told apart from anyone else, so requests that came through a proxy are
never trusted as local.  Local means: a direct request to the API's own port from a loopback
address with no proxy headers (for example curl on the server), or, behind our nginx
(MEGAVIR_TRUST_PROXY=1), a loopback X-Real-IP, which nginx sets from the real connection.

The token is MEGAVIR_ADMIN_TOKEN if set; otherwise a random one is created on first use in
data/admin_token (owner read/write only).  ``megavir-ingest admin-token`` prints it on the server.
"""

from __future__ import annotations

import hmac
import ipaddress
import os
import secrets
from pathlib import Path

from fastapi import HTTPException, Request

from megavir.api.security import settings_trust_proxy
from megavir.config import settings

PROXY_HEADERS = ("x-forwarded-host", "x-forwarded-for", "x-real-ip", "forwarded")


def token_file() -> Path:
    return settings().data_dir / "admin_token"


def admin_token() -> str:
    """The administrator token: from the settings, else from (or newly into) data/admin_token."""
    if settings().admin_token:
        return settings().admin_token
    path = token_file()
    try:
        return path.read_text().strip()
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(24)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:  # another process made it first
        return path.read_text().strip()
    with os.fdopen(fd, "w") as fh:
        fh.write(token + "\n")
    return token


def token_source() -> str:
    return "setting" if settings().admin_token else "file"


def _loopback(addr: str | None) -> bool:
    if not addr:
        return False
    addr = addr.strip().split("%")[0]
    if addr.startswith("[") and "]" in addr:
        addr = addr[1 : addr.index("]")]
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return addr == "localhost"
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_loopback


def request_role(request: Request) -> str | None:
    """'admin' (token), 'local' (provably the server itself) or None (viewing only)."""
    given = request.headers.get("x-admin-token", "")
    if given and hmac.compare_digest(given.encode(), admin_token().encode()):
        return "admin"
    if settings_trust_proxy():
        return "local" if _loopback(request.headers.get("x-real-ip")) else None
    if any(h in request.headers for h in PROXY_HEADERS):
        return None  # came through a proxy: the visitor's address is unknown
    return "local" if _loopback(request.client.host if request.client else None) else None


def require_role(request: Request) -> str:
    role = request_role(request)
    if role is None:
        raise HTTPException(
            403,
            "Imports, deletions and account changes need the administrator token "
            "(on the server: megavir-ingest admin-token).",
        )
    return role
