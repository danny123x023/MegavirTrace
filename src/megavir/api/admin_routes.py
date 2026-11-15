"""Import dashboard API (web page "Data import").

Reading is open; acting (imports, deletions, Earthdata account, checks) needs this computer or
the administrator token, see ``megavir.imports.admin``.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from megavir.imports import earthdata, jobs, nasa, overview
from megavir.imports.admin import request_role, require_role, token_source
from megavir.imports.state import get_state
from megavir.store import connect

router = APIRouter(prefix="/admin", tags=["import dashboard"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class ImportIn(BaseModel):
    products: list[str] = Field(min_length=1, max_length=40)


@router.get("/overview")
def admin_overview(request: Request):
    role = request_role(request)
    with connect() as conn:
        check = get_state(conn, "earthdata_check")
        worker = jobs.worker_status(conn)
    return {
        "role": role,
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
