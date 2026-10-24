"""
Barbell tracking.

Two modes:

1. ``plate`` — detect the outer plate circle with HoughCircles inside a
   search region around the expected bar location, then track it frame to
   frame. A detected plate also yields a metric scale (competition plates
   are 450 mm diameter) that overrides height-based calibration.
2. ``proxy`` — no detection needed. For a back squat the bar rides the upper
   back, so the shoulder joint tracks it well; for a deadlift the wrists
   track the bar (arms hang straight).

Plate detection is opportunistic: if fewer than MIN_DETECTION_FRAMES
consistent detections are found we silently fall back to the proxy.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

PLATE_DIAMETER_M = 0.450
MIN_DETECTION_FRAMES = 12
SAMPLE_EVERY = 5


@dataclass
class BarbellResult:
    pos: np.ndarray            # (N,2) bar position in analysis units
    method: str                # 'plate' | 'proxy'
    px_per_m_plate: float | None
    plate_r_px: float | None
    pos_px: np.ndarray | None  # (N,2) in positions_px space for overlay


class BarbellTracker:
    def __init__(self, lift_type: str):
        self.lift_type = lift_type

    # -- public -------------------------------------------------------------

    def track(self, pre, video_path: str | None = None,
              allow_plate: bool = True) -> BarbellResult:
        proxy = self._proxy(pre)
        if video_path is None or pre.px_per_m is None or not allow_plate:
            return BarbellResult(
                pos=proxy, method="proxy", px_per_m_plate=None,
                plate_r_px=None, pos_px=self._proxy_px(pre),
            )
        plate = self._detect_plate(video_path, pre)
        if plate is None:
            return BarbellResult(
                pos=proxy, method="proxy", px_per_m_plate=None,
                plate_r_px=None, pos_px=self._proxy_px(pre),
            )
        pos_px, r_px = plate
        pos_m = pos_px / pre.px_per_m  # positions_px space shares the origin
        return BarbellResult(
            pos=pos_m, method="plate",
            px_per_m_plate=(2 * r_px) / PLATE_DIAMETER_M,
            plate_r_px=r_px, pos_px=pos_px,
        )

    # -- proxy --------------------------------------------------------------

    def _proxy_name(self) -> str:
        return "shoulder" if self.lift_type == "squat" else "wrist"

    def _proxy(self, pre) -> np.ndarray:
        # Back squat: bar rides the upper back, shoulder joint tracks it well.
        # Deadlift: straight arms, wrist tracks the bar.
        return pre.positions[self._proxy_name()].copy()

    def _proxy_px(self, pre) -> np.ndarray:
        return pre.positions_px[self._proxy_name()].copy()

    # -- plate detection ------------------------------------------------------

    def _detect_plate(self, video_path: str, pre):
        """HoughCircles in an ROI around the proxy point. Returns
        (pos_px (N,2), r_px) in positions_px space, or None."""
        import cv2

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return None
        n = pre.n_frames
        proxy_img = self._analysis_px_to_img(pre, self._proxy_px(pre))

        detections = {}   # frame -> (x_img, y_img, r)
        radii = []
        frame_i = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if frame_i % SAMPLE_EVERY == 0 and frame_i < n:
                cx, cy = proxy_img[frame_i]
                roi = self._roi(frame, int(cx), int(cy), int(0.25 * pre.stature_px))
                if roi is not None:
                    x0, y0, crop = roi
                    det = self._hough(crop)
                    if det is not None:
                        dx, dy, r = det
                        detections[frame_i] = (x0 + dx, y0 + dy, r)
                        radii.append(r)
            frame_i += 1
        cap.release()

        if len(detections) < MIN_DETECTION_FRAMES:
            return None
        r_med = float(np.median(radii))
        # radius consistency + the plate must stay near the body-proxy path;
        # HoughCircles happily locks onto other round objects between reps
        proxy_px_img = proxy_img  # image coords per frame
        good = {}
        for f, (x, y, r) in detections.items():
            if not (0.7 * r_med < r < 1.4 * r_med):
                continue
            px, py = proxy_px_img[f]
            if np.hypot(x - px, y - py) > 0.30 * pre.stature_px:
                continue
            good[f] = (x, y, r)
        if len(good) < MIN_DETECTION_FRAMES:
            return None

        # the detected circle must actually be plate-sized: a 450 mm plate
        # under the height-based px/m scale. Rejects lamps, clocks, mats...
        if pre.px_per_m:
            r_m = (2 * r_med) / pre.px_per_m
            if not (0.30 < r_m < 0.60):
                return None

        # interpolate between detections, but blend back to the proxy when
        # the nearest detection is far in time (tracking lost / clip edges)
        frames = np.array(sorted(good))
        xs = np.array([good[f][0] for f in frames])
        ys = np.array([good[f][1] for f in frames])
        all_f = np.arange(min(n, len(proxy_img)))
        xi = np.interp(all_f, frames, xs)
        yi = np.interp(all_f, frames, ys)
        near = np.minimum(
            np.abs(all_f[:, None] - frames[None, :]).min(axis=1), 60
        )
        w = np.clip(1.0 - near / 60.0, 0.0, 1.0)
        w = np.convolve(w, np.ones(7) / 7, mode="same")
        xi = w * xi + (1 - w) * proxy_px_img[:, 0]
        yi = w * yi + (1 - w) * proxy_px_img[:, 1]
        faced = np.column_stack([pre.facing * xi, -yi])
        pos_px = faced - pre.analysis_px_offset
        return pos_px, r_med

    @staticmethod
    def _analysis_px_to_img(pre, pos_px: np.ndarray) -> np.ndarray:
        img = pos_px + pre.analysis_px_offset
        return np.column_stack([pre.facing * img[:, 0], -img[:, 1]])

    @staticmethod
    def _roi(frame, cx, cy, half):
        h, w = frame.shape[:2]
        x0, y0 = max(0, cx - half), max(0, cy - half)
        x1, y1 = min(w, cx + half), min(h, cy + half)
        if x1 - x0 < 40 or y1 - y0 < 40:
            return None
        return x0, y0, frame[y0:y1, x0:x1]

    @staticmethod
    def _hough(crop):
        import cv2

        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        gray = cv2.medianBlur(gray, 5)
        h = gray.shape[0]
        circles = cv2.HoughCircles(
            gray, cv2.HOUGH_GRADIENT, dp=1.2, minDist=h,
            param1=80, param2=30,
            minRadius=int(0.15 * h), maxRadius=int(0.6 * h),
        )
        if circles is None:
            return None
        x, y, r = circles[0][0]
        return float(x), float(y), float(r)
