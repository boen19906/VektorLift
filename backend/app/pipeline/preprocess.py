"""
Preprocessing: normalized landmarks -> metric, smoothed, oriented time series.

Coordinate frame used by every downstream module:

    origin  : midfoot position in the standing-calibration frame
    +x      : direction the lifter faces (sagittal forward)
    +y      : up, floor at y ~= 0
    units   : meters, seconds

If the user height is known we get an absolute metric scale by measuring the
ankle->eye distance in the calibration frame (eye height ~= 0.936 * stature).
When a 450 mm plate is detected by barbell.py that scale wins instead; this
module exposes `set_scale_from_plate` for that override.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.signal import savgol_filter

from .pose import RawPoseSeries, LANDMARK_INDEX

# Landmarks that must be tracked for analysis to be meaningful.
KEY_LANDMARKS = ("shoulder", "hip", "knee", "ankle", "heel", "foot_index", "wrist")

EYE_HEIGHT_FRACTION = 0.936  # standing eye height as a fraction of stature
ANKLE_HEIGHT_FRACTION = 0.039  # ankle joint height above floor, frac of stature
MAX_GAP_S = 0.35  # interpolate tracking gaps up to this long
MIN_KEY_VIS = 0.5


class CalibrationError(Exception):
    """Raised when no usable upright/standing frame can be found."""


@dataclass
class PreprocessResult:
    fps: float
    t: np.ndarray                      # (N,) seconds
    side: str                          # 'left' | 'right'
    facing: int                        # +1 if lifter faces +x in image, else -1
    px_per_m: float | None             # None => no metric scale available
    positions: dict                    # name -> (N,2) meters in analysis frame
    velocities: dict                   # name -> (N,2) m/s
    positions_px: dict                 # name -> (N,2) raw pixels (for overlay)
    visibility: dict                   # name -> (N,) visibility 0..1
    key_visibility: np.ndarray         # (N,) min vis across KEY_LANDMARKS
    ground_y: float                    # floor height in analysis coords (~0)
    midfoot_x: np.ndarray              # (N,) midfoot center x, meters
    calib_frame: int                   # index of standing-calibration frame
    stature_px: float                  # measured pixel stature at calibration
    quality_ok: np.ndarray             # (N,) frames usable for math
    # analysis_px = diag(facing,-1) @ img_px - analysis_px_offset
    analysis_px_offset: np.ndarray = field(default_factory=lambda: np.zeros(2))
    shoulder_sep_frac: float = 0.0   # |near-far shoulder x| / stature
    camera_side_on: bool = True      # False => angled view, 2-D math degrades

    def pos(self, name: str) -> np.ndarray:
        return self.positions[name]

    def img_px_to_m(self, img_xy: np.ndarray) -> np.ndarray:
        """Convert raw image pixel coords -> analysis-frame meters."""
        faced = np.array([self.facing * img_xy[0], -img_xy[1]], dtype=np.float64)
        if self.px_per_m:
            return (faced - self.analysis_px_offset) / self.px_per_m
        return (faced - self.analysis_px_offset) / max(self.stature_px, 1.0)

    @property
    def n_frames(self) -> int:
        return len(self.t)


class Preprocessor:
    def __init__(self, height_m: float | None, min_vis: float = MIN_KEY_VIS):
        self.height_m = height_m
        self.min_vis = min_vis

    # -- public -------------------------------------------------------------

    def run(self, raw: RawPoseSeries) -> PreprocessResult:
        n = raw.x.shape[0]
        t = np.arange(n, dtype=np.float64) / raw.fps

        side = self._pick_side(raw)
        facing = self._pick_facing(raw, side)

        names = self._landmark_names_for(side)
        px = self._to_pixel_positions(raw, names)       # dict name -> (N,2) px
        vis = {name: raw.visibility[:, LANDMARK_INDEX[mp_name]]
               for name, mp_name in names.items()}
        px = self._fill_and_smooth(px, raw.fps, vis)

        calib_frame, stature_px, eye_name = self._calibrate(px, vis, raw, side)
        px_per_m = (
            stature_px / self.height_m if (self.height_m and stature_px > 0) else None
        )

        # analysis frame: x flipped to face-forward, y-up, origin at midfoot
        positions_px = {}
        positions = {}
        velocities = {}
        for name, p in px.items():
            p_faced = np.column_stack([facing * p[:, 0], -p[:, 1]])
            positions_px[name] = p_faced  # px units, y-up, facing+
            if px_per_m:
                positions[name] = p_faced / px_per_m
            else:
                positions[name] = p_faced / max(stature_px, 1.0)  # stature units

        # origin: midfoot at calibration frame (computed separately per unit)
        midfoot_cal = (
            positions["heel"][calib_frame] + positions["foot_index"][calib_frame]
        ) / 2.0
        midfoot_cal_px = (
            positions_px["heel"][calib_frame] + positions_px["foot_index"][calib_frame]
        ) / 2.0
        for name in positions:
            positions[name] = positions[name] - midfoot_cal
            positions_px[name] = positions_px[name] - midfoot_cal_px

        # floor: ankle joint sits ~4% of stature above the floor at standing
        ankle_h = ANKLE_HEIGHT_FRACTION * (self.height_m if px_per_m else 1.0)
        ground_y = positions["ankle"][calib_frame, 1] - ankle_h
        ground_y_px = (
            positions_px["ankle"][calib_frame, 1] - ankle_h * (px_per_m or 1.0)
        )
        for name in positions:
            positions[name][:, 1] -= ground_y
            positions_px[name][:, 1] -= ground_y_px
        ground_y_out = 0.0

        midfoot_x = (positions["heel"][:, 0] + positions["foot_index"][:, 0]) / 2.0

        win = self._savgol_window(raw.fps, n)
        for name in positions:
            velocities[name] = np.column_stack(
                [
                    savgol_filter(positions[name][:, 0], win, 3, deriv=1, delta=1 / raw.fps),
                    savgol_filter(positions[name][:, 1], win, 3, deriv=1, delta=1 / raw.fps),
                ]
            )

        key_vis = np.min(
            np.stack([vis[nm] for nm in KEY_LANDMARKS]), axis=0
        )
        quality_ok = key_vis >= self.min_vis

        # camera-angle estimate: in a true side view the near and far
        # shoulders project to nearly the same x; separation grows with
        # off-sagittal camera angle
        both = (vis["shoulder"] > self.min_vis) & (vis["shoulder_far"] > self.min_vis)
        if np.any(both):
            sep = np.abs(px["shoulder"][both, 0] - px["shoulder_far"][both, 0])
            sep_frac = float(np.median(sep) / max(stature_px, 1.0))
        else:
            sep_frac = 0.0
        camera_side_on = sep_frac < 0.10

        return PreprocessResult(
            fps=raw.fps,
            t=t,
            side=side,
            facing=facing,
            px_per_m=px_per_m,
            positions=positions,
            velocities=velocities,
            positions_px=positions_px,
            visibility=vis,
            key_visibility=key_vis,
            ground_y=ground_y_out,
            midfoot_x=midfoot_x,
            calib_frame=calib_frame,
            stature_px=stature_px,
            quality_ok=quality_ok,
            analysis_px_offset=midfoot_cal_px + np.array([0.0, ground_y_px]),
            shoulder_sep_frac=sep_frac,
            camera_side_on=camera_side_on,
        )

    # -- internals ------------------------------------------------------------

    @staticmethod
    def _pick_side(raw: RawPoseSeries) -> str:
        left = np.nanmean(
            raw.visibility[
                :, [LANDMARK_INDEX[f"left_{k}"] for k in ("shoulder", "hip", "knee", "ankle")]
            ]
        )
        right = np.nanmean(
            raw.visibility[
                :, [LANDMARK_INDEX[f"right_{k}"] for k in ("shoulder", "hip", "knee", "ankle")]
            ]
        )
        return "left" if left >= right else "right"

    def _pick_facing(self, raw: RawPoseSeries, side: str) -> int:
        """+1 when the lifter faces +x in image space, else -1."""
        toe = LANDMARK_INDEX[f"{side}_foot_index"]
        heel = LANDMARK_INDEX[f"{side}_heel"]
        vis = raw.visibility[:, toe] > self.min_vis
        diff = raw.x[vis, toe] - raw.x[vis, heel]
        diff = diff[np.isfinite(diff)]
        if len(diff) >= 10 and abs(np.median(diff)) > 1e-4:
            return 1 if np.median(diff) > 0 else -1
        nose = LANDMARK_INDEX["nose"]
        hip = LANDMARK_INDEX[f"{side}_hip"]
        d = raw.x[:, nose] - raw.x[:, hip]
        d = d[np.isfinite(d)]
        if len(d) and abs(np.median(d)) > 1e-4:
            return 1 if np.median(d) > 0 else -1
        return 1

    @staticmethod
    def _landmark_names_for(side: str) -> dict:
        """Map generic name -> mediaipipe name for the chosen body side."""
        names = {s: f"{side}_{s}" for s in (
            "shoulder", "elbow", "wrist", "hip", "knee", "ankle",
            "heel", "foot_index", "ear", "eye",
        )}
        names["nose"] = "nose"
        # far-side shoulder: its separation from the near shoulder tells us
        # whether the camera is truly side-on
        other = "right" if side == "left" else "left"
        names["shoulder_far"] = f"{other}_shoulder"
        return names

    @staticmethod
    def _to_pixel_positions(raw: RawPoseSeries, names: dict) -> dict:
        out = {}
        for generic, mp_name in names.items():
            i = LANDMARK_INDEX[mp_name]
            out[generic] = np.column_stack(
                [raw.x[:, i] * raw.width, raw.y[:, i] * raw.height]
            )
        return out

    def _fill_and_smooth(self, px: dict, fps: float, vis: dict) -> dict:
        """Interpolate short dropouts and Savitzky-Golay smooth each series."""
        n = next(iter(px.values())).shape[0]
        win = self._savgol_window(fps, n)
        max_gap = int(MAX_GAP_S * fps)
        out = {}
        for name, p in px.items():
            q = p.copy()
            bad = vis[name] < 0.3
            q[bad] = np.nan
            for axis in range(2):
                q[:, axis] = self._interp_gaps(q[:, axis], max_gap)
                if np.isfinite(q[:, axis]).sum() >= win:
                    q[:, axis] = savgol_filter(q[:, axis], win, 3)
            out[name] = q
        return out

    @staticmethod
    def _interp_gaps(y: np.ndarray, max_gap: int) -> np.ndarray:
        idx = np.arange(len(y))
        good = np.isfinite(y)
        if good.sum() < 2:
            return y
        # find runs of NaN; only interpolate runs <= max_gap
        y = y.copy()
        isnan = ~good
        i = 0
        while i < len(y):
            if isnan[i]:
                j = i
                while j < len(y) and isnan[j]:
                    j += 1
                if j - i <= max_gap:
                    y[i:j] = np.interp(idx[i:j], idx[good], y[good])
                i = j
            else:
                i += 1
        # fill edges with nearest valid
        y[~np.isfinite(y)] = np.interp(idx[~np.isfinite(y)], idx[good], y[good])
        return y

    @staticmethod
    def _savgol_window(fps: float, n: int) -> int:
        win = int(round(0.12 * fps))
        win = max(5, win | 1)  # odd, >=5
        if win >= n:
            win = n - 1 if (n - 1) % 2 else n - 2
        return max(5, win)

    def _calibrate(self, px: dict, vis: dict, raw: RawPoseSeries, side: str):
        """Find the most 'standing upright' frame and measure pixel stature."""
        n = raw.x.shape[0]
        shoulder, hip = px["shoulder"], px["hip"]
        knee, ankle = px["knee"], px["ankle"]

        # knee extension: straightness of hip-knee-ankle
        thigh = hip - knee
        shank = ankle - knee
        cos_knee = np.einsum("ij,ij->i", thigh, shank) / (
            np.linalg.norm(thigh, axis=1) * np.linalg.norm(shank, axis=1) + 1e-9
        )
        # interior angle ~180 when straight -> cos ~ -1 with these vectors
        knee_straight = (-cos_knee + 1) / 2  # 1 = perfectly straight

        # trunk verticality
        trunk = shoulder - hip
        trunk_vert = np.abs(trunk[:, 1]) / (np.linalg.norm(trunk, axis=1) + 1e-9)

        hip_height = -hip[:, 1]  # y-down px: higher hip = more negative y
        hip_height = (hip_height - np.nanmin(hip_height)) / (
            np.nanmax(hip_height) - np.nanmin(hip_height) + 1e-9
        )

        # prefer still frames: penalize hip speed so calibration lands on a
        # truly static standing moment, not a between-reps transition
        hip_speed = np.linalg.norm(np.gradient(hip, axis=0), axis=1)
        hip_speed /= np.percentile(hip_speed, 90) + 1e-9
        stillness = 1.0 / (1.0 + hip_speed)

        key = np.min(np.stack([vis[k] for k in ("shoulder", "hip", "knee", "ankle")]), axis=0)
        valid = key >= self.min_vis
        score = np.where(
            valid,
            (0.35 * knee_straight + 0.25 * trunk_vert + 0.2 * hip_height)
            * stillness,
            -1,
        )

        calib = int(np.argmax(score))
        if score[calib] <= 0:
            raise CalibrationError(
                "No frame with a clearly visible upright posture found. "
                "Include a moment standing still before the first rep."
            )

        eye = px.get("eye")
        ear = px.get("ear")
        eye_name = "eye"
        head_pt = eye
        if eye is None or vis["eye"][calib] < self.min_vis:
            head_pt = ear
            eye_name = "ear"
        if head_pt is None or vis.get(eye_name, np.zeros(n))[calib] < self.min_vis:
            head_pt = px["nose"]
            eye_name = "nose"

        eye_ankle_px = abs(head_pt[calib, 1] - ankle[calib, 1])
        stature_px = eye_ankle_px / EYE_HEIGHT_FRACTION
        return calib, float(stature_px), eye_name
