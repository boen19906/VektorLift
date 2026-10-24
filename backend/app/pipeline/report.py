"""
Report assembly: everything the frontend needs as one JSON-serializable dict.
"""
from __future__ import annotations

import numpy as np


def _ds(x: np.ndarray, n: int = 400) -> list:
    """Downsample a series for charting."""
    x = np.asarray(x, dtype=float)
    if len(x) <= n:
        return [round(float(v), 4) for v in x]
    idx = np.linspace(0, len(x) - 1, n).astype(int)
    return [round(float(x[i]), 4) for i in idx]


def _clean(v):
    """numpy scalars -> native python types for json; non-finite -> None.

    Infinity/NaN are not valid JSON — browsers' strict JSON.parse rejects
    them, which silently breaks result loading."""
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float):
        return round(v, 4) if np.isfinite(v) else None
    return v


def build_report(
    meta: dict,
    pre,
    anthro,
    kin,
    dyn,
    fat,
    findings,
    bar_method: str,
) -> dict:
    reps = []
    fat_by_rep = {r.rep: r for r in (fat.reps if fat else [])}
    peaks_by_rep = {p["rep"]: p for p in (dyn.rep_peaks if dyn else [])}
    for rep in kin.reps:
        fv = fat_by_rep.get(rep.index)
        pk = peaks_by_rep.get(rep.index)
        reps.append({
            "index": int(rep.index),
            "frames": {
                "start": int(rep.start), "bottom": int(rep.bottom),
                "lockout": int(rep.lockout), "end": int(rep.end),
            },
            "metrics": {k: _clean(v) for k, v in rep.metrics.items()},
            "velocity": ({
                "mcv": round(fv.mcv, 4), "peak": round(fv.peak_v, 4),
                "v_loss_pct": round(fv.v_loss_pct, 1),
                "concentric_s": round(fv.concentric_s, 3),
                "rom": round(fv.rom, 4), "flags": fv.flags,
            } if fv else None),
            "torque_peaks": ({
                k: (round(v, 4) if isinstance(v, float) else v)
                for k, v in pk.items() if k != "rep"
            } if pk else None),
        })

    quality = {
        "key_visibility_mean": round(float(np.mean(pre.key_visibility)), 3),
        "frames_usable_pct": round(
            100.0 * float(np.mean(pre.quality_ok)), 1
        ),
        "bar_tracking": bar_method,
        "metric_scale": bool(pre.px_per_m),
        "camera_side_on": bool(pre.camera_side_on),
        "shoulder_sep_frac": round(pre.shoulder_sep_frac, 3),
    }

    return {
        "meta": meta,
        "lift_type": kin.lift_type,
        "side": pre.side,
        "fps": pre.fps,
        "duration_s": round(float(pre.t[-1] - pre.t[0]), 2),
        "anthropometry": {
            "lengths": {k: round(v, 4) for k, v in anthro.lengths.items()},
            "ratios": {k: round(v, 3) for k, v in anthro.ratios.items()},
            "expected_trunk_lean_deg": round(
                anthro.expected_trunk_lean(), 1
            ),
        },
        "reps": reps,
        "fatigue": ({
            "best_mcv": round(fat.best_mcv, 4),
            "set_v_loss_pct": round(fat.set_v_loss_pct, 1),
            "fatigue_band": fat.fatigue_band,
            "units": fat.units,
        } if fat else None),
        "findings": [
            {
                "rule": f.rule, "severity": f.severity, "title": f.title,
                "evidence": f.evidence, "cue": f.cue, "drill": f.drill,
                "body_part": f.body_part,
                "reps": f.reps, "timestamp": round(f.timestamp, 2),
            }
            for f in findings
        ],
        "series": {
            "t": _ds(pre.t),
            "hip_y": _ds(pre.positions["hip"][:, 1]),
            "bar_y": _ds(kin.bar_pos[:, 1]),
            "bar_x": _ds(kin.bar_pos[:, 0]),
            "knee_flexion": _ds(kin.angles["knee_flexion"]),
            "hip_flexion": _ds(kin.angles["hip_flexion"]),
            "trunk_inclination": _ds(kin.angles["trunk_inclination"]),
            "bar_v": _ds(fat.bar_velocity) if fat else [],
            "knee_moment": _ds(dyn.moments_norm["knee"]) if dyn else [],
            "hip_moment": _ds(dyn.moments_norm["hip"]) if dyn else [],
            "l5s1_moment": _ds(dyn.moments_norm["l5s1"]) if dyn else [],
        },
        "quality": quality,
    }
