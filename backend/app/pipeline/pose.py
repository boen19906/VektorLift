"""
MediaPipe pose extraction.

Runs BlazePose (Pose Landmarker) in VIDEO mode over decoded frames and returns a
dense time series of 33 landmarks per frame. Everything downstream of this file
works on plain numpy arrays, so it can be unit-tested without a camera or model.

Coordinates are kept in normalized image space here (x right, y down, 0..1).
Conversion to a metric, y-up frame happens in preprocess.py once the camera
scale is known.
"""
from __future__ import annotations

import os
import urllib.request
from dataclasses import dataclass

import cv2
import numpy as np


class PoseExtractionError(Exception):
    """Raised when pose extraction fails outright (unreadable video, no person)."""


# MediaPipe Pose landmark indices. We keep a name table rather than relying on
# numeric indices scattered through the math code.
LANDMARK_NAMES = [
    "nose",
    "left_eye_inner", "left_eye", "left_eye_outer",
    "right_eye_inner", "right_eye", "right_eye_outer",
    "left_ear", "right_ear",
    "left_mouth", "right_mouth",
    "left_shoulder", "right_shoulder",
    "left_elbow", "right_elbow",
    "left_wrist", "right_wrist",
    "left_pinky", "right_pinky",
    "left_index", "right_index",
    "left_thumb", "right_thumb",
    "left_hip", "right_hip",
    "left_knee", "right_knee",
    "left_ankle", "right_ankle",
    "left_heel", "right_heel",
    "left_foot_index", "right_foot_index",
]
LANDMARK_INDEX = {name: i for i, name in enumerate(LANDMARK_NAMES)}

# Skeleton edges used both for drawing and for graph-based geometry.
SKELETON_EDGES = [
    ("shoulder", "elbow"), ("elbow", "wrist"),
    ("shoulder", "hip"), ("hip", "knee"), ("knee", "ankle"),
    ("ankle", "heel"), ("heel", "foot_index"), ("ankle", "foot_index"),
]

# Pose Landmarker runs on a bundled task model. MediaPipe does not ship the
# .task file inside the wheel, so we fetch it once and cache it next to the
# package. The 'full' model is the right accuracy/speed point for offline
# analysis of single-person clips.
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_full/float16/latest/pose_landmarker_full.task"
)
MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "models")
MODEL_PATH = os.path.abspath(os.path.join(MODEL_DIR, "pose_landmarker_full.task"))


def _ensure_model() -> str:
    if os.path.exists(MODEL_PATH):
        return MODEL_PATH
    os.makedirs(MODEL_DIR, exist_ok=True)
    try:
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    except Exception as exc:  # noqa: BLE001 - surface as domain error
        raise PoseExtractionError(
            f"Could not download pose model from {MODEL_URL}: {exc}"
        ) from exc
    return MODEL_PATH


@dataclass
class RawPoseSeries:
    """Per-frame landmark output in normalized image coordinates."""

    fps: float
    width: int
    height: int
    # (num_frames, 33) arrays
    x: np.ndarray
    y: np.ndarray
    visibility: np.ndarray
    frame_indices: np.ndarray  # original frame numbers (in case of skips)


def extract_landmarks(
    video_path: str,
    progress_cb=None,
    min_detection_confidence: float = 0.5,
    min_tracking_confidence: float = 0.5,
) -> RawPoseSeries:
    """Run MediaPipe over a video file and return the dense landmark series.

    progress_cb, if given, is called with a float in [0, 1].
    Raises PoseExtractionError when the video can't be read or no person is
    ever detected.
    """
    try:
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision as mp_vision
    except Exception as exc:  # noqa: BLE001
        raise PoseExtractionError(f"mediapipe import failed: {exc}") from exc

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise PoseExtractionError(f"Cannot open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0

    options = mp_vision.PoseLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=_ensure_model()),
        running_mode=mp_vision.RunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=min_detection_confidence,
        min_pose_presence_confidence=min_detection_confidence,
        min_tracking_confidence=min_tracking_confidence,
        output_segmentation_masks=False,
    )

    xs, ys, vis, idxs = [], [], [], []
    ever_detected = False
    frame_i = 0
    with mp_vision.PoseLandmarker.create_from_options(options) as landmarker:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            ts_ms = int(frame_i * 1000.0 / fps)
            mp_image = mp.Image(
                image_format=mp.ImageFormat.SRGB,
                data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB),
            )
            result = landmarker.detect_for_video(mp_image, ts_ms)
            if result.pose_landmarks:
                lm = result.pose_landmarks[0]
                ever_detected = True
                xs.append([p.x for p in lm])
                ys.append([p.y for p in lm])
                vis.append([p.visibility for p in lm])
            else:
                xs.append([np.nan] * 33)
                ys.append([np.nan] * 33)
                vis.append([0.0] * 33)
            idxs.append(frame_i)
            if progress_cb and total:
                progress_cb(0.05 + 0.55 * frame_i / max(total, 1))
            frame_i += 1
    cap.release()

    if frame_i == 0:
        raise PoseExtractionError("Video has no decodable frames.")
    if not ever_detected:
        raise PoseExtractionError(
            "No person detected in any frame. Use a side-angle clip of a "
            "single lifter with the full body visible."
        )

    return RawPoseSeries(
        fps=fps,
        width=width,
        height=height,
        x=np.asarray(xs, dtype=np.float64),
        y=np.asarray(ys, dtype=np.float64),
        visibility=np.asarray(vis, dtype=np.float64),
        frame_indices=np.asarray(idxs, dtype=np.int64),
    )
