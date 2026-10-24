# VektorLift — Implementation Plan

Computer-vision coaching for the barbell squat and deadlift, filmed from the side.
Upload a video → get an annotated video back plus a per-rep biomechanics report and
prioritized, injury-focused coaching cues.

## Differentiators (the math that matters)

1. **Anthropometric normalization** — limb segment lengths are measured from the
   video during a standing calibration phase; body segment masses/COMs come from
   de Leva (1996) tables scaled to the user's bodyweight/height/sex. All angles,
   moment arms, and fault thresholds are normalized to the individual's segment
   ratios (e.g. expected squat trunk lean scales with femur:torso ratio), so the
   app does not judge a long-femured lifter against an average-limbed ideal.
2. **Velocity-based fatigue (VBT)** — barbell velocity is tracked through each
   concentric phase; mean concentric velocity (MCV), velocity loss % vs. the
   best rep, and rep-duration drift quantify fatigue. Classic thresholds
   (10% / 20% / 30% velocity loss) drive "stop the set" guidance.
3. **Joint torque / inverse statics** — a 2-D sagittal-plane rigid-link model
   (foot, shank, thigh, trunk+head, arms) with de Leva segment inertial
   parameters. Ground reaction force is estimated from whole-system
   Σm(g + a); net joint moments are propagated distal→proximal
   (ankle → knee → hip → L5/S1) via D'Alembert. Produces knee/hip extensor
   moment curves, a hip:knee torque ratio (knee- vs hip-dominant strategy),
   and a lumbar shear stress index.

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Pose estimation | MediaPipe Pose Landmarker (`mediapipe` pip, VIDEO mode, 33 landmarks) | Runs CPU-fine on single-person side view; installs on Python 3.14/Windows |
| Video decode | OpenCV (`opencv-python`) | Frame extraction, drawing |
| Video encode | `imageio-ffmpeg` | Bundled ffmpeg binary → H.264 annotated output, no system install |
| Math | NumPy, SciPy (Savitzky–Golay smoothing, peak finding, finite differences) | |
| API | FastAPI + Uvicorn, Pydantic schemas | Upload endpoint, job status, report JSON, media streaming |
| Job store | Filesystem (`data/jobs/<id>/` with `job.json`) | Zero-infra MVP; swap for SQLite/S3 later |
| Processing | `concurrent.futures` worker inside the API process | No Celery/Redis needed at this scale |
| Frontend | React 18 + Vite + TypeScript + Tailwind v4, Recharts | Upload form → live job polling → report dashboard with annotated video |
| Tests | pytest with synthetic landmark trajectories | Math pipeline is deterministic and unit-testable without video |

## Architecture

```
video.mp4 ──► backend/app/pipeline
               ├─ pose.py          MediaPipe → (frame, 33 landmarks, visibility)
               ├─ preprocess.py    px coords, occlusion filtering, Sav-Gol smooth,
               │                   side-of-body detect, standing calibration,
               │                   px→m scale (height OR 450mm plate detection)
               ├─ barbell.py       plate circle/blob tracking; fallback proxies
               │                   (wrist mid for DL, shoulder mid for back squat)
               ├─ anthropometry.py segment lengths from calibration; de Leva tables
               ├─ kinematics.py    joint-angle time series; rep segmentation;
               │                   events (descent/bottom/ascent/liftoff/lockout)
               ├─ dynamics.py      GRF estimate + distal→proximal inverse statics
               │                   → ankle/knee/hip/L5S1 net moments
               ├─ fatigue.py       per-rep MCV, velocity loss %, fatigue index
               ├─ rules.py         lift-specific fault rules → ranked findings
               ├─ annotate.py      skeleton + angle arcs + bar path + warnings → mp4
               └─ report.py        aggregates everything → report.json
                          │
        FastAPI  ──►  frontend (React): upload → poll → report UI
```

## Faults detected (side-view-feasible only)

**Squat:** insufficient depth (hip crease vs knee, normalized), excessive
forward lean vs. anthropometric expectation, butt wink (pelvis/torso angle
break in bottom third), good-morning ascent (hip rise rate >> bar rise rate),
bar path drift off midfoot, heel lift, valgus excluded (needs frontal view).

**Deadlift:** lumbar flexion at liftoff (trunk angle deviation from setup
baseline), hips shooting up before bar leaves floor, bar drifting away from
body, hitching at knees, over-lean-back at lockout.

## Phases

- **P0 — Scaffold:** repo layout, `requirements.txt`, FastAPI health endpoint, Vite app.
- **P1 — Pose pipeline:** `pose.py` (MediaPipe VIDEO mode, model complexity 2), `preprocess.py` (normalized→px, visibility gating, One-Euro/Sav-Gol smoothing, left/right side selection, calibration frame detection, px→m scale). Unit-tested on synthetic landmarks.
- **P2 — Kinematics:** angle extraction, rep segmentation (hip-y hysteresis for squat; bar/wrist-y for deadlift), event detection, per-rep ROM/depth/tempo. Synthetic-trajectory tests.
- **P3 — Anthropometry + dynamics:** de Leva table, segment COM/inertia, GRF estimate, distal→proximal moment propagation, hip:knee moment ratio, lumbar shear index. Validation: static squat hold reproduces textbook torque ordering; zero-moment sanity at lockout.
- **P4 — Fatigue:** bar tracking + proxies, concentric phase velocity, velocity-loss curve, per-rep fatigue flagging.
- **P5 — Rule engine:** declarative rules `(condition, evidence, severity, cue, drill)` over the per-rep feature dict; dedupe + rank; every cue carries the measured number that triggered it.
- **P6 — Output:** `annotate.py` overlay renderer (skeleton, knee/hip angle arcs, bar trace, phase banner, live warnings), `report.json`, API (`POST /api/analyze`, `GET /api/jobs/{id}`, `/result`, `/video`), job worker.
- **P7 — Frontend:** upload form (lift type, load, bodyweight, height, sex, facing), polling status, report view: annotated video player, rep table, velocity-loss chart, torque chart, ranked cue list.
- **P8 — Hardening:** pytest suite, error states (non-side angle, occluded bar, too-short clip), README run instructions.

## Known limitations (documented to user)

- Side view only; frontal-plane faults (knee valgus, asymmetry) are out of scope.
- Torques are *net joint moments with estimated GRF/midfoot COP* — valid for
  comparisons across reps/lifters, not a force-plate replacement.
- Bar tracking falls back to body-proxies when plates aren't resolvable.
