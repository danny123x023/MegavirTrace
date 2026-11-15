"""Import dashboard: who may act, the Earthdata login file, NASA comparison, the job queue."""

from __future__ import annotations

import os
import stat
import sys
import time

import numpy as np
import pytest
from starlette.requests import Request

from tests.conftest import ORIGIN

BLOCKED = [sys.executable, "-c", "import sys; print('real command blocked in tests'); sys.exit(3)"]


@pytest.fixture(autouse=True)
def no_real_commands(monkeypatch, tmp_path):
    """No test may start a real import, statistics run or NASA access check, or write job files to data/."""
    from megavir.imports import earthdata, jobs

    monkeypatch.setattr(jobs, "import_command", lambda *a: BLOCKED)
    monkeypatch.setattr(jobs, "precompute_command", lambda *a: BLOCKED)
    monkeypatch.setattr(earthdata, "access_check_command", lambda *a: BLOCKED)
    monkeypatch.setattr(jobs, "jobs_dir", lambda: tmp_path)
    from megavir.imports import admin

    monkeypatch.setattr(admin, "token_file", lambda: tmp_path / "admin_token")
    yield
    jobs.stop_worker(timeout=30)  # before the real commands come back
    assert not jobs.worker_alive()


# --------------------------------------------------------------------------------------
# Who may act
# --------------------------------------------------------------------------------------


def _request(host: str, headers: dict | None = None) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": raw, "client": (host, 1234)})


def test_role_this_computer_only_without_a_proxy(monkeypatch):
    from megavir.imports import admin

    monkeypatch.setattr(admin, "settings_trust_proxy", lambda: False)
    assert admin.request_role(_request("127.0.0.1")) == "local"  # e.g. curl on the server
    assert admin.request_role(_request("::1")) == "local"
    assert admin.request_role(_request("::ffff:127.0.0.1")) == "local"
    assert admin.request_role(_request("203.0.113.9")) is None
    # through the web app's proxy the visitor's address is unknown: never local, whatever is claimed
    assert admin.request_role(_request("127.0.0.1", {"X-Forwarded-Host": "localhost:3000"})) is None
    assert admin.request_role(_request("127.0.0.1", {"X-Forwarded-For": "127.0.0.1"})) is None
    assert admin.request_role(_request("127.0.0.1", {"Forwarded": "for=127.0.0.1"})) is None


def test_admin_token_is_created_once_owner_only(tmp_path, monkeypatch):
    from megavir.imports import admin

    path = tmp_path / "admin_token"
    monkeypatch.setattr(admin, "token_file", lambda: path)

    class S:
        admin_token = ""

    monkeypatch.setattr(admin, "settings", lambda: S())
    tok = admin.admin_token()
    assert len(tok) >= 30 and admin.admin_token() == tok
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert (
        admin.request_role(_request("127.0.0.1", {"X-Forwarded-Host": "x", "X-Admin-Token": tok})) == "admin"
    )
    assert (
        admin.request_role(_request("127.0.0.1", {"X-Forwarded-Host": "x", "X-Admin-Token": tok + "x"}))
        is None
    )


def test_role_behind_nginx_and_token(monkeypatch):
    from megavir.imports import admin

    monkeypatch.setattr(admin, "settings_trust_proxy", lambda: True)
    assert admin.request_role(_request("127.0.0.1", {"X-Real-IP": "203.0.113.9"})) is None
    assert admin.request_role(_request("127.0.0.1", {"X-Real-IP": "127.0.0.1"})) == "local"

    class S:
        admin_token = "a-long-random-token"

    monkeypatch.setattr(admin, "settings", lambda: S())
    assert (
        admin.request_role(
            _request("203.0.113.9", {"X-Admin-Token": "a-long-random-token", "X-Real-IP": "203.0.113.9"})
        )
        == "admin"
    )
    assert (
        admin.request_role(_request("203.0.113.9", {"X-Admin-Token": "wrong", "X-Real-IP": "203.0.113.9"}))
        is None
    )


# --------------------------------------------------------------------------------------
# The Earthdata login file
# --------------------------------------------------------------------------------------


@pytest.fixture
def netrc_file(tmp_path, monkeypatch):
    from megavir.imports import earthdata

    path = tmp_path / "netrc"
    monkeypatch.setattr(earthdata, "netrc_path", lambda: path)
    for k in ("EARTHDATA_TOKEN", "EARTHDATA_USERNAME", "EARTHDATA_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(earthdata, "verify_login", lambda u, p: None)
    return path


def test_save_and_remove_login_keeps_other_machines(netrc_file):
    from megavir.imports import earthdata

    netrc_file.write_text("machine example.org login someone password other-secret\n")
    assert earthdata.login_status(True)["configured"] is False
    st = earthdata.save_login("  explorer ", "s3cret-Pass")
    assert st == {**st, "configured": True, "method": "netrc", "username": "explorer"}
    assert stat.S_IMODE(os.stat(netrc_file).st_mode) == 0o600
    text = netrc_file.read_text()
    assert "machine urs.earthdata.nasa.gov login explorer password s3cret-Pass" in text
    assert "machine example.org login someone password other-secret" in text
    assert earthdata.login_status(False)["username"] is None  # viewers never see it
    earthdata.save_login("explorer2", "new-pass")  # replaces, does not duplicate
    assert netrc_file.read_text().count("urs.earthdata.nasa.gov") == 1
    st = earthdata.remove_login()
    assert st["configured"] is False
    assert "example.org" in netrc_file.read_text()
    netrc_file.write_text("machine urs.earthdata.nasa.gov login a password b\n")
    earthdata.remove_login()
    assert not netrc_file.exists()  # nothing left: no empty file


def test_login_that_netrc_cannot_hold_is_refused(netrc_file):
    from megavir.imports import earthdata

    for bad in ("has space", 'quo"te', "hash#tag", "back\\slash"):
        with pytest.raises(earthdata.LoginError):
            earthdata.save_login("explorer", bad)
    assert not netrc_file.exists()


def test_rejected_login_is_not_saved(netrc_file, monkeypatch):
    from megavir.imports import earthdata

    def reject(u, p):
        raise earthdata.LoginError("Earthdata Login rejected this username or password.")

    monkeypatch.setattr(earthdata, "verify_login", reject)
    with pytest.raises(earthdata.LoginError):
        earthdata.save_login("explorer", "wrong")
    assert not netrc_file.exists()


# --------------------------------------------------------------------------------------
# NASA side, results, checksums
# --------------------------------------------------------------------------------------


def test_last_complete_month_for_daily_and_weekly_files():
    from megavir.imports.nasa import last_complete_month

    assert last_complete_month("2026-11-12T23:59:59Z") == "2026-10"
    assert last_complete_month("2026-10-31T23:59:59Z") == "2026-10"
    assert last_complete_month("2026-01-05") == "2025-12"


def test_results_from_report_and_summary():
    from megavir.imports.jobs import results_from_report, summarise

    job = {"variables": ["a", "b", "c"]}
    rep = {
        "product": "p",
        "versions": {"a": {"version": 7, "months": 12}, "b": {"version": 3, "months": 12, "unchanged": True}},
        "no_data": ["c"],
    }
    res = results_from_report(job, rep, 0, [])
    assert [res[v]["action"] for v in "abc"] == ["imported", "unchanged", "failed"]
    assert summarise(res) == "1 imported · 1 unchanged · 1 failed"
    skipped = results_from_report(job, {"product": "p", "skipped": "no login"}, 0, [])
    assert summarise(skipped) == "3 skipped"
    crashed = results_from_report(job, None, 1, ["Traceback\n", "MemoryError\n"])
    assert crashed["a"] == {"action": "failed", "detail": "MemoryError"}


def test_cube_digest_sees_any_change():
    from megavir.ingest.pipeline import cube_digest

    a = np.arange(24, dtype=np.float32).reshape(2, 3, 4)
    a[0, 0, 0] = np.nan
    b = a.copy()
    assert cube_digest(a) == cube_digest(b)
    b[1, 2, 3] += 1e-3
    assert cube_digest(a) != cube_digest(b)


# --------------------------------------------------------------------------------------
# With the test database
# --------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def local_client(db):
    from fastapi.testclient import TestClient

    from megavir.api.main import app

    return TestClient(app, client=("127.0.0.1", 50000))


@pytest.fixture
def clean_jobs(db):
    from megavir.imports.state import ensure
    from megavir.store import direct_connect

    with direct_connect() as conn:
        ensure(conn)
        conn.execute("DELETE FROM import_job")
        conn.execute("DELETE FROM import_state")
        conn.commit()
    yield


FAKE_IMPORT = r"""
import json, sys
print('PROGRESS ' + json.dumps({"stage": "download", "done": 1, "total": 2}), flush=True)
print('downloading...', flush=True)
print('PROGRESS ' + json.dumps({"stage": "build", "variable": "rainfall", "index": 0, "total": 1}), flush=True)
print('PROGRESS ' + json.dumps({"stage": "stored", "variable": "rainfall", "action": "imported", "version": 42}), flush=True)
report = sys.argv[1]
json.dump([{"product": "imerg", "versions": {"rainfall": {"version": 42, "months": 333}}}], open(report, "w"))
"""


@pytest.mark.db
def test_import_job_runs_and_records_every_variable(clean_jobs, monkeypatch):
    from megavir.imports import jobs
    from megavir.store import direct_connect

    calls = []
    monkeypatch.setattr(jobs, "import_command", lambda job, rp: [sys.executable, "-c", FAKE_IMPORT, str(rp)])
    monkeypatch.setattr(
        jobs,
        "precompute_command",
        lambda vs: calls.append(vs) or [sys.executable, "-c", "print('precomputed')"],
    )
    monkeypatch.setattr(jobs, "ensure_worker", lambda: None)
    with direct_connect() as conn:
        out = jobs.enqueue(conn, ["imerg", "imerg", "nosuch"], "local")
        assert [q["product"] for q in out["queued"]] == ["imerg"]
        assert {s["product"] for s in out["skipped"]} == {"nosuch"}
        assert jobs.enqueue(conn, ["imerg"], "local")["skipped"][0]["reason"].startswith("already queued")
        job = conn.execute(
            "UPDATE import_job SET status = 'running', started_at = now() RETURNING *"
        ).fetchone()
        conn.commit()
        jobs.run_job(conn, job)
        conn.commit()
        row = conn.execute("SELECT * FROM import_job WHERE id = %s", (job["id"],)).fetchone()
    assert row["status"] == "done" and row["finished_at"] is not None
    assert row["results"] == {"rainfall": {"action": "imported", "version": 42, "months": 333}}
    assert row["summary"] == "1 imported"
    assert row["progress"]["stage"] == "finished" and row["progress"]["stored"] == {"rainfall": "imported"}
    assert calls == [["rainfall"]]  # statistics precomputed for the new version
    assert "downloading..." in row["log_tail"]


@pytest.mark.db
def test_crashed_import_is_failed_with_its_last_line(clean_jobs, monkeypatch):
    from megavir.imports import jobs
    from megavir.store import direct_connect

    monkeypatch.setattr(
        jobs,
        "import_command",
        lambda job, rp: [sys.executable, "-c", "import sys; print('boom: disk full'); sys.exit(1)"],
    )
    monkeypatch.setattr(jobs, "ensure_worker", lambda: None)
    with direct_connect() as conn:
        jobs.enqueue(conn, ["gldas"], "local")
        job = conn.execute(
            "UPDATE import_job SET status = 'running', started_at = now() RETURNING *"
        ).fetchone()
        conn.commit()
        jobs.run_job(conn, job)
        conn.commit()
        row = conn.execute("SELECT * FROM import_job WHERE id = %s", (job["id"],)).fetchone()
        assert row["status"] == "failed"
        assert row["summary"] == "3 failed"
        assert row["results"]["soil_moisture"]["detail"] == "boom: disk full"
        with pytest.raises(jobs.JobError):
            conn.execute("UPDATE import_job SET status = 'running' WHERE id = %s", (job["id"],))
            conn.commit()
            jobs.delete_job(conn, job["id"])
        conn.execute("UPDATE import_job SET status = 'failed' WHERE id = %s", (job["id"],))
        conn.commit()
        assert jobs.delete_finished(conn) == 1


@pytest.mark.db
def test_worker_picks_up_queued_jobs(clean_jobs, monkeypatch):
    from megavir.imports import jobs
    from megavir.store import direct_connect

    monkeypatch.setattr(jobs, "import_command", lambda job, rp: [sys.executable, "-c", FAKE_IMPORT, str(rp)])
    monkeypatch.setattr(jobs, "precompute_command", lambda vs: [sys.executable, "-c", "pass"])
    monkeypatch.setattr(jobs, "IDLE_POLLS", 1)
    with direct_connect() as conn:
        out = jobs.enqueue(conn, ["imerg"], "local")  # starts the worker thread
        job_id = out["queued"][0]["job"]
        for _ in range(100):
            st = conn.execute("SELECT status FROM import_job WHERE id = %s", (job_id,)).fetchone()["status"]
            conn.commit()
            if st in ("done", "failed"):
                break
            time.sleep(0.2)
    assert st == "done"


@pytest.mark.db
def test_dashboard_api_reading_is_open_acting_is_local(
    client, local_client, clean_jobs, netrc_file, monkeypatch
):
    from megavir.imports import jobs, nasa

    monkeypatch.setattr(jobs, "ensure_worker", lambda: None)
    ov = client.get("/admin/overview").json()
    assert ov["can_act"] is False and ov["worker"]["state"] == "idle"
    assert local_client.get("/admin/overview").json()["role"] == "local"
    # the same computer, but through the web app's proxy: viewing only
    assert (
        local_client.get("/admin/overview", headers={"X-Forwarded-Host": "localhost:3000"}).json()["role"]
        is None
    )
    proxied = {**ORIGIN, "X-Forwarded-Host": "localhost:3000"}
    assert (
        local_client.post("/admin/imports", json={"products": ["imerg"]}, headers=proxied).status_code == 403
    )
    # acting from elsewhere is refused, even with the right Origin
    assert (
        client.put("/admin/earthdata", json={"username": "u", "password": "p"}, headers=ORIGIN).status_code
        == 403
    )
    assert client.post("/admin/imports", json={"products": ["imerg"]}, headers=ORIGIN).status_code == 403
    # from this computer it works, and the Origin check still applies
    assert local_client.put("/admin/earthdata", json={"username": "u", "password": "p"}).status_code == 403
    r = local_client.put(
        "/admin/earthdata", json={"username": "explorer", "password": "pw-1"}, headers=ORIGIN
    )
    assert r.status_code == 200 and r.json()["username"] == "explorer"
    assert client.get("/admin/overview").json()["login"] == {
        **client.get("/admin/overview").json()["login"],
        "configured": True,
        "username": None,
    }
    bad = local_client.put(
        "/admin/earthdata", json={"username": "explorer", "password": "has space"}, headers=ORIGIN
    )
    assert bad.status_code == 422

    def fake(pid):
        return {
            "first_month": "2000-01",
            "last_month": "2030-12",
            "files": 10,
            "bytes": 1000,
            "approx_size": True,
        }

    monkeypatch.setattr(nasa, "check_product", fake)
    cat = local_client.post("/admin/catalog/refresh", headers=ORIGIN).json()
    assert cat["checked_at"] and cat["counts"]["all"] == 17
    assert {r["status"] for r in cat["rows"]} <= {"stand_in", "not_imported"}  # the test store is synthetic
    q = local_client.post("/admin/imports", json={"products": ["imerg"]}, headers=ORIGIN).json()
    assert q["queued"][0]["product"] == "imerg"
    hist = client.get("/admin/imports").json()
    assert hist["total"] >= 1 and hist["items"][0]["status"] == "queued"
    assert client.get("/admin/imports", params={"status": "failed"}).json()["total"] == 0
    dbrows = client.get("/admin/database").json()
    assert dbrows["counts"]["all"] == len(dbrows["rows"]) and dbrows["counts"]["stand_in"] >= 1
    jid = q["queued"][0]["job"]
    assert local_client.delete(f"/admin/imports/{jid}", headers=ORIGIN).json() == {"deleted": jid}


@pytest.mark.db
def test_identical_import_keeps_the_stored_version(db):
    from megavir.ingest.pipeline import cube_digest, unchanged_version
    from megavir.store import GridSpec, direct_connect, write_version

    spec = GridSpec(2.0, -89.0, -179.0, 3, 4)
    cube = np.random.default_rng(1).normal(size=(5, 3, 4)).astype(np.float32)
    d = cube_digest(cube)
    with direct_connect() as conn:
        vid = write_version(conn, "zz_test_var", "test", spec, 24000, cube, "1", {"checksum": d}, {}, True)
        conn.commit()
        assert unchanged_version(conn, "zz_test_var", "test", spec, 24000, 5, d) == vid
        assert unchanged_version(conn, "zz_test_var", "test", spec, 24001, 5, d) is None
        assert unchanged_version(conn, "zz_test_var", "test", spec, 24000, 5, "0" * 32) is None
        conn.execute("DELETE FROM grid_version WHERE variable = 'zz_test_var'")
        conn.commit()
