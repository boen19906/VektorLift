"""
Velocity-based fatigue analysis (VBT).

For each rep we take the concentric phase (squat: bottom -> lockout;
deadlift: liftoff -> lockout) and compute:

    MCV   mean concentric velocity of the bar (m/s, or stature-units/s
          when no metric scale — velocity *loss %* is unit-independent)
    peak  peak concentric velocity
    VL%   velocity loss vs the fastest rep of the set
    TUT   time under tension

Fatigue interpretation uses standard VBT velocity-loss bands:
<10 % fresh, 10-20 % accumulating, 20-30 % high fatigue, >30 % stop.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.signal import savgol_filter


@dataclass
class RepVelocity:
    rep: int
    mcv: float               # mean concentric velocity
    peak_v: float            # peak concentric velocity
    v_loss_pct: float        # loss vs best rep, %
    concentric_s: float
    rom: float               # concentric bar travel
    flags: list = field(default_factory=list)


@dataclass
class FatigueResult:
    reps: list               # list[RepVelocity]
    best_mcv: float
    set_v_loss_pct: float    # first -> last rep loss
    fatigue_band: str        # 'fresh' | 'accumulating' | 'high' | 'excessive'
    bar_velocity: np.ndarray  # (N,) vertical bar velocity
    units: str               # 'm/s' | 'stature/s'


def _band(loss_pct: float) -> str:
    if loss_pct < 10:
        return "fresh"
    if loss_pct < 20:
        return "accumulating"
    if loss_pct < 30:
        return "high"
    return "excessive"


def compute_fatigue(pre, kin, metric_scale: bool) -> FatigueResult:
    bar_y = kin.bar_pos[:, 1]
    t = pre.t
    win = max(5, int(0.08 * pre.fps) | 1)
    if len(bar_y) > win:
        bar_v = savgol_filter(bar_y, win, 3, deriv=1, delta=1.0 / pre.fps)
    else:
        bar_v = np.gradient(bar_y, t)

    reps: list[RepVelocity] = []
    for rep in kin.reps:
        start = rep.bottom if kin.lift_type == "squat" else rep.pull_start
        sl = slice(start, rep.lockout + 1)
        if sl.stop - sl.start < 2:
            continue
        rom = float(bar_y[rep.lockout] - bar_y[start])
        dur = float(t[rep.lockout] - t[start])
        mcv = rom / dur if dur > 1e-6 else 0.0
        peak = float(np.max(bar_v[sl])) if sl.stop - sl.start else mcv
        reps.append(
            RepVelocity(
                rep=rep.index, mcv=mcv, peak_v=peak, v_loss_pct=0.0,
                concentric_s=dur, rom=rom,
            )
        )

    best = max((r.mcv for r in reps), default=0.0)
    for r in reps:
        r.v_loss_pct = float(100.0 * (best - r.mcv) / best) if best > 1e-9 else 0.0
        if r.v_loss_pct > 30:
            r.flags.append("velocity loss > 30% — mechanical failure zone")
        elif r.v_loss_pct > 20:
            r.flags.append("velocity loss > 20% — high fatigue")

    set_loss = (
        100.0 * (reps[0].mcv - reps[-1].mcv) / reps[0].mcv
        if len(reps) > 1 and reps[0].mcv > 1e-9
        else 0.0
    )

    return FatigueResult(
        reps=reps,
        best_mcv=best,
        set_v_loss_pct=float(set_loss),
        fatigue_band=_band(set_loss),
        bar_velocity=bar_v,
        units="m/s" if metric_scale else "stature/s",
    )
