"""
Filesystem-backed job store + in-process analysis worker.

Layout:
    data/jobs/<job_id>/
        upload.<ext>
        job.json        {id, status, progress, error, meta, created_at}
        report.json
        annotated.mp4

Statuses: queued -> running -> done | error.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

BASE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "jobs")
)
_executor = ThreadPoolExecutor(max_workers=2)
_lock = threading.Lock()


def _job_dir(job_id: str) -> str:
    return os.path.join(BASE_DIR, job_id)


def _meta_path(job_id: str) -> str:
    return os.path.join(_job_dir(job_id), "job.json")


def create_job(meta: dict) -> str:
    job_id = uuid.uuid4().hex[:12]
    d = _job_dir(job_id)
    os.makedirs(d, exist_ok=True)
    state = {
        "id": job_id, "status": "queued", "progress": 0.0,
        "error": None, "meta": meta, "created_at": time.time(),
    }
    _write_state(job_id, state)
    return job_id


def _write_state(job_id: str, state: dict) -> None:
    with _lock:
        with open(_meta_path(job_id), "w") as f:
            json.dump(state, f, indent=2)


def update_job(job_id: str, **kw) -> None:
    state = get_job(job_id)
    if state is None:
        return
    state.update(kw)
    _write_state(job_id, state)


def get_job(job_id: str) -> dict | None:
    p = _meta_path(job_id)
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


def job_file(job_id: str, name: str) -> str | None:
    p = os.path.join(_job_dir(job_id), name)
    return p if os.path.exists(p) else None


def save_upload(job_id: str, filename: str, data: bytes) -> str:
    ext = os.path.splitext(filename)[1] or ".mp4"
    path = os.path.join(_job_dir(job_id), f"upload{ext}")
    with open(path, "wb") as f:
        f.write(data)
    return path


def sweep_stale_jobs() -> int:
    """Mark jobs left in queued/running as errored.

    Workers are in-process, so on a fresh boot nothing is actually running —
    a non-terminal job state means the server restarted mid-analysis and the
    frontend would otherwise poll forever.
    """
    import glob

    n = 0
    for p in glob.glob(os.path.join(BASE_DIR, "*", "job.json")):
        try:
            with open(p) as f:
                state = json.load(f)
            if state.get("status") in ("queued", "running"):
                state["status"] = "error"
                state["error"] = "server restarted during analysis — resubmit"
                _write_state(state["id"], state)
                n += 1
        except Exception:
            continue
    return n


def start_analysis(job_id: str, video_path: str) -> None:
    from .pipeline.run import run_analysis  # deferred: heavy imports

    def work():
        update_job(job_id, status="running")
        try:
            run_analysis(
                video_path,
                _job_dir(job_id),
                meta=(get_job(job_id) or {}).get("meta", {}),
                progress_cb=lambda p: update_job(job_id, progress=round(p, 3)),
            )
            update_job(job_id, status="done", progress=1.0)
        except Exception as exc:  # noqa: BLE001 - surface to client
            update_job(job_id, status="error", error=str(exc))

    _executor.submit(work)
