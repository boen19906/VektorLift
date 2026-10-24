"""
Annotated-video renderer.

Draws the tracked skeleton, joint-angle readouts, bar path trace, rep/phase
banner, live warnings, and torque numbers over the original frames, then
encodes H.264 via imageio-ffmpeg (no system ffmpeg required).
"""
from __future__ import annotations

import os

import cv2
import imageio_ffmpeg
import numpy as np

from .pose import SKELETON_EDGES

COLOR_BONE = (80, 220, 100)
COLOR_JOINT = (60, 160, 255)
COLOR_BAR = (255, 190, 60)
COLOR_WARN = (60, 60, 240)
COLOR_TEXT = (235, 235, 235)
COLOR_REF = (120, 120, 120)


def _to_img(pre, analysis_px):
    """positions_px-space point -> raw image pixel coords."""
    img = analysis_px + pre.analysis_px_offset
    return np.array([pre.facing * img[0], -img[1]])


def _phase_label(kin, frame_i):
    for rep in kin.reps:
        if rep.start <= frame_i <= rep.end:
            if kin.lift_type == "squat":
                if frame_i < rep.bottom:
                    return rep.index, "descent"
                if frame_i < rep.lockout:
                    return rep.index, "ascent"
                return rep.index, "lockout"
            if frame_i < rep.pull_start:
                return rep.index, "setup"
            if frame_i < rep.lockout:
                return rep.index, "pull"
            return rep.index, "return"
    return None, "between reps"


def render_annotated(
    video_path: str,
    out_path: str,
    pre,
    kin,
    dyn,
    fat,
    findings,
    bar_pos_px: np.ndarray,
    progress_cb=None,
) -> str:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"cannot re-open {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or pre.fps
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or pre.n_frames

    writer = imageio_ffmpeg.write_frames(
        out_path, (w, h), fps=min(fps, 30.0), codec="libx264",
        output_params=["-pix_fmt", "yuv420p", "-crf", "23"],
        macro_block_size=16,
    )
    writer.send(None)

    # map finding -> set of frames to warn on (+-0.6 s around evidence time)
    warn_windows = []
    for f_ in findings:
        if f_.timestamp:
            warn_windows.append((f_.timestamp, f_.title))

    # ground line in image space
    gy = int(-(0 + pre.analysis_px_offset[1]))

    step = max(1, int(round(fps / 30.0)))
    frame_i = 0
    written = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame_i >= pre.n_frames:
                break
            if frame_i % step == 0:
                overlay = frame.copy()
                # skeleton
                for a, b in SKELETON_EDGES:
                    pa = _to_img(pre, pre.positions_px[a][frame_i])
                    pb = _to_img(pre, pre.positions_px[b][frame_i])
                    cv2.line(overlay, tuple(pa.astype(int)),
                             tuple(pb.astype(int)), COLOR_BONE, 2)
                for name in ("shoulder", "hip", "knee", "ankle", "wrist",
                             "heel", "foot_index"):
                    p = _to_img(pre, pre.positions_px[name][frame_i])
                    cv2.circle(overlay, tuple(p.astype(int)), 4,
                               COLOR_JOINT, -1)
                # bar trace (last ~1.5 s)
                tail = max(0, frame_i - int(1.5 * pre.fps))
                pts = np.array(
                    [_to_img(pre, bar_pos_px[j])
                     for j in range(tail, frame_i + 1)]
                ).astype(int)
                for j in range(1, len(pts)):
                    cv2.line(overlay, tuple(pts[j - 1]), tuple(pts[j]),
                             COLOR_BAR, 2)
                bp = _to_img(pre, bar_pos_px[frame_i])
                cv2.circle(overlay, tuple(bp.astype(int)), 5, COLOR_BAR, -1)

                # midfoot + ground reference
                mf = _to_img(pre, np.array([pre.midfoot_x[frame_i], 0.0]))
                cv2.line(overlay, (int(mf[0]), int(gy)),
                         (int(mf[0]), 0), COLOR_REF, 1)
                cv2.line(overlay, (0, int(gy)), (w, int(gy)), COLOR_REF, 1)

                alpha = 0.65
                frame = cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0)

                # joint angle readouts
                kn = _to_img(pre, pre.positions_px["knee"][frame_i])
                hp = _to_img(pre, pre.positions_px["hip"][frame_i])
                cv2.putText(
                    frame, f"knee {kin.angles['knee_flexion'][frame_i]:.0f}deg",
                    (int(kn[0]) + 8, int(kn[1])),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, COLOR_TEXT, 1)
                cv2.putText(
                    frame, f"hip {kin.angles['hip_flexion'][frame_i]:.0f}deg",
                    (int(hp[0]) + 8, int(hp[1]) - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, COLOR_TEXT, 1)

                # banner: rep, phase, bar velocity, torques
                rep_i, phase = _phase_label(kin, frame_i)
                t_s = frame_i / pre.fps
                vel = fat.bar_velocity[frame_i] if fat is not None else 0.0
                header = f"{kin.lift_type.upper()}"
                if rep_i:
                    header += f"  rep {rep_i}  |  {phase}"
                cv2.putText(frame, header, (16, 28),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, COLOR_TEXT, 2)
                cv2.putText(
                    frame, f"bar v {vel:+.2f} {fat.units if fat else ''}",
                    (16, 54), cv2.FONT_HERSHEY_SIMPLEX, 0.55, COLOR_TEXT, 1)
                if dyn is not None:
                    cv2.putText(
                        frame,
                        f"knee M {dyn.moments_norm['knee'][frame_i]:+.2f}  "
                        f"hip M {dyn.moments_norm['hip'][frame_i]:+.2f} Nm/kg",
                        (16, 78), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                        COLOR_TEXT, 1)

                # warnings
                active = [t for ts, t in warn_windows
                          if abs(ts - t_s) < 0.6]
                for k, txt in enumerate(active[:3]):
                    cv2.putText(frame, f"! {txt}", (16, h - 20 - 26 * k),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, COLOR_WARN, 2)

                writer.send(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                written += 1
                if progress_cb:
                    progress_cb(0.6 + 0.35 * frame_i / max(total, 1))
            frame_i += 1
    finally:
        cap.release()
        writer.close()
    if written == 0:
        raise RuntimeError("no frames written to annotated video")
    return out_path
