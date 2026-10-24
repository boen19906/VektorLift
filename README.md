# VektorLift

Computer-vision coaching for the barbell **squat** and **deadlift**, filmed
from the side. Upload a clip → get back an annotated video plus a per-rep
biomechanics report and ranked, injury-focused coaching cues.

See `IMPLEMENTATION_PLAN.md` for the architecture and math design.

## Features

- **Pose tracking** — MediaPipe Pose Landmarker (33 landmarks, video mode)
- **Metric calibration** — px→m from your height, or automatically from a
  detected 450 mm plate
- **Anthropometric normalization** — your segment lengths measured from the
  video; de Leva (1996) mass/inertia tables scaled to your bodyweight; fault
  thresholds adapt to your proportions (e.g. expected trunk lean scales with
  femur:torso ratio)
- **Inverse statics** — sagittal rigid-link model; estimated GRF +
  distal→proximal joint moments at ankle / knee / hip / L5-S1, reported
  absolute and N·m/kg
- **Velocity-based fatigue** — mean concentric velocity per rep, velocity
  loss %, standard VBT fatigue bands
- **Rule engine** — evidence-backed findings: every cue shows the measured
  number that triggered it, ranked by injury risk
- **Annotated video** — skeleton, joint angles, bar path, phase banner,
  torque readout, live warnings (H.264)

## Requirements

- Python 3.11+ (built/tested on 3.14, Windows)
- Node 18+

No system ffmpeg needed (`imageio-ffmpeg` bundles it). The MediaPipe pose
model (~5 MB) downloads once on first analysis.

## Run

Backend (from `backend/`):

```bash
pip install -r requirements.txt
uvicorn app.main:app --port 8000
```

Frontend (from `frontend/`):

```bash
npm install
npm run dev        # http://localhost:5173, proxies /api -> :8000
```

## Use

1. Film the lift **square from the side**, full body in frame, standing
   upright briefly before the first rep. Plates facing the camera improve
   scale + bar tracking.
2. Upload, pick squat/deadlift, enter bar load, bodyweight, height, sex.
3. Get the annotated video + report: per-rep metrics, velocity-loss chart,
   joint-moment curves, and ranked coaching cues.

## Tests

```bash
cd backend && python -m pytest tests -q
```

The suite runs the full math stack on synthetic forward-kinematics
trajectories — no video or model download required.

## Limitations

- Side view only. Frontal-plane faults (knee valgus, left/right asymmetry)
  are out of scope; the app detects and warns on angled camera views.
- Joint moments are estimates (estimated GRF, midfoot COP) — valid for
  comparisons and fault detection, not a force-plate replacement.
- Falls back to body-proxy bar tracking when plates can't be resolved.
