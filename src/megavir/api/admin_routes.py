"""Import dashboard API (web page "Data import").

Reading is open; acting (imports, deletions, Earthdata account, checks) needs this computer or
the administrator token, see ``megavir.imports.admin``.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from megavir import ai
from megavir.ai import config as ai_config
from megavir.api.security import SlidingWindow, client_ip
from megavir.imports import admin, earthdata, jobs, nasa, overview
from megavir.imports.admin import request_role, require_role, token_source
from megavir.imports.state import get_state
from megavir.store import connect

# wrong tokens: at most 10 tries per visitor in 10 minutes
_sign_in_failures = SlidingWindow(10, 600.0)

router = APIRouter(prefix="/admin", tags=["import dashboard"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class ImportIn(BaseModel):
    products: list[str] = Field(min_length=1, max_length=40)


class SignInIn(BaseModel):
    token: str = Field(min_length=1, max_length=200)
    remember: bool = False


class AiChoiceIn(BaseModel):
    active: Literal["anthropic", "zai", "none"] | None = None
    fallback: bool | None = None
    models: dict[str, str] | None = None


class AiKeyIn(BaseModel):
    api_key: str = Field(min_length=1, max_length=300)
    model: str | None = Field(None, max_length=80)


# --------------------------------------------------------------------------------------
# Sign-in sessions
# --------------------------------------------------------------------------------------


@router.post("/sessions")
def sign_in(body: SignInIn, request: Request):
    """Trade the administrator token for a session (the browser keeps only the session)."""
    ip = client_ip(request)
    if not admin.token_ok(body.token.strip()):
        ok, retry = _sign_in_failures.allow(ip)
        if not ok:
            raise HTTPException(429, f"Too many wrong tokens. Try again in {max(1, retry // 60)} minutes.")
        raise HTTPException(403, "That token is not right.")
    with connect() as conn:
        secret, info = admin.new_session(conn, request.headers.get("user-agent", ""), body.remember)
    return {"session": secret, "info": info}


@router.get("/sessions")
def sessions_list(request: Request):
    require_role(request)
    with connect() as conn:
        return {"sessions": admin.list_sessions(conn, admin.session_secret(request) or None)}


@router.delete("/sessions/current")
def sign_out(request: Request):
    """End the session this browser uses."""
    secret = admin.session_secret(request)
    with connect() as conn:
        found = admin.find_session(conn, secret) if secret else None
        if found:
            admin.end_session(conn, found["id_hash"][:12])
    return {"ended": bool(found)}


@router.delete("/sessions/{session_id}")
def session_end(session_id: str, request: Request):
    require_role(request)
    with connect() as conn:
        if not admin.end_session(conn, session_id):
            raise HTTPException(404, "no such session")
    return {"ended": True}


@router.delete("/sessions")
def sessions_end_others(request: Request):
    """Sign out everywhere else (this browser stays signed in)."""
    require_role(request)
    with connect() as conn:
        return {"ended": admin.end_other_sessions(conn, admin.session_secret(request) or None)}


# --------------------------------------------------------------------------------------
# AI service: keys, active service, models
# --------------------------------------------------------------------------------------


def _ai_view() -> dict:
    st = ai.status()
    return {
        **ai_config.public(),
        "usage": {k: st[k] for k in ("hourly_limit_per_visitor", "daily_cap", "used_today")},
    }


@router.get("/ai")
def ai_settings(request: Request):
    require_role(request)
    return _ai_view()


@router.put("/ai")
def ai_choose(body: AiChoiceIn, request: Request):
    require_role(request)
    try:
        ai_config.set_choice(body.active, body.fallback, body.models)
    except ai_config.SettingsError as e:
        raise HTTPException(422, str(e)) from None
    return _ai_view()


@router.put("/ai/keys/{provider}")
def ai_key_save(provider: Literal["anthropic", "zai"], body: AiKeyIn, request: Request):
    """Check a new key with the service; it is saved only if the service accepts it."""
    require_role(request)
    try:
        key = ai_config.check_key_format(provider, body.api_key)
        model = ai_config.check_model(body.model) if body.model else None
    except ai_config.SettingsError as e:
        raise HTTPException(422, str(e)) from None
    result = ai.test_key(provider, key, model or ai_config.provider(provider)["model"] or None)
    if not result["ok"]:
        raise HTTPException(422, result["detail"])
    ai_config.set_key(provider, key)
    if model:
        ai_config.set_choice(models={provider: model})
    return {**_ai_view(), "check": result}


@router.delete("/ai/keys/{provider}")
def ai_key_remove(provider: Literal["anthropic", "zai"], request: Request):
    require_role(request)
    ai_config.remove_key(provider)
    return _ai_view()


@router.post("/ai/test/{provider}")
def ai_key_test(provider: Literal["anthropic", "zai"], request: Request):
    require_role(request)
    return ai.test_key(provider)


# --------------------------------------------------------------------------------------
# Import dashboard
# --------------------------------------------------------------------------------------


@router.get("/overview")
def admin_overview(request: Request):
    role = request_role(request)
    with connect() as conn:
        check = get_state(conn, "earthdata_check")
        worker = jobs.worker_status(conn)
        secret = admin.session_secret(request)
        session = admin.find_session(conn, secret) if secret else None
    return {
        "role": role,
        "session": admin.describe_session(session, session["id_hash"]) if session else None,
        "can_act": role is not None,
        "token_source": token_source(),  # "setting" (MEGAVIR_ADMIN_TOKEN) or "file" (data/admin_token)
        "login": earthdata.login_status(show_username=role is not None),
        "access_check": check,
        "worker": worker,
    }


@router.put("/earthdata")
def admin_save_login(body: LoginIn, request: Request):
    require_role(request)
    try:
        return earthdata.save_login(body.username, body.password)
    except earthdata.LoginError as e:
        raise HTTPException(422, str(e)) from None
    except RuntimeError as e:
        raise HTTPException(502, str(e)) from None


@router.delete("/earthdata")
def admin_remove_login(request: Request):
    require_role(request)
    return earthdata.remove_login()


@router.post("/earthdata/check")
def admin_check_access(request: Request):
    require_role(request)
    return earthdata.start_access_check(connect)


@router.get("/catalog")
def admin_catalog():
    with connect() as conn:
        return overview.catalog_rows(conn)


@router.post("/catalog/refresh")
def admin_catalog_refresh(request: Request):
    require_role(request)
    nasa.refresh_catalog(connect)
    with connect() as conn:
        return overview.catalog_rows(conn)


@router.post("/imports")
def admin_import(body: ImportIn, request: Request):
    role = require_role(request)
    with connect() as conn:
        return jobs.enqueue(conn, body.products, role)


@router.get("/imports")
def admin_history(
    status: Literal["queued", "running", "done", "failed"] | None = None,
    variable: str | None = Query(default=None, max_length=60),
    page: int = Query(default=1, ge=1, le=1000),
):
    with connect() as conn:
        return overview.history(conn, status, variable, page)


@router.post("/imports/{job_id}/rerun")
def admin_rerun(job_id: int, request: Request):
    role = require_role(request)
    with connect() as conn:
        r = conn.execute("SELECT product, mode FROM import_job WHERE id = %s", (job_id,)).fetchone()
        if not r:
            raise HTTPException(404, "No such import.")
        return jobs.enqueue(conn, [r["product"]], role, r["mode"])


@router.post("/imports/rerun-product/{product}")
def admin_rerun_product(product: str, request: Request):
    """Run again an import that was done from the command line (no job row)."""
    role = require_role(request)
    with connect() as conn:
        return jobs.enqueue(conn, [product], role)


@router.delete("/imports/{job_id}")
def admin_delete_job(job_id: int, request: Request):
    require_role(request)
    with connect() as conn:
        try:
            jobs.delete_job(conn, job_id)
        except KeyError:
            raise HTTPException(404, "No such import.") from None
        except jobs.JobError as e:
            raise HTTPException(409, str(e)) from None
    return {"deleted": job_id}


@router.delete("/imports")
def admin_delete_finished(request: Request):
    require_role(request)
    with connect() as conn:
        return {"deleted": jobs.delete_finished(conn)}


@router.get("/imports/{job_id}/log")
def admin_job_log(job_id: int, request: Request):
    """The end of a job's log (people who may act only: it can show server paths)."""
    require_role(request)
    path = jobs.jobs_dir() / f"{job_id}.log"
    if not path.exists():
        raise HTTPException(404, "No log for this import.")
    text = path.read_text(errors="replace")
    lines = [ln for ln in text.splitlines() if not ln.startswith("PROGRESS ")]
    return {"lines": lines[-200:]}


@router.get("/database")
def admin_database():
    with connect() as conn:
        return overview.database_rows(conn)
