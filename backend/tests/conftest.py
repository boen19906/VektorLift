import numpy as np
import pytest

from app.pipeline.pose import RawPoseSeries, LANDMARK_INDEX

FPS = 30.0
W, H = 1280, 720
PPM = 380.0          # px per meter
X0, Y0 = 640.0, 690.0  # img px of (x=0, y=0) ground origin


def _img(pt):
    """analysis (x fwd m, y up m) -> (x_norm, y_norm) image coords."""
    return ((X0 + pt[0] * PPM) / W, (Y0 - pt[1] * PPM) / H)


def _skeleton_frame(hip, knee, shoulder, ankle=(0.0, 0.07)):
    """Return dict landmark-name -> (x,y) meters for one frame."""
    heel = (ankle[0] - 0.06, 0.01)
    toe = (ankle[0] + 0.14, 0.01)
    elbow = (shoulder[0] + 0.04, shoulder[1] - 0.24)
    wrist = (elbow[0] + 0.02, elbow[1] - 0.24)
    eye = (shoulder[0] + 0.07, shoulder[1] + 0.20)
    nose = (eye[0] + 0.06, eye[1] - 0.02)
    ear = (shoulder[0] + 0.03, shoulder[1] + 0.20)
    return {
        "ankle": ankle, "heel": heel, "foot_index": toe,
        "knee": knee, "hip": hip, "shoulder": shoulder,
        "elbow": elbow, "wrist": wrist, "eye": eye, "ear": ear,
        "nose": nose,
    }


def squat_frame(u, depth=0.55, speed_mult=1.0):
    """u in [0,1] through a single squat rep (0=stand, .5=bottom)."""
    s = np.sin(np.pi * u)  # 0 -> 1 -> 0
    hip = (-0.10 * s, 0.95 - depth * s)
    knee = (0.02 + 0.26 * s, 0.50 - 0.04 * s)
    shoulder = (-0.02 + 0.22 * s, 1.45 - 0.40 * s)
    return _skeleton_frame(hip, knee, shoulder)


def deadlift_frame(u, bar_h0=0.16):
    """u in [0,1] through a deadlift pull (0=floor, .5=lockout, 1=floor)."""
    s = np.sin(np.pi * u)
    lift = np.clip(np.sin(np.pi * np.clip(u, 0, 0.65) / 0.65), 0, 1)
    hip = (-0.12 + 0.12 * lift, 0.72 + 0.23 * lift)
    knee = (0.10 - 0.08 * lift, 0.42 + 0.08 * lift)
    shoulder = (0.22 - 0.24 * lift, 1.12 + 0.33 * lift)
    fr = _skeleton_frame(hip, knee, shoulder)
    # arms straight down to the bar; bar = wrist
    wrist = (shoulder[0] + 0.06, bar_h0 + 0.60 * lift)
    fr["wrist"] = wrist
    fr["elbow"] = ((shoulder[0] + wrist[0]) / 2, (shoulder[1] + wrist[1]) / 2)
    return fr


def make_series(pose_fn, n_frames=240, reps=2, lift="squat"):
    """Stand 1s -> `reps` reps -> stand 1s. Returns RawPoseSeries."""
    frames = []
    per = int((n_frames - 60) / reps)
    for i in range(n_frames):
        if i < 30 or i >= n_frames - 30:
            u = 0.0
        else:
            j = i - 30
            u = (j % per) / per
            if u > 0.92:  # brief stand between reps
                u = 0.0
        frames.append(pose_fn(min(u, 1.0)))

    x = np.zeros((n_frames, 33))
    y = np.zeros((n_frames, 33))
    vis = np.full((n_frames, 33), 0.99)
    for i, fr in enumerate(frames):
        for name, pt in fr.items():
            for side in ("left", "right"):
                key = f"{side}_{name}" if f"{side}_{name}" in LANDMARK_INDEX else name
                idx = LANDMARK_INDEX.get(key)
                if idx is None:
                    continue
                # slight L/R offset so one side dominates visibility? keep equal
                xn, yn = _img(pt)
                x[i, idx] = xn
                y[i, idx] = yn
    return RawPoseSeries(
        fps=FPS, width=W, height=H, x=x, y=y, visibility=vis,
        frame_indices=np.arange(n_frames),
    )
