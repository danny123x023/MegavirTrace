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

Sessions: the web pages trade the token once for a session (POST /admin/sessions) and then send
the X-Admin-Session header, so the token itself is not kept in the browser.  Only a hash of the
session secret is stored; sessions end after 12 hours without use (30 days with "keep me signed
in"), can be listed and revoked from the Admin panel, and all of them can be ended at once.
Scripts may still send X-Admin-Token directly.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import ipaddress
import os
import re
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


def token_ok(given: str) -> bool:
    return bool(given) and hmac.compare_digest(given.encode(), admin_token().encode())


# --------------------------------------------------------------------------------------
# Sessions
# --------------------------------------------------------------------------------------

SESSION_HOURS = 12  # without "keep me signed in"
REMEMBER_DAYS = 30
_TOUCH_EVERY = dt.timedelta(seconds=60)


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _ttl(remember: bool) -> dt.timedelta:
    return dt.timedelta(days=REMEMBER_DAYS) if remember else dt.timedelta(hours=SESSION_HOURS)


def browser_label(user_agent: str) -> str:
    """ "Firefox on Windows" from a User-Agent string (for the session list only)."""
    ua = user_agent or ""
    browser = next(
        (name for pat, name in (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"), ("Chrome/", "Chrome"),
                                ("Safari/", "Safari"), ("curl/", "curl"), ("python", "a script")) if pat in ua),
        "a browser",
    )  # fmt: skip
    system = next(
        (name for pat, name in (("Windows", "Windows"), ("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"),
                                ("Mac OS", "macOS"), ("CrOS", "ChromeOS"), ("Linux", "Linux")) if pat in ua),
        "",
    )  # fmt: skip
    return f"{browser} on {system}" if system else browser


def describe_session(row: dict, current: str | None = None) -> dict:
    return {
        "id": row["id_hash"][:12],
        "created_at": row["created_at"].isoformat(),
        "last_seen": row["last_seen"].isoformat(),
        "expires_at": row["expires_at"].isoformat(),
        "remember": row["remember"],
        "browser": browser_label(row["user_agent"]),
        "current": current is not None and row["id_hash"] == current,
    }


def new_session(conn, user_agent: str, remember: bool) -> tuple[str, dict]:
    """A new session: (the secret for the browser, its public description)."""
    from .state import ensure

    ensure(conn)
    secret = secrets.token_urlsafe(32)
    now = dt.datetime.now(dt.UTC)
    conn.execute("DELETE FROM admin_session WHERE expires_at < now()")
    row = conn.execute(
        """INSERT INTO admin_session (id_hash, created_at, last_seen, expires_at, remember, user_agent)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
        (_hash(secret), now, now, now + _ttl(remember), remember, (user_agent or "")[:300]),
    ).fetchone()
    conn.commit()
    return secret, describe_session(row, row["id_hash"])


def find_session(conn, secret: str) -> dict | None:
    """The live session for a secret (its expiry moves on with use), or None."""
    from .state import ensure

    if not secret or len(secret) > 200:
        return None
    ensure(conn)
    row = conn.execute(
        "SELECT * FROM admin_session WHERE id_hash = %s AND expires_at > now()", (_hash(secret),)
    ).fetchone()
    if not row:
        return None
    now = dt.datetime.now(dt.UTC)
    if now - row["last_seen"] > _TOUCH_EVERY:
        row = conn.execute(
            "UPDATE admin_session SET last_seen = %s, expires_at = %s WHERE id_hash = %s RETURNING *",
            (now, now + _ttl(row["remember"]), row["id_hash"]),
        ).fetchone()
        conn.commit()
    return row


def list_sessions(conn, current_secret: str | None = None) -> list[dict]:
    from .state import ensure

    ensure(conn)
    current = _hash(current_secret) if current_secret else None
    rows = conn.execute(
        "SELECT * FROM admin_session WHERE expires_at > now() ORDER BY last_seen DESC"
    ).fetchall()
    return [describe_session(r, current) for r in rows]


def end_session(conn, public_id: str) -> bool:
    if not re.fullmatch(r"[0-9a-f]{12}", public_id or ""):
        return False
    n = conn.execute("DELETE FROM admin_session WHERE left(id_hash, 12) = %s", (public_id,)).rowcount
    conn.commit()
    return n > 0


def end_other_sessions(conn, current_secret: str | None) -> int:
    keep = _hash(current_secret) if current_secret else ""
    n = conn.execute("DELETE FROM admin_session WHERE id_hash <> %s", (keep,)).rowcount
    conn.commit()
    return n


def session_secret(request: Request) -> str:
    return request.headers.get("x-admin-session", "")


def request_role(request: Request) -> str | None:
    """'admin' (session or token), 'local' (provably the server itself) or None (viewing only)."""
    if token_ok(request.headers.get("x-admin-token", "")):
        return "admin"
    secret = session_secret(request)
    if secret:
        from megavir.store import connect

        with connect() as conn:
            if find_session(conn, secret):
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
