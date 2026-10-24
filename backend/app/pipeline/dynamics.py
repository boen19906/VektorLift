"""
2-D sagittal inverse statics/dynamics.

Model: bilateral lumped rigid links (foot, shank, thigh, HAT) plus the
barbell as a point mass at its tracked/proxied position.

Method
------
1. Segment COM kinematics from joint positions (de Leva COM fractions),
   accelerations via Savitzky-Golay second derivatives.
2. Whole-system ground reaction force estimated from D'Alembert:
       Fy = sum_i m_i (a_yi + g)      (includes the bar)
       Fx = sum_i m_i a_xi
   Center of pressure is taken at the midfoot (toe when the heel is lifted).
3. Net joint moments propagated distal -> proximal: the internal moment at a
   joint equals the negative of the moment produced about that joint by every
   external + inertial load acting on segments *below* it (ankle/knee/hip).
   For L5/S1 we integrate from *above* (HAT + bar).

Moments are the net internal joint moments as computed from the below-side
(ankle/knee/hip) or above-side (L5/S1) force system — per-rep peaks are
reported as magnitudes, which is the interpretable quantity. All outputs
are also normalized by bodyweight (N m / kg) so lifts compare across
lifters.

This is an *estimate* — no force plate — and is meant for rep-to-rep and
lifter-to-lifter comparison, injury-risk flagging, and technique diagnosis,
not for absolute clinical measurement.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.signal import savgol_filter

G = 9.81


@dataclass
class DynamicsResult:
    moments: dict          # 'ankle'|'knee'|'hip'|'l5s1' -> (N,) N m, extensor+
    moments_norm: dict     # same, / bodyweight
    grf: np.ndarray        # (N,2) estimated ground reaction force
    cop_x: np.ndarray      # (N,) center of pressure x
    segment_coms: dict     # name -> (N,2)
    rep_peaks: list        # per-rep peak moments etc.


def _com_series(a: np.ndarray, b: np.ndarray, frac: float) -> np.ndarray:
    return a + frac * (b - a)


def _accel(x: np.ndarray, fps: float, win: int) -> np.ndarray:
    win = min(win, len(x) - 1 if (len(x) - 1) % 2 else len(x) - 2)
    win = max(win, 5)
    return np.column_stack(
        [
            savgol_filter(x[:, 0], win, 3, deriv=2, delta=1.0 / fps),
            savgol_filter(x[:, 1], win, 3, deriv=2, delta=1.0 / fps),
        ]
    )


def _segment_alpha(a: np.ndarray, b: np.ndarray, fps: float, win: int) -> np.ndarray:
    """Angular acceleration of segment A->B (rad/s^2)."""
    d = b - a
    theta = np.unwrap(np.arctan2(d[:, 1], d[:, 0]))
    w = min(win, len(theta) - 1 if (len(theta) - 1) % 2 else len(theta) - 2)
    return savgol_filter(theta, max(5, w), 3, deriv=2, delta=1.0 / fps)


def _moment_about(point: np.ndarray, force: np.ndarray, at: np.ndarray) -> np.ndarray:
    """2-D moment of `force` applied `at`, taken about `point` (all (N,2))."""
    r = at - point
    return r[:, 0] * force[:, 1] - r[:, 1] * force[:, 0]


def compute_dynamics(
    pre,
    anthro,
    kin,
    bar_pos: np.ndarray,
    bar_kg: float,
    dynamic: bool = True,
) -> DynamicsResult:
    P = pre.positions
    fps, n = pre.fps, pre.n_frames
    win = max(7, int(0.15 * fps) | 1)

    seg = anthro.segments
    coms = {
        "foot": _com_series(P["heel"], P["foot_index"], seg["foot"].com_frac),
        "shank": _com_series(P["knee"], P["ankle"], seg["shank"].com_frac),
        "thigh": _com_series(P["hip"], P["knee"], seg["thigh"].com_frac),
        "hat": _com_series(P["hip"], P["shoulder"], seg["hat"].com_frac),
    }
    acc = {k: (_accel(v, fps, win) if dynamic else np.zeros_like(v))
           for k, v in coms.items()}
    bar_acc = _accel(bar_pos, fps, win) if dynamic else np.zeros_like(bar_pos)

    alpha = {
        "foot": _segment_alpha(P["heel"], P["foot_index"], fps, win),
        "shank": _segment_alpha(P["ankle"], P["knee"], fps, win),
        "thigh": _segment_alpha(P["knee"], P["hip"], fps, win),
        "hat": _segment_alpha(P["hip"], P["shoulder"], fps, win),
    }

    # ---- whole-system GRF -------------------------------------------------
    masses = {"foot": seg["foot"].mass, "shank": seg["shank"].mass,
              "thigh": seg["thigh"].mass, "hat": seg["hat"].mass}
    fy = np.zeros(n)
    fx = np.zeros(n)
    for k, m in masses.items():
        fy += m * (acc[k][:, 1] + G)
        fx += m * acc[k][:, 0]
    fy += bar_kg * (bar_acc[:, 1] + G)
    fx += bar_kg * bar_acc[:, 0]
    grf = np.column_stack([fx, fy])

    heel_lift = P["heel"][:, 1] > 0.02 if pre.px_per_m else np.zeros(n, bool)
    cop_x = np.where(heel_lift, P["foot_index"][:, 0], pre.midfoot_x)
    cop = np.column_stack([cop_x, np.zeros(n)])

    # ---- below-side force/moment accumulation ------------------------------
    # body force of a segment = weight + D'Alembert inertia: m*(g - a) applied
    # at its COM; plus a pure inertial couple -I*alpha.
    def body_terms(name):
        m = masses[name]
        # gravity + D'Alembert inertia: F = (-m a_x, -m(g + a_y)) at the COM
        F = np.column_stack(
            [-m * acc[name][:, 0], -m * (G + acc[name][:, 1])]
        )
        return F, -seg[name].inertia * alpha[name]

    # moment about joint J of everything BELOW J; internal moment = -that
    def below_moment(joint_pos: np.ndarray, seg_names: list[str]) -> np.ndarray:
        M = _moment_about(joint_pos, grf, cop)
        for name in seg_names:
            F, couple = body_terms(name)
            M += _moment_about(joint_pos, F, coms[name]) + couple
        return -M

    moments = {
        "ankle": below_moment(P["ankle"], ["foot"]),
        "knee": below_moment(P["knee"], ["foot", "shank"]),
        "hip": below_moment(P["hip"], ["foot", "shank", "thigh"]),
    }

    # ---- L5/S1 from above: HAT + bar ---------------------------------------
    l5s1 = P["hip"] + 0.15 * (P["shoulder"] - P["hip"])
    F_hat, c_hat = body_terms("hat")
    F_bar = np.column_stack(
        [-bar_kg * bar_acc[:, 0], -bar_kg * (G + bar_acc[:, 1])]
    )
    M_above = (
        _moment_about(l5s1, F_hat, coms["hat"])
        + c_hat
        + _moment_about(l5s1, F_bar, bar_pos)
    )
    # internal extensor moment opposes the flexion moment of the load above
    moments["l5s1"] = -M_above

    bw = max(anthro.bodyweight_kg, 1e-6)
    moments_norm = {k: v / bw for k, v in moments.items()}

    # ---- per-rep peaks -------------------------------------------------------
    rep_peaks = []
    for rep in kin.reps:
        sl = slice(rep.start, rep.end + 1)
        pk = {
            "rep": rep.index,
            "ankle_peak": float(np.max(np.abs(moments["ankle"][sl]))),
            "knee_peak": float(np.max(np.abs(moments["knee"][sl]))),
            "hip_peak": float(np.max(np.abs(moments["hip"][sl]))),
            "l5s1_peak": float(np.max(np.abs(moments["l5s1"][sl]))),
            "knee_peak_norm": float(
                np.max(np.abs(moments_norm["knee"][sl]))
            ),
            "hip_peak_norm": float(np.max(np.abs(moments_norm["hip"][sl]))),
            "l5s1_peak_norm": float(np.max(np.abs(moments_norm["l5s1"][sl]))),
        }
        hip_pk = abs(pk["hip_peak_norm"])
        knee_pk = abs(pk["knee_peak_norm"])
        pk["hip_knee_ratio"] = (
            float(hip_pk / knee_pk) if knee_pk > 1e-6 else None
        )
        rep_peaks.append(pk)

    return DynamicsResult(
        moments=moments,
        moments_norm=moments_norm,
        grf=grf,
        cop_x=cop_x,
        segment_coms=coms,
        rep_peaks=rep_peaks,
    )
