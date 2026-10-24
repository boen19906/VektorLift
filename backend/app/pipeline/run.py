"""
End-to-end analysis orchestration.
"""
from __future__ import annotations

import json
import os
import time

from . import (
    extract_landmarks, Preprocessor, BarbellTracker, build_anthropometry,
    compute_kinematics, compute_dynamics, compute_fatigue, evaluate_rules,
    build_report,
)
from .annotate import render_annotated


class AnalysisError(Exception):
    pass


def run_analysis(
    video_path: str,
    job_dir: str,
    meta: dict,
    progress_cb=None,
) -> dict:
    """Run the whole pipeline. Writes report.json + annotated.mp4 into job_dir
    and returns the report dict."""
    cb = progress_cb or (lambda p: None)
    t0 = time.time()

    lift_type = meta.get("lift_type", "squat")

    raw = extract_landmarks(video_path, progress_cb=lambda p: cb(0.05 + 0.5 * p))
    pre = Preprocessor(height_m=meta.get("height_m")).run(raw)

    bar = BarbellTracker(lift_type).track(
        pre, video_path=video_path,
        allow_plate=meta.get("load_kg", 0.0) > 0,
    )
    # detected plate scale wins over height-based scale, but only when it
    # roughly agrees — a Hough "plate" can be any round object in frame
    if bar.method == "plate" and bar.px_per_m_plate and pre.px_per_m:
        agree = pre.px_per_m / bar.px_per_m_plate
        if 0.6 < agree < 1.7:
            ratio = agree
            for name in pre.positions:
                pre.positions[name] = pre.positions[name] * ratio
                pre.velocities[name] = pre.velocities[name] * ratio
            pre.midfoot_x = pre.midfoot_x * ratio
            pre.px_per_m = bar.px_per_m_plate

    anthro = build_anthropometry(
        pre,
        bodyweight_kg=meta.get("bodyweight_kg", 80.0),
        height_m=meta.get("height_m"),
        sex=meta.get("sex", "male"),
    )
    kin = compute_kinematics(pre, bar.pos, lift_type)
    if not kin.reps:
        raise AnalysisError(
            f"No {lift_type} reps detected. Check that the clip shows a full "
            "rep cycle from the side."
        )

    dyn = compute_dynamics(
        pre, anthro, kin, kin.bar_pos, bar_kg=meta.get("load_kg", 0.0)
    )
    fat = compute_fatigue(pre, kin, metric_scale=bool(pre.px_per_m))
    findings = evaluate_rules(kin, dyn, fat, anthro, pre)
    cb(0.62)

    bar_px = bar.pos_px if bar.pos_px is not None else (
        kin.bar_pos * (pre.px_per_m or pre.stature_px)
    )
    render_annotated(
        video_path,
        os.path.join(job_dir, "annotated.mp4"),
        pre, kin, dyn, fat, findings, bar_px,
        progress_cb=lambda p: cb(p),
    )
    cb(0.97)

    report = build_report(
        meta={**meta, "analysis_seconds": round(time.time() - t0, 1)},
        pre=pre, anthro=anthro, kin=kin, dyn=dyn, fat=fat,
        findings=findings, bar_method=bar.method,
    )
    with open(os.path.join(job_dir, "report.json"), "w") as f:
        json.dump(report, f, indent=2)
    cb(1.0)
    return report
