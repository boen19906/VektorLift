"""
Joint kinematics and rep segmentation.

Produces per-frame sagittal joint angles plus a per-rep event segmentation:

    squat    : start -> descent -> bottom -> ascent -> lockout(end)
    deadlift : setup -> liftoff -> ascent -> lockout -> return(end)

All angles are in degrees; positions/velocities inherit the units of the
preprocess result (meters when scale was calibrated, else stature-units —
ratio-based checks like depth and velocity-loss still work either way).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.signal import find_peaks


@dataclass
class Rep:
    index: int                 # 1-based rep number
    start: int                 # frame: leave standing (squat) / setup (dl)
    pull_start: int            # frame: liftoff (dl) == bottom for squat
    bottom: int                # frame: squat bottom (== liftoff region for dl)
    lockout: int               # frame: top of ascent
    end: int                   # frame: return to standing / bar down
    metrics: dict = field(default_factory=dict)


@dataclass
class KinematicsResult:
    lift_type: str
    angles: dict               # name -> (N,) deg
    positions: dict            # alias of pre.positions
    velocities: dict
    reps: list
    standing_hip_y: float
    bar_pos: np.ndarray        # (N,2) bar position used downstream
    floor_bar_y: float         # deadlift: bar height at rest on floor
    bar_method: str = "proxy"  # 'plate' | 'proxy' (set by run.py)
    events: dict = field(default_factory=dict)


def _angle_between(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Interior angle (deg) between vectors a and b (each (N,2))."""
    cos = np.einsum("ij,ij->i", a, b) / (
        np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1) + 1e-12
    )
    return np.degrees(np.arccos(np.clip(cos, -1.0, 1.0)))


def compute_kinematics(pre, bar_pos: np.ndarray, lift_type: str) -> KinematicsResult:
    P, V = pre.positions, pre.velocities
    n = pre.n_frames

    knee_flexion = 180.0 - _angle_between(P["hip"] - P["knee"], P["ankle"] - P["knee"])
    hip_flexion = 180.0 - _angle_between(
        P["shoulder"] - P["hip"], P["knee"] - P["hip"]
    )
    trunk_vec = P["shoulder"] - P["hip"]
    trunk_incl = np.degrees(
        np.arctan2(trunk_vec[:, 0], np.clip(trunk_vec[:, 1], 1e-6, None))
    )
    shank_vec = P["knee"] - P["ankle"]
    shank_incl = np.degrees(
        np.arctan2(shank_vec[:, 0], np.clip(shank_vec[:, 1], 1e-6, None))
    )
    ankle_angle = _angle_between(
        P["knee"] - P["ankle"], P["foot_index"] - P["heel"]
    )

    angles = {
        "knee_flexion": knee_flexion,
        "hip_flexion": hip_flexion,
        "trunk_inclination": trunk_incl,
        "shank_inclination": shank_incl,
        "ankle_angle": ankle_angle,
    }

    standing_hip_y = float(P["hip"][pre.calib_frame, 1])
    floor_bar_y = float(np.nanmin(bar_pos[:, 1])) if lift_type == "deadlift" else 0.0

    if lift_type == "squat":
        reps = _segment_squat(pre, knee_flexion, standing_hip_y)
    else:
        reps = _segment_deadlift(pre, bar_pos, floor_bar_y)

    kin = KinematicsResult(
        lift_type=lift_type,
        angles=angles,
        positions=P,
        velocities=V,
        reps=reps,
        standing_hip_y=standing_hip_y,
        bar_pos=bar_pos,
        floor_bar_y=floor_bar_y,
    )
    _rep_metrics(kin, pre)
    _filter_implausible_reps(kin, pre)
    return kin


def _filter_implausible_reps(kin: KinematicsResult, pre) -> None:
    """Drop segmentation artifacts that no loaded rep could produce."""
    kept = []
    for rep in kin.reps:
        m = rep.metrics
        vis = float(np.mean(pre.key_visibility[rep.start : rep.end + 1]))
        if vis < 0.22:
            continue
        if kin.lift_type == "squat":
            if m.get("max_knee_flexion", 0) < 40:
                continue          # walk/bob, not a squat
            if m.get("duration_s", 99) < 0.8:
                continue          # too fast for a loaded full rep
        else:
            pull = m.get("concentric_s", 0)
            if pull < 0.25:
                continue          # a real pull takes >= ~0.3 s under load
        rep.index = len(kept) + 1
        kept.append(rep)
    kin.reps = kept


# --------------------------------------------------------------------------
# Segmentation
# --------------------------------------------------------------------------

def _segment_squat(pre, knee_flexion, standing_hip_y) -> list:
    """Rep boundaries from the vertical hip trajectory."""
    hip_y = pre.positions["hip"][:, 1]
    drop_needed = max(0.30 * standing_hip_y, 1e-3)
    valleys, props = find_peaks(-hip_y, prominence=drop_needed * 0.5)
    reps = []
    band = 0.15 * standing_hip_y  # 'returned to standing' band
    for vi, v in enumerate(valleys):
        if standing_hip_y - hip_y[v] < drop_needed:
            continue
        # expand left to last frame within standing band (or previous rep)
        s = v
        lo = reps[-1].end + 1 if reps else 0
        while s > lo and hip_y[s - 1] < standing_hip_y - band:
            s -= 1
        e = v
        hi = (valleys[vi + 1] if vi + 1 < len(valleys) else len(hip_y) - 1)
        while e < hi and hip_y[e + 1] < standing_hip_y - band:
            e += 1
        # lockout = highest hip between bottom and end
        lo_i = s + int(np.argmax(hip_y[s : e + 1])) if e > s else v
        # lockout must come after the bottom
        if lo_i <= v:
            lo_i = e
        reps.append(
            Rep(index=len(reps) + 1, start=s, pull_start=v, bottom=v,
                lockout=lo_i, end=e)
        )
    return reps


def _segment_deadlift(pre, bar_pos, floor_bar_y) -> list:
    """Rep boundaries from bar height: floor -> lockout -> floor."""
    bar_y = bar_pos[:, 1]
    lock_h = np.nanmax(bar_y)
    rise_needed = max(0.4 * (lock_h - floor_bar_y), 1e-3)
    peaks, _ = find_peaks(bar_y, prominence=rise_needed * 0.5)
    floor_band = floor_bar_y + 0.04 * max(lock_h - floor_bar_y, 1e-3) + 0.02
    reps = []
    for pi, p in enumerate(peaks):
        if bar_y[p] - floor_bar_y < rise_needed:
            continue
        # walk back to the last floor contact before this peak
        lo = reps[-1].end + 1 if reps else 0
        s = p
        while s > lo and bar_y[s - 1] > floor_band:
            s -= 1
        # liftoff = first frame clearly off the floor
        liftoff = s
        while liftoff < p and bar_y[liftoff] <= floor_band:
            liftoff += 1
        e = p
        hi = (peaks[pi + 1] if pi + 1 < len(peaks) else len(bar_y) - 1)
        while e < hi and bar_y[e + 1] > floor_band:
            e += 1
        reps.append(
            Rep(index=len(reps) + 1, start=s, pull_start=liftoff, bottom=liftoff,
                lockout=p, end=e)
        )
    return reps


# --------------------------------------------------------------------------
# Per-rep metrics
# --------------------------------------------------------------------------

def _rep_metrics(kin: KinematicsResult, pre) -> None:
    P, V, A = kin.positions, kin.velocities, kin.angles
    fps, t = pre.fps, pre.t
    bar = kin.bar_pos

    for rep in kin.reps:
        m = rep.metrics
        s, b, lo, e = rep.start, rep.bottom, rep.lockout, rep.end
        # physiological sanity: values past these bounds are landmark noise,
        # not human joints — surfaced as 'tracking_suspect' in the report
        m["tracking_suspect"] = bool(
            np.nanmax(np.abs(A["knee_flexion"][s : e + 1])) > 160
            or np.nanmax(np.abs(A["trunk_inclination"][s : e + 1])) > 85
        )
        m["duration_s"] = float(t[e] - t[s])
        m["t_start"], m["t_bottom"], m["t_lockout"], m["t_end"] = (
            float(t[s]), float(t[b]), float(t[lo]), float(t[e]),
        )
        m["max_knee_flexion"] = float(np.max(A["knee_flexion"][s : e + 1]))
        m["min_hip_y"] = float(np.min(P["hip"][s : e + 1, 1]))

        if kin.lift_type == "squat":
            m["eccentric_s"] = float(t[b] - t[s])
            m["concentric_s"] = float(t[lo] - t[b])
            m["pause_s"] = 0.0
            # depth: hip crease below knee => positive margin
            m["depth_margin"] = float(P["knee"][b, 1] - P["hip"][b, 1])
            m["trunk_incl_bottom"] = float(A["trunk_inclination"][b])
            m["trunk_incl_max"] = float(np.max(A["trunk_inclination"][s : e + 1]))
            # butt wink: hip flexion keeps closing while the hip has stopped
            # descending (bottom dwell, +-0.15 s around the bottom)
            dwell = slice(
                max(s, b - int(0.15 * fps)), min(e + 1, b + int(0.15 * fps) + 1)
            )
            hip_y_dwell = P["hip"][dwell, 1]
            bottom_local = int(np.argmin(hip_y_dwell))
            bw = (
                float(
                    A["hip_flexion"][dwell][-1]
                    - A["hip_flexion"][dwell][bottom_local]
                )
                if dwell.stop - dwell.start > 2 else 0.0
            )
            m["buttwink_deg"] = float(np.clip(bw, -15.0, 30.0))
            # good-morning: early concentric hip rise outpacing bar rise
            win = slice(b, min(lo + 1, b + int(0.4 * fps)))
            if win.stop - win.start > 2:
                hip_rise = P["hip"][win, 1][-1] - P["hip"][win, 1][0]
                bar_rise = bar[win, 1][-1] - bar[win, 1][0]
                m["hip_rise_early"] = float(hip_rise)
                m["bar_rise_early"] = float(bar_rise)
                m["hip_bar_rise_ratio"] = (
                    float(hip_rise / bar_rise) if bar_rise > 1e-4 else None
                )
            m["heel_lift_max"] = float(np.max(P["heel"][s : e + 1, 1]))
            m["knee_over_toe_max"] = float(
                np.max(P["knee"][s : e + 1, 0] - P["foot_index"][s : e + 1, 0])
            )
            # bar drift relative to midfoot, in foot lengths
            drift = bar[s : e + 1, 0] - pre.midfoot_x[s : e + 1]
            m["bar_drift_max"] = float(np.max(np.abs(drift)))
            m["bar_path_range_x"] = float(np.ptp(bar[s : e + 1, 0]))
        else:  # deadlift
            m["concentric_s"] = float(t[lo] - t[rep.pull_start])
            m["setup_i"] = rep.start
            m["liftoff_i"] = rep.pull_start
            # hip-rise-vs-bar-rise over first 30% of the pull
            n_pull = max(2, int(0.3 * (rep.lockout - rep.pull_start)))
            win = slice(rep.pull_start, rep.pull_start + n_pull)
            hip_rise = P["hip"][win, 1][-1] - P["hip"][win, 1][0]
            bar_rise = bar[win, 1][-1] - bar[win, 1][0]
            m["hip_rise_early"] = float(hip_rise)
            m["bar_rise_early"] = float(bar_rise)
            m["hip_bar_rise_ratio"] = (
                float(hip_rise / bar_rise) if bar_rise > 1e-4 else None
            )
            # back angle: trunk inclination at setup vs through the pull
            m["trunk_incl_setup"] = float(A["trunk_inclination"][rep.start])
            m["trunk_incl_liftoff"] = float(
                np.max(A["trunk_inclination"][rep.pull_start : rep.pull_start + int(0.3 * fps)])
            )
            m["trunk_incl_lockout"] = float(A["trunk_inclination"][rep.lockout])
            # bar should stay over midfoot the whole pull; also measure total
            # horizontal excursion (ideal path is nearly vertical)
            drift = bar[s : e + 1, 0] - pre.midfoot_x[s : e + 1]
            m["bar_off_midfoot_max"] = (
                float(np.max(np.abs(drift))) if len(drift) else 0.0
            )
            m["bar_path_range_x"] = float(np.ptp(bar[s : e + 1, 0]))
            # hitching: non-monotonic bar ascent (downward moves while pulling)
            dy = np.diff(bar[rep.pull_start : rep.lockout + 1, 1])
            m["bar_reversals"] = int(np.sum(dy < -0.005))
            m["trunk_incl_max"] = float(np.max(A["trunk_inclination"][s : e + 1]))
            m["heel_lift_max"] = float(np.max(P["heel"][s : e + 1, 1]))
