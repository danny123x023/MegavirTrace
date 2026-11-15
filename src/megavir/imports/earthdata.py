"""The Earthdata Login on this server, and whether each product can be downloaded with it.

The login lives where ``earthaccess`` (and curl) look for it: the EARTHDATA_* environment
variables, or the ``machine urs.earthdata.nasa.gov`` entry of the netrc file
(MEGAVIR_NETRC_PATH, else $NETRC, else ~/.netrc).  The dashboard can replace or remove that
entry.  The password is written only to that file (owner read/write only) and is never
stored in the database, logged or sent back to the browser.
"""

from __future__ import annotations

import datetime as dt
import json
import netrc
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import httpx

from megavir.config import ROOT, settings

from .state import get_state, set_state

URS_HOST = "urs.earthdata.nasa.gov"
URS_TOKENS = f"https://{URS_HOST}/api/users/tokens"  # GET with the login: lists tokens, changes nothing
_BAD_CHARS = set(" \t\r\n\"'#\\")


class LoginError(ValueError):
    """The username or password cannot be used (rejected by NASA, or not storable)."""


def netrc_path() -> Path:
    if settings().netrc_path:
        return Path(settings().netrc_path).expanduser()
    env = os.environ.get("NETRC")
    return Path(env) if env else Path.home() / ".netrc"


def child_env() -> dict:
    """Environment for import and check processes: the same login the dashboard shows."""
    env = dict(os.environ)
    env["NETRC"] = str(netrc_path())
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _read() -> netrc.netrc | None:
    path = netrc_path()
    if not path.exists():
        return None
    return netrc.netrc(str(path))


def login_status(show_username: bool) -> dict:
    """How this server logs in to Earthdata.  The username only for people who may act."""
    if os.environ.get("EARTHDATA_TOKEN"):
        return {
            "configured": True,
            "method": "token",
            "where": "EARTHDATA_TOKEN (environment)",
            "username": None,
        }
    if os.environ.get("EARTHDATA_USERNAME") and os.environ.get("EARTHDATA_PASSWORD"):
        user = os.environ["EARTHDATA_USERNAME"] if show_username else None
        return {
            "configured": True,
            "method": "environment",
            "where": "EARTHDATA_USERNAME (environment)",
            "username": user,
        }
    path = netrc_path()
    where = "~/" + path.name if path.parent == Path.home() else str(path)
    try:
        entry = _read().authenticators(URS_HOST) if path.exists() else None
    except (netrc.NetrcParseError, OSError) as e:
        return {
            "configured": False,
            "method": "netrc",
            "where": where,
            "username": None,
            "problem": f"the file cannot be read: {e}",
        }
    if not entry:
        return {"configured": False, "method": "none", "where": where, "username": None}
    return {
        "configured": True,
        "method": "netrc",
        "where": where,
        "username": entry[0] if show_username else None,
    }


def verify_login(username: str, password: str) -> None:
    """Ask Earthdata Login whether the pair is valid (read-only request)."""
    try:
        r = httpx.get(URS_TOKENS, auth=(username, password), timeout=20, follow_redirects=False)
    except httpx.HTTPError as e:
        raise RuntimeError(f"could not reach Earthdata Login: {e}") from e
    if r.status_code in (401, 403):
        raise LoginError("Earthdata Login rejected this username or password.")
    if r.status_code != 200:
        raise RuntimeError(f"Earthdata Login answered HTTP {r.status_code}; try again later.")


def _check_storable(username: str, password: str) -> None:
    if not username or not password:
        raise LoginError("Enter both the username and the password.")
    if len(username) > 100 or len(password) > 200:
        raise LoginError("That is longer than an Earthdata Login allows.")
    if _BAD_CHARS & set(username + password):
        raise LoginError(
            "This password contains a space, quote, # or backslash, which a netrc file cannot hold. "
            "Set EARTHDATA_USERNAME and EARTHDATA_PASSWORD in the server's environment instead."
        )


def _write(entries: dict, macros: dict) -> None:
    """Rewrite the netrc file atomically, owner-only, keeping every other machine's entry."""
    path = netrc_path()
    lines = []
    for host, (login, account, password) in entries.items():
        head = "default" if host == "default" else f"machine {host}"
        parts = [head]
        if login:
            parts.append(f"login {login}")
        if account:
            parts.append(f"account {account}")
        if password:
            parts.append(f"password {password}")
        lines.append(" ".join(parts))
    for name, body in macros.items():
        lines.append(f"macdef {name}\n" + "".join(body))
    if not lines:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".netrc-")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write("\n".join(lines) + "\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _current() -> tuple[dict, dict]:
    n = _read()
    return (dict(n.hosts), dict(n.macros)) if n else ({}, {})


def save_login(username: str, password: str) -> dict:
    username = username.strip()
    _check_storable(username, password)
    verify_login(username, password)  # looked up at call time (tests replace it)
    hosts, macros = _current()
    # keep the Earthdata entry first, where people expect it
    hosts = {URS_HOST: (username, None, password), **{h: v for h, v in hosts.items() if h != URS_HOST}}
    _write(hosts, macros)
    return login_status(show_username=True)


def remove_login() -> dict:
    hosts, macros = _current()
    if URS_HOST in hosts:
        del hosts[URS_HOST]
        _write(hosts, macros)
    return login_status(show_username=True)


# --------------------------------------------------------------------------------------
# Can each product be downloaded?  (a child process, like an import, so it uses the same login)
# --------------------------------------------------------------------------------------

_check_lock = threading.Lock()


def access_check_command() -> list[str]:
    return [sys.executable, "-I", "-m", "megavir.ingest.cli", "access-check"]


def start_access_check(connect) -> dict:
    with connect() as conn:
        current = get_state(conn, "earthdata_check") or {}
        if current.get("status") == "checking" and _check_lock.locked():
            return current
        set_state(
            conn,
            "earthdata_check",
            {**{k: v for k, v in current.items() if k != "updated_at"}, "status": "checking"},
        )
    threading.Thread(target=_run_check, args=(connect,), daemon=True).start()
    return {"status": "checking"}


def _run_check(connect) -> None:
    with _check_lock:
        started = dt.datetime.now(dt.UTC)
        try:
            out = subprocess.run(
                access_check_command(), capture_output=True, text=True, timeout=300, env=child_env(), cwd=ROOT
            )
            lines = [ln for ln in out.stdout.splitlines() if ln.startswith("{")]
            if out.returncode != 0 or not lines:
                raise RuntimeError(
                    (out.stderr.strip().splitlines() or ["the check stopped without a result"])[-1][:300]
                )
            res = json.loads(lines[-1])
            value = {
                "status": "done",
                "checked_at": started.isoformat(),
                "login": res["login"],
                "results": res["results"],
                "ok": sum(r["ok"] for r in res["results"]),
                "total": len(res["results"]),
            }
        except Exception as e:  # noqa: BLE001 - shown on the page
            value = {
                "status": "failed",
                "checked_at": started.isoformat(),
                "error": str(e)[:300],
                "results": [],
            }
        with connect() as conn:
            set_state(conn, "earthdata_check", value)
