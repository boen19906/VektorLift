"""
Form-fault rule engine.

Rules are declarative functions over the per-rep feature dict built by
kinematics/dynamics/fatigue. Each returns zero or more Findings carrying the
*measured number* that fired the rule — every cue is traceable to data.

Severity: 1 = minor efficiency leak, 2 = meaningful fault, 3 = injury risk.
Findings are deduplicated by rule (worst rep wins) and sorted by severity.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class Finding:
    rule: str
    lift: str
    severity: int            # 1-3
    title: str
    evidence: str            # the measured value(s)
    cue: str                 # what to do next rep
    drill: str               # how to train the fix
    reps: list = field(default_factory=list)
    timestamp: float = 0.0   # representative time (s) into the video
    body_part: str = ""      # anatomy at risk (e.g. 'lumbar spine')


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _worst(reps, key, fn=max, default=None):
    vals = [(r.metrics.get(key), r) for r in reps if r.metrics.get(key) is not None]
    vals = [(v, r) for v, r in vals if np.isfinite(v)]
    if not vals:
        return default
    v, r = fn(vals, key=lambda x: x[0])
    return v, r


def _ctx(kin, dyn, fat, anthro, pre):
    return {
        "kin": kin, "dyn": dyn, "fat": fat, "anthro": anthro, "pre": pre,
        "reps": kin.reps,
        "foot_len": anthro.lengths.get("foot", 0.28),
        # 'plate' => true bar track; 'proxy' => shoulder/wrist stand-in.
        "bar_method": getattr(kin, "bar_method", "proxy"),
    }


# ---------------------------------------------------------------------------
# SQUAT rules — each takes ctx, returns [Finding]
# ---------------------------------------------------------------------------

def r_depth(c):
    out = []
    for rep in c["reps"]:
        margin = rep.metrics.get("depth_margin")
        if margin is None:
            continue
        thigh = c["anthro"].lengths.get("thigh", 0.45)
        if margin < -0.02 * thigh:  # clearly above parallel
            out.append(Finding(
                "squat_depth", "squat", 2, "Squat is above parallel",
                f"hip crease {abs(margin):.2f} m above the knee at the bottom "
                f"(rep {rep.index})",
                "Sit down until your hip crease passes below the top of your "
                "knee — think 'hips to ankles', not 'knees forward'.",
                "Paused box squats to a target just below parallel; ankle-"
                "mobility work if depth is blocked by dorsiflexion.",
                [rep.index], rep.metrics.get("t_bottom", 0.0),
            ))
    return out


def r_trunk_lean(c):
    expected = c["anthro"].expected_trunk_lean()
    hit = _worst(c["reps"], "trunk_incl_bottom")
    if not hit:
        return []
    v, rep = hit
    if v > expected + 12:
        return [Finding(
            "squat_lean", "squat", 2, "Excessive forward lean at the bottom",
            f"trunk {v:.0f}° from vertical vs ~{expected:.0f}° expected for "
            f"your proportions (rep {rep.index})",
            "Brace harder into the belt and drive your chest up out of the "
            "hole; keep elbows under the bar.",
            "Tempo squats and high-bar/pause variations to groove upright "
            "positions; thoracic mobility work.",
            [rep.index], rep.metrics.get("t_bottom", 0.0),
        )]
    return []


def r_buttwink(c):
    hit = _worst(c["reps"], "buttwink_deg")
    if not hit:
        return []
    v, rep = hit
    if v > 8:
        return [Finding(
            "buttwink", "squat", 3, "Posterior pelvic tilt ('butt wink')",
            f"hip angle kept closing {v:.0f}° after the hips stopped "
            f"descending (rep {rep.index}) — pelvis tucking under load",
            "Stop the descent 2-3 cm higher and keep your ribs down; brace "
            "360° before you descend instead of relaxing at the bottom.",
            "Squat-to-stand drills, goblet squat pauses above the wink "
            "depth, hip-flexor and ankle mobility.",
            [rep.index], rep.metrics.get("t_bottom", 0.0),
        )]
    return []


def r_good_morning(c):
    hit = _worst(c["reps"], "hip_bar_rise_ratio")
    if not hit:
        return []
    v, rep = hit
    if np.isfinite(v) and v > 1.8 and rep.metrics.get("hip_rise_early", 0) > 0.05:
        return [Finding(
            "good_morning", "squat", 3, "Hips shoot up before the bar "
            "('good morning' squat)",
            f"hips rose {v:.1f}x faster than the bar in the first part of "
            f"the ascent (rep {rep.index}) — load is shifting to the low back",
            "Push the floor away and drive your upper back INTO the bar at "
            "the same time; think 'chest and hips rise together'.",
            "Pin squats from the hole, tempo ascents, and quad strengthening "
            "(the fault usually means quads are the weak link).",
            [rep.index], rep.metrics.get("t_lockout", 0.0),
        )]
    return []


def r_heel_lift(c):
    hit = _worst(c["reps"], "heel_lift_max")
    if not hit:
        return []
    v, rep = hit
    thresh = 0.02 if c["pre"].px_per_m else 0.015
    if v > thresh:
        return [Finding(
            "heel_lift", "squat", 2, "Heels come off the floor",
            f"heel rose {v:.2f} units above the floor (rep {rep.index})",
            "Keep pressure through midfoot — spread the floor and jam the "
            "big toe down; do not let your weight rock forward.",
            "Ankle dorsiflexion mobilization; consider heel-elevated "
            "squat shoes if mobility is the limiter.",
            [rep.index], rep.metrics.get("t_bottom", 0.0),
        )]
    return []


def r_bar_drift_squat(c):
    # horizontal excursion of the bar during the rep — a good squat bar path
    # is nearly vertical. Requires a real plate track: the shoulder proxy is
    # not the bar (the torso leans, translating the shoulder ~0.3-0.5 m).
    if c["bar_method"] != "plate":
        return []
    hit = _worst(c["reps"], "bar_path_range_x")
    if not hit:
        return []
    v, rep = hit
    if v > 0.12:
        return [Finding(
            "bar_drift", "squat", 2, "Bar path is not vertical",
            f"bar wandered {v:.2f} m horizontally during the rep "
            f"(rep {rep.index}) — wasted horizontal work and balance stress",
            "Keep the bar stacked over the middle of your foot the whole "
            "rep; if it drifts forward on the way up, sit BACK more on "
            "the descent.",
            "Film check: draw a vertical line at midfoot; wall-facing "
            "squats to groove a vertical bar path.",
            [rep.index], rep.metrics.get("t_bottom", 0.0),
        )]
    return []


def r_torque_asym(c):
    """Hip:Knee moment ratio far outside the usual band."""
    if not c["dyn"] or not c["dyn"].rep_peaks:
        return []
    ratios = [p["hip_knee_ratio"] for p in c["dyn"].rep_peaks
              if p.get("hip_knee_ratio")]
    if not ratios:
        return []
    med = float(np.median(ratios))
    if med > 2.6:
        return [Finding(
            "hip_dominant", "squat", 1, "Very hip-dominant squat",
            f"peak hip moment is {med:.1f}x the knee moment — the quads "
            "are barely contributing",
            "Let your knees travel further forward and keep a more upright "
            "torso; you are turning the squat into a hinge.",
            "High-bar or front squats, heels-elevated variations to load "
            "the quads.",
            [], 0.0,
        )]
    if med < 0.9:
        return [Finding(
            "knee_dominant", "squat", 1, "Very knee-dominant squat",
            f"peak hip moment is only {med:.1f}x the knee moment — hips "
            "underused",
            "Reach your hips back more on the descent and let your torso "
            "lean a little; the posterior chain is not sharing the load.",
            "Low-bar patterning, box squats with a vertical shin to "
            "re-introduce hip drive.",
            [], 0.0,
        )]
    return []


# ---------------------------------------------------------------------------
# DEADLIFT rules
# ---------------------------------------------------------------------------

def r_dl_hips_shoot(c):
    hit = _worst(c["reps"], "hip_bar_rise_ratio")
    if not hit:
        return []
    v, rep = hit
    if np.isfinite(v) and v > 2.0 and rep.metrics.get("hip_rise_early", 0) > 0.04:
        return [Finding(
            "dl_hips_shoot", "deadlift", 3, "Hips rise before the bar "
            "leaves the floor",
            f"hips rose {v:.1f}x faster than the bar in the first 30% of "
            f"the pull (rep {rep.index}) — you end up stiff-legging it",
            "Set your hips lower OR push the floor away harder — your knees "
            "should extend WITH the bar rising, not before it.",
            "Pause deadlifts 2 cm off the floor; deficit pulls to groove "
            "leg drive.",
            [rep.index], rep.metrics.get("t_lockout", 0.0),
        )]
    return []


def r_dl_back_angle(c):
    out = []
    for rep in c["reps"]:
        setup = rep.metrics.get("trunk_incl_setup")
        liftoff = rep.metrics.get("trunk_incl_liftoff")
        if setup is None or liftoff is None:
            continue
        delta = liftoff - setup
        if delta > 8:
            out.append(Finding(
                "dl_back_angle", "deadlift", 3, "Back angle collapses as "
                "the pull starts",
                f"trunk inclination increased {delta:.0f}° between setup "
                f"and just after liftoff (rep {rep.index}) — consistent "
                "with losing spinal position under load",
                "Pull the slack out, then push the floor away while "
                "holding your chest at the exact angle you set. Don't "
                "jerk the bar.",
                "Dead-stop reps with a 2 s setup hold; lat engagement "
                "drills ('bend the bar around your shins').",
                [rep.index], rep.metrics.get("t_lockout", 0.0),
            ))
    return out


def r_dl_bar_drift(c):
    hit = _worst(c["reps"], "bar_off_midfoot_max")
    if not hit:
        return []
    v, rep = hit
    if v > 0.12:
        return [Finding(
            "dl_bar_drift", "deadlift", 2, "Bar drifts away from the body",
            f"bar reached {v:.2f} m off the midfoot line "
            f"(rep {rep.index}) — longer moment arm on the low back",
            "Drag the bar up your shins and thighs; it should feel like "
            "it is shaving your legs the whole way.",
            "Lat-setting drill before every pull; Romanian deadlifts to "
            "practice a close bar path.",
            [rep.index], rep.metrics.get("t_lockout", 0.0),
        )]
    return []


def r_dl_hitch(c):
    hit = _worst(c["reps"], "bar_reversals")
    if not hit:
        return []
    v, rep = hit
    if v >= 2:
        return [Finding(
            "dl_hitch", "deadlift", 1, "Bar stalls/hitches around the knees",
            f"bar reversed direction {v} times during the ascent "
            f"(rep {rep.index})",
            "Keep the bar glued to your legs through the knee region and "
            "drive the hips THROUGH, not up — hitching means the hips are "
            "behind the bar.",
            "Block pulls from just below the knee at moderate load.",
            [rep.index], rep.metrics.get("t_lockout", 0.0),
        )]
    return []


def r_dl_leanback(c):
    out = []
    for rep in c["reps"]:
        incl = rep.metrics.get("trunk_incl_lockout")
        if incl is not None and incl < -8:
            out.append(Finding(
                "dl_leanback", "deadlift", 1, "Over-leaning back at lockout",
                f"trunk {incl:.0f}° (backward) at lockout (rep {rep.index}) "
                "— hyperextension, not a stronger lockout",
                "Finish tall: squeeze the glutes and stand straight — "
                "shoulders behind hips is enough.",
                "RKC plank / glute-bridge patterning for lockout tension.",
                [rep.index], rep.metrics.get("t_lockout", 0.0),
            ))
    return out


def r_fatigue(c):
    """Cross-lift: set-level velocity loss guidance."""
    fat = c["fat"]
    if not fat or len(fat.reps) < 2:
        return []
    band = fat.fatigue_band
    if band in ("high", "excessive"):
        sev = 2 if band == "high" else 3
        return [Finding(
            "vbt_fatigue", c["kin"].lift_type, sev,
            f"Set fatigue is {band} — bar speed collapsed",
            f"mean concentric velocity dropped {fat.set_v_loss_pct:.0f}% "
            f"from rep {fat.reps[0].rep} to rep {fat.reps[-1].rep}; reps "
            "past ~25% velocity loss add fatigue without adding strength",
            "End the set (or rest longer). If you are training for max "
            "strength, cut sets when velocity loss hits ~20-25%.",
            "Autoregulate with velocity: keep a running note of first-rep "
            "MCV as your daily readiness baseline.",
            [fat.reps[-1].rep], 0.0,
        )]
    return []


SQUAT_RULES = [
    r_depth, r_buttwink, r_good_morning, r_trunk_lean,
    r_heel_lift, r_bar_drift_squat, r_torque_asym, r_fatigue,
]
DEADLIFT_RULES = [
    r_dl_hips_shoot, r_dl_back_angle, r_dl_bar_drift,
    r_dl_hitch, r_dl_leanback, r_fatigue,
]

# anatomy stressed by each fault — shown as a tag on the finding card
BODY_PARTS = {
    "squat_depth": "knees / ankles",
    "buttwink": "lumbar spine",
    "good_morning": "lumbar spine",
    "squat_lean": "thoracic / lumbar spine",
    "heel_lift": "ankles / knees",
    "bar_drift": "lumbar spine",
    "hip_dominant": "glutes / lower back",
    "knee_dominant": "knees",
    "dl_hips_shoot": "lumbar spine",
    "dl_back_angle": "lumbar spine",
    "dl_bar_drift": "lumbar spine",
    "dl_hitch": "lumbar spine",
    "dl_leanback": "lumbar spine",
    "vbt_fatigue": "whole system",
}


def evaluate_rules(kin, dyn, fat, anthro, pre) -> list:
    ctx = _ctx(kin, dyn, fat, anthro, pre)
    rules = SQUAT_RULES if kin.lift_type == "squat" else DEADLIFT_RULES
    findings = []
    for rule in rules:
        try:
            findings.extend(rule(ctx))
        except Exception:
            continue  # a broken rule must never kill the analysis

    # merge duplicate findings from the same rule across reps into one card
    merged: dict = {}
    for f in findings:
        f.body_part = BODY_PARTS.get(f.rule, "")
        m = merged.get(f.rule)
        if m is None:
            merged[f.rule] = f
        else:
            m.reps = sorted(set(m.reps) | set(f.reps))
            m.severity = max(m.severity, f.severity)
            if f.timestamp and (not m.timestamp or f.timestamp < m.timestamp):
                m.timestamp = f.timestamp
    findings = sorted(merged.values(), key=lambda f: -f.severity)
    return findings
