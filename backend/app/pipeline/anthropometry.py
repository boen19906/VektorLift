"""
Anthropometric model: measured segment lengths + de Leva (1996) inertial params.

Two jobs:

1. Measure the lifter's segment lengths from the standing-calibration frame
   (thigh, shank, trunk, foot, upper+fore arm). These drive *anthropometric
   normalization*: expected joint angles and fault thresholds are expressed in
   units of the lifter's own proportions instead of population averages.

2. Provide body-segment mass fractions, center-of-mass locations, and radii of
   gyration from de Leva (1996), scaled by the user's bodyweight. The dynamics
   module consumes these to run inverse statics.

Reference: de Leva, P. (1996). "Adjustments to Zatsiorsky-Seluyanov's segment
inertia parameters." J. Biomechanics 29(9), 1223-1230.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


# de Leva 1996, mean values. com_frac measured from the PROXIMAL joint toward
# the distal joint; gyration_frac is radius of gyration / segment length about
# the segment COM.
DE_LEVA = {
    "male": {
        #            mass%   com%   gyr%
        "head":       (0.0694, 0.5000, 0.3030),
        "trunk":      (0.4346, 0.5002, 0.3270),  # shoulder->hip, com from top
        "upper_arm":  (0.0271, 0.5772, 0.2850),
        "forearm":    (0.0162, 0.4574, 0.2760),
        "hand":       (0.0061, 0.7900, 0.6280),
        "thigh":      (0.1416, 0.4095, 0.3290),
        "shank":      (0.0433, 0.4459, 0.2550),
        "foot":       (0.0137, 0.4415, 0.4750),
    },
    "female": {
        "head":       (0.0668, 0.4841, 0.2710),
        "trunk":      (0.4257, 0.4964, 0.3070),
        "upper_arm":  (0.0255, 0.5754, 0.2780),
        "forearm":    (0.0138, 0.4559, 0.2610),
        "hand":       (0.0056, 0.7474, 0.5310),
        "thigh":      (0.1478, 0.3612, 0.3690),
        "shank":      (0.0481, 0.4416, 0.2710),
        "foot":       (0.0129, 0.4014, 0.2990),
    },
}

# Lumped head+arms+trunk fraction used for the single "HAT" segment in the
# sagittal model (arms hang with trunk for squat; for deadlift the arm load
# path is handled separately via the bar force at the hands).
def hat_mass_fraction(sex: str) -> float:
    t = DE_LEVA.get(sex, DE_LEVA["male"])
    return (
        t["head"][0] + t["trunk"][0]
        + 2 * (t["upper_arm"][0] + t["forearm"][0] + t["hand"][0])
    )


@dataclass
class SegmentParams:
    """One rigid segment's inertial parameters for the 2-D model."""
    name: str
    length: float          # m
    mass: float            # kg
    com_frac: float        # COM position along segment from endpoint A
    inertia: float         # kg m^2 about segment COM (sagittal)


@dataclass
class Anthropometry:
    sex: str
    bodyweight_kg: float
    height_m: float | None
    # measured lengths (meters in analysis units; stature-units if unscaled)
    lengths: dict
    ratios: dict           # femur:shank, trunk:femur, etc. for normalization
    segments: dict         # name -> SegmentParams (bilateral where noted)

    def expected_trunk_lean(self) -> float:
        """Expected bottom-of-squat trunk inclination (deg from vertical).

        Longer femur relative to trunk forces more forward lean to keep the
        bar over midfoot. Fit is a pragmatic linearization of published
        squat-kinematics relationships, NOT a population average.
        """
        r = self.ratios.get("femur_to_trunk", 0.8)
        return float(np.clip(18.0 + 38.0 * (r - 0.55), 10.0, 55.0))


def build_anthropometry(
    pre,
    bodyweight_kg: float,
    height_m: float | None,
    sex: str = "male",
) -> Anthropometry:
    """Measure segment lengths at the calibration frame + scale de Leva table."""
    f = pre.calib_frame
    P = pre.positions

    def seg(a, b):
        return float(np.linalg.norm(P[a][f] - P[b][f]))

    lengths = {
        "thigh": seg("hip", "knee"),
        "shank": seg("knee", "ankle"),
        "trunk": seg("hip", "shoulder"),
        "foot": seg("heel", "foot_index"),
        "upper_arm": seg("shoulder", "elbow"),
        "forearm_hand": seg("elbow", "wrist"),
    }

    femur = max(lengths["thigh"], 1e-6)
    trunk = max(lengths["trunk"], 1e-6)
    shank = max(lengths["shank"], 1e-6)
    ratios = {
        "femur_to_shank": femur / shank,
        "femur_to_trunk": femur / trunk,
        "trunk_to_height": trunk / (pre.stature_px / (pre.px_per_m or pre.stature_px)),
    }

    table = DE_LEVA.get(sex, DE_LEVA["male"])
    # 2-D sagittal model segments. Bilateral segments (legs) carry both limbs'
    # mass since the visible leg represents a symmetric pair.
    segments = {
        "foot": SegmentParams(
            "foot", lengths["foot"], 2 * table["foot"][0] * bodyweight_kg,
            table["foot"][1],
            2 * table["foot"][0] * bodyweight_kg * (table["foot"][2] * lengths["foot"]) ** 2,
        ),
        "shank": SegmentParams(
            "shank", lengths["shank"], 2 * table["shank"][0] * bodyweight_kg,
            table["shank"][1],
            2 * table["shank"][0] * bodyweight_kg * (table["shank"][2] * lengths["shank"]) ** 2,
        ),
        "thigh": SegmentParams(
            "thigh", lengths["thigh"], 2 * table["thigh"][0] * bodyweight_kg,
            table["thigh"][1],
            2 * table["thigh"][0] * bodyweight_kg * (table["thigh"][2] * lengths["thigh"]) ** 2,
        ),
        "hat": SegmentParams(
            "hat", lengths["trunk"],
            hat_mass_fraction(sex) * bodyweight_kg,
            0.5,
            hat_mass_fraction(sex) * bodyweight_kg * (0.33 * lengths["trunk"]) ** 2,
        ),
    }

    return Anthropometry(
        sex=sex,
        bodyweight_kg=bodyweight_kg,
        height_m=height_m,
        lengths=lengths,
        ratios=ratios,
        segments=segments,
    )
