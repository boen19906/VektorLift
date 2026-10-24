"""
VektorLift API.

    POST /api/analyze            multipart upload -> {job_id}
    GET  /api/jobs/{id}          job status/progress
    GET  /api/jobs/{id}/result   report.json
    GET  /api/jobs/{id}/video    annotated mp4
    GET  /api/health
"""
from __future__ import annotations

import os

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from . import jobs

app = FastAPI(title="VektorLift", version="0.1.0")


@app.on_event("startup")
def _startup():
    jobs.sweep_stale_jobs()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_UPLOAD_MB = 500


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/analyze")
async def analyze(
    file: UploadFile = File(...),
    lift_type: str = Form("squat"),
    load_kg: float = Form(0.0),
    bodyweight_kg: float = Form(80.0),
    height_m: float = Form(1.75),
    sex: str = Form("male"),
):
    if lift_type not in ("squat", "deadlift"):
        raise HTTPException(400, "lift_type must be 'squat' or 'deadlift'")
    if sex not in ("male", "female"):
        raise HTTPException(400, "sex must be 'male' or 'female'")

    data = await file.read()
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"file too large (>{MAX_UPLOAD_MB} MB)")
    if len(data) < 10_000:
        raise HTTPException(400, "file looks empty — upload a video")

    meta = {
        "lift_type": lift_type,
        "load_kg": float(load_kg),
        "bodyweight_kg": float(bodyweight_kg),
        "height_m": float(height_m),
        "sex": sex,
        "filename": file.filename,
    }
    job_id = jobs.create_job(meta)
    video_path = jobs.save_upload(job_id, file.filename or "upload.mp4", data)
    jobs.start_analysis(job_id, video_path)
    return {"job_id": job_id}


@app.get("/api/jobs")
def jobs_list():
    return jobs.list_jobs()


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    state = jobs.get_job(job_id)
    if state is None:
        raise HTTPException(404, "job not found")
    return {
        "id": state["id"], "status": state["status"],
        "progress": state["progress"], "error": state.get("error"),
        "meta": state["meta"],
    }


@app.get("/api/jobs/{job_id}/result")
def job_result(job_id: str):
    p = jobs.job_file(job_id, "report.json")
    if p is None:
        state = jobs.get_job(job_id)
        if state is None:
            raise HTTPException(404, "job not found")
        raise HTTPException(409, f"result not ready (status={state['status']})")
    # read into memory and return plain JSON — a streamed FileResponse can
    # stall behind the vite dev proxy and hang the frontend's poll loop.
    # Older reports may contain Infinity/NaN (invalid JSON for browsers);
    # scrub non-finite floats to null.
    import json
    import math

    def scrub(v):
        if isinstance(v, float) and not math.isfinite(v):
            return None
        if isinstance(v, dict):
            return {k: scrub(x) for k, x in v.items()}
        if isinstance(v, list):
            return [scrub(x) for x in v]
        return v

    with open(p) as f:
        return JSONResponse(scrub(json.load(f)))


@app.get("/api/jobs/{job_id}/video")
def job_video(job_id: str):
    p = jobs.job_file(job_id, "annotated.mp4")
    if p is None:
        raise HTTPException(404, "annotated video not found")
    return FileResponse(p, media_type="video/mp4")
