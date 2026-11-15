"""Import queue: one job per product, run one at a time by a single worker.

A job runs ``megavir-ingest full <product>`` as a child process (the same command as on the
command line), reads its PROGRESS lines for the live view, and afterwards records, from the run's
report, what happened to every variable: imported (new version swapped in), unchanged (identical
to what was stored, so the stored version stays), skipped (no login, or the product was busy) or
failed.  Newly imported variables then get their preset statistics precomputed.

Only one worker runs per database: it holds a PostgreSQL advisory lock while it works, so
several API processes never import at the same time, and a crashed worker releases the lock.
"""

from __future__ import annotations

import collections
import json
import logging
import subprocess
import sys
import threading
import time
from pathlib import Path

from megavir.config import ROOT, settings
from megavir.ingest.products import PRODUCTS
from megavir.store import direct_connect

from .earthdata import child_env
from .state import ensure

log = logging.getLogger("megavir.imports")
LOCK_KEY = 72026111  # advisory lock id of the import worker
IDLE_POLLS = 15  # the worker stops after this many empty polls (2 s apart)


class JobError(RuntimeError):
    pass


# --------------------------------------------------------------------------------------
# Commands (module functions so tests can replace them)
# --------------------------------------------------------------------------------------


def import_command(job: dict, report_path: Path) -> list[str]:
    return [
        sys.executable,
        "-I",
        "-m",
        "megavir.ingest.cli",
        job["mode"],
        job["product"],
        "--report-json",
        str(report_path),
    ]


def precompute_command(variables: list[str]) -> list[str]:
    return [sys.executable, "-I", "-m", "megavir.ingest.cli", "precompute", *variables]


def jobs_dir() -> Path:
    d = settings().data_dir / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


# --------------------------------------------------------------------------------------
# Queue
# --------------------------------------------------------------------------------------


def enqueue(conn, products: list[str], role: str, mode: str = "full") -> dict:
    ensure(conn)
    queued, skipped = [], []
    for pid in dict.fromkeys(products):
        if pid not in PRODUCTS:
            skipped.append({"product": pid, "reason": "unknown source"})
            continue
        busy = conn.execute(
            "SELECT id FROM import_job WHERE product = %s AND status IN ('queued', 'running')", (pid,)
        ).fetchone()
        if busy:
            skipped.append({"product": pid, "reason": f"already queued or running (job {busy['id']})"})
            continue
        r = conn.execute(
            """INSERT INTO import_job (product, variables, mode, status, requested_by)
               VALUES (%s, %s, %s, 'queued', %s) RETURNING id""",
            (pid, list(PRODUCTS[pid].outputs), mode, role),
        ).fetchone()
        queued.append({"product": pid, "job": r["id"]})
    conn.commit()
    if queued:
        ensure_worker()
    return {"queued": queued, "skipped": skipped}


def delete_job(conn, job_id: int) -> None:
    ensure(conn)
    r = conn.execute("SELECT status FROM import_job WHERE id = %s", (job_id,)).fetchone()
    if not r:
        raise KeyError(job_id)
    if r["status"] == "running":
        raise JobError("This import is running; it can be deleted when it has finished.")
    conn.execute("DELETE FROM import_job WHERE id = %s", (job_id,))
    conn.commit()
    for suffix in (".log", ".json"):
        (jobs_dir() / f"{job_id}{suffix}").unlink(missing_ok=True)


def delete_finished(conn) -> int:
    ensure(conn)
    ids = [
        r["id"]
        for r in conn.execute(
            "DELETE FROM import_job WHERE status IN ('done', 'failed') RETURNING id"
        ).fetchall()
    ]
    conn.commit()
    for i in ids:
        for suffix in (".log", ".json"):
            (jobs_dir() / f"{i}{suffix}").unlink(missing_ok=True)
    return len(ids)


def worker_status(conn) -> dict:
    ensure(conn)
    running = conn.execute(
        "SELECT id, product, variables, started_at, progress FROM import_job WHERE status = 'running' ORDER BY id LIMIT 1"
    ).fetchone()
    queued_products = [
        r["product"]
        for r in conn.execute("SELECT product FROM import_job WHERE status = 'queued' ORDER BY id").fetchall()
    ]
    queued = len(queued_products)
    if queued and not running and not worker_alive():
        ensure_worker()  # e.g. after a server restart
    state = "running" if running else ("starting" if queued else "idle")
    job = None
    if running:
        job = {k: running[k] for k in ("id", "product", "variables", "progress")}
        job["started_at"] = running["started_at"].isoformat() if running["started_at"] else None
    return {"state": state, "queued": queued, "queued_products": queued_products, "job": job}


# --------------------------------------------------------------------------------------
# Worker
# --------------------------------------------------------------------------------------

_thread: threading.Thread | None = None
_thread_lock = threading.Lock()
_stop = threading.Event()


def worker_alive() -> bool:
    return bool(_thread and _thread.is_alive())


def ensure_worker() -> None:
    global _thread
    with _thread_lock:
        if worker_alive():
            return
        _stop.clear()
        _thread = threading.Thread(target=_worker, name="megavir-import-worker", daemon=True)
        _thread.start()


def stop_worker(timeout: float = 30.0) -> None:
    """Ask the worker to stop after the current job (if any) and wait for it."""
    _stop.set()
    t = _thread
    if t and t.is_alive():
        t.join(timeout)


def _queued(conn) -> bool:
    return bool(conn.execute("SELECT 1 FROM import_job WHERE status = 'queued' LIMIT 1").fetchone())


def _worker() -> None:
    conn = direct_connect()
    conn.autocommit = True
    try:
        ensure(conn)
        while not conn.execute("SELECT pg_try_advisory_lock(%s) AS ok", (LOCK_KEY,)).fetchone()["ok"]:
            if not _queued(conn) or _stop.is_set():  # another process's worker is busy and nothing waits
                return
            time.sleep(5)
        # holding the lock: a job still marked running was cut off (the server stopped)
        conn.execute(
            """UPDATE import_job SET status = 'failed', finished_at = now(),
               summary = 'interrupted: the server stopped during the import' WHERE status = 'running'"""
        )
        idle = 0
        while idle < IDLE_POLLS and not _stop.is_set():
            job = conn.execute(
                """UPDATE import_job SET status = 'running', started_at = now(), progress = '{"stage": "starting"}'
                   WHERE id = (SELECT id FROM import_job WHERE status = 'queued' ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED)
                   RETURNING *"""
            ).fetchone()
            if not job:
                idle += 1
                time.sleep(2)
                continue
            idle = 0
            try:
                run_job(conn, job)
            except Exception as e:  # noqa: BLE001 - the worker keeps going
                log.exception("import job %s failed", job["id"])
                conn.execute(
                    "UPDATE import_job SET status = 'failed', finished_at = now(), summary = %s WHERE id = %s",
                    (f"failed: {e}"[:300], job["id"]),
                )
    finally:
        try:
            conn.execute("SELECT pg_advisory_unlock_all()")
        finally:
            conn.close()


def _set(conn, job_id: int, **fields) -> None:
    cols = ", ".join(f"{k} = %({k})s" + ("::jsonb" if k in ("progress", "results") else "") for k in fields)
    vals = {k: json.dumps(v) if k in ("progress", "results") else v for k, v in fields.items()}
    conn.execute(f"UPDATE import_job SET {cols} WHERE id = %(id)s", {**vals, "id": job_id})


def _stream(
    conn, job_id: int, cmd: list[str], log_path: Path, progress: dict, tail: collections.deque
) -> tuple[int, list[str]]:
    """Run a child process, keep its output in the job log (and ``tail``) and its progress in the job row."""
    env = child_env()
    env["MEGAVIR_PROGRESS"] = "1"
    last_write = 0.0
    with open(log_path, "a") as logf:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            cwd=ROOT,
            start_new_session=True,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            logf.write(line)
            if line.startswith("PROGRESS "):
                try:
                    p = json.loads(line[9:])
                except json.JSONDecodeError:
                    continue
                stage_changed = p.get("stage") != progress.get("stage")
                if p.get("stage") == "stored":
                    progress.setdefault("stored", {})[p["variable"]] = p.get("action")
                else:
                    progress.update(p)
                now = time.monotonic()
                if stage_changed or now - last_write > 1.0:
                    _set(conn, job_id, progress=progress, log_tail="".join(tail)[-4000:])
                    last_write = now
            else:
                tail.append(line)
        rc = proc.wait()
    _set(conn, job_id, progress=progress, log_tail="".join(tail)[-4000:])
    return rc, list(tail)


def results_from_report(job: dict, report: dict | None, rc: int, tail: list[str]) -> dict:
    """What happened to each of the job's variables."""
    out = {}
    last_line = next((ln.strip() for ln in reversed(tail) if ln.strip()), "")
    for v in job["variables"]:
        if report is None:
            detail = last_line[:300] or f"the import stopped (exit code {rc}) without a report"
            out[v] = {"action": "failed", "detail": detail}
        elif "skipped" in report:
            out[v] = {"action": "skipped", "detail": report["skipped"]}
        elif "error" in report:
            out[v] = {"action": "failed", "detail": report["error"]}
        elif v in report.get("versions", {}):
            info = report["versions"][v]
            out[v] = {
                "action": "unchanged" if info.get("unchanged") else "imported",
                "version": info["version"],
                "months": info["months"],
            }
        elif v in report.get("no_data", []):
            out[v] = {"action": "failed", "detail": "no valid month in the downloaded files"}
        else:
            out[v] = {"action": "failed", "detail": "the import did not produce this variable"}
    return out


def summarise(results: dict) -> str:
    order = ["imported", "unchanged", "skipped", "failed"]
    counts = collections.Counter(r["action"] for r in results.values())
    return " · ".join(f"{counts[a]} {a}" for a in order if counts[a]) or "nothing to do"


def run_job(conn, job: dict) -> None:
    job_id = job["id"]
    folder = jobs_dir()
    report_path, log_path = folder / f"{job_id}.json", folder / f"{job_id}.log"
    report_path.unlink(missing_ok=True)
    progress: dict = {"stage": "starting"}
    tail: collections.deque[str] = collections.deque(maxlen=40)  # shared by both steps
    rc, lines = _stream(conn, job_id, import_command(job, report_path), log_path, progress, tail)
    reports = json.loads(report_path.read_text()) if report_path.exists() else []
    report = next((r for r in reports if r.get("product") == job["product"]), None)
    results = results_from_report(job, report, rc, lines)
    imported = [v for v, r in results.items() if r["action"] == "imported"]
    note = ""
    if imported:
        progress.update({"stage": "precompute", "variables": imported})
        _set(conn, job_id, progress=progress, results=results)
        rc2, _ = _stream(conn, job_id, precompute_command(imported), log_path, progress, tail)
        if rc2 != 0:
            note = " · statistics not precomputed (they are computed on first use)"
    failed = any(r["action"] == "failed" for r in results.values())
    progress["stage"] = "finished"
    _set(
        conn,
        job_id,
        status="failed" if failed else "done",
        progress=progress,
        results=results,
        summary=summarise(results) + note,
    )
    conn.execute("UPDATE import_job SET finished_at = now() WHERE id = %s", (job_id,))
