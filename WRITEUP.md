# VektorLift

**An AI strength coach that measures your squat and deadlift — then tells you exactly what to fix to lift safer and stronger.**

VektorLift turns any side-angle video of a barbell squat or deadlift into a full biomechanical report. Upload a clip and it tracks your skeleton frame-by-frame, reconstructs your segment lengths, estimates joint torques and bar velocity, flags injury-risk patterns (with the body part at risk), and returns a coached report plus an annotated video — all from a phone camera, no sensors or wearables required.

---

## What it does, end to end

1. **Upload** a side-view video of a squat or deadlift set, along with optional metadata (bar load, bodyweight, height, sex).
2. **Pose extraction** — MediaPipe Pose Landmarker produces a 33-point skeleton for every frame.
3. **Normalization** — the pipeline detects which way you're facing, picks the camera-side limbs, smooths the trajectories, and locates a standing "calibration" frame to measure your body proportions and establish a pixel→meter scale (validated against detected plate diameter when a barbell is visible).
4. **Kinematics** — joint angles (knee, hip, trunk), bar path, segmenting the set into individual reps with start/bottom/lockout events.
5. **Biomechanics** — anthropometric-normalized inverse statics: estimated ground reaction force propagated ankle → knee → hip → L5/S1 for net joint moments, in absolute N·m and N·m/kg.
6. **Fatigue** — velocity-based training metrics: mean concentric velocity per rep and set velocity-loss percentage with standard fatigue bands.
7. **Coaching** — a rule engine evaluates ~15 fault patterns (depth, butt wink, good-morning collapse, heel lift, bar drift, hips-shooting-up, hitching, lockout lean-back, excessive fatigue, knee/hip dominance asymmetry) and emits ranked findings with a specific cue and a drill to fix each.
8. **Report** — a Strava-style dashboard: activity header with headline stats, injury risks first (tagged with the anatomy at risk), what's working, coaching cues with measured evidence, contextualized charts, per-rep detail, and the annotated video showing skeleton, bar path, live velocity, and joint torques.

## The three differentiators

- **Anthropometric normalization** — thresholds aren't one-size-fits-all. Segment lengths are measured from your video; de Leva (1996) mass/inertia parameters are scaled to your bodyweight and sex; the "expected" trunk lean at squat bottom is computed from your femur:trunk ratio. A long-femured lifter is judged against their own levers, not an idealized body.
- **Velocity-based fatigue** — every rep gets a mean concentric velocity; the set gets a velocity-loss percentage and a band (fresh → accumulating → high → excessive). This catches a real coaching signal — grinding past productive reps — that pure joint-angle analysis misses.
- **Joint torque / inverse statics** — a sagittal rigid-link model (foot, shank, thigh, HAT + bar point mass) estimates GRF via D'Alembert and propagates net moments distal→proximal through ankle, knee, hip, and L5/S1. Honest framing: it's an estimate for rep-to-rep comparison and fault detection, not a force plate.

## Tech stack

| Layer | Tech |
|---|---|
| Backend | Python, FastAPI, NumPy, SciPy, OpenCV, MediaPipe Pose Landmarker, imageio-ffmpeg (bundled x264) |
| Frontend | React, Vite, TypeScript, Tailwind CSS v4, Recharts |
| Processing | Async in-process job queue with progress polling; per-job artifacts on disk |
| Testing | pytest — 16 tests driving the real math stack on synthetic forward-kinematics lifter trajectories |

## Major features

- **Computer-vision pipeline** — pose tracking with visibility-aware quality gates, gap interpolation, Savitzky-Golay smoothing, facing-direction normalization, and camera-angle quality detection (warns when footage isn't truly side-on).
- **Bar tracking** — Hough-circle plate detection that doubles as a metric scale reference, with sanity checks (plate must be plate-sized in meters, stay near the body-proxy path, skipped entirely for unloaded lifts) and shoulder/wrist proxy fallback.
- **Rep segmentation** — event detection with physiological plausibility filtering (rejects impossible rep durations/ROMs produced by tracking noise).
- **Injury-risk framing** — severity-3 findings surface first, each tagged with the anatomy under load (lumbar spine, knees, ankles…); tracking-suspect reps are flagged rather than trusted.
- **Product UX** — upload → live progress → feed-style report; job persistence across reloads, recent-analyses history, self-healing connection handling, and a compact letterboxed video player.

## Engineering rigor (the unglamorous part that makes it work)

Real gym footage is hostile: MediaPipe reports low per-landmark visibility on usable tracking, plate detectors hallucinate circles on plates that don't exist, and 45° camera angles produce impossible joint angles. The pipeline handles this with visibility statistics over load-bearing joints only, plate-vs-proxy scale agreement checks, impossible-angle flags, and physiological rep filtering — all verified end-to-end on real uploaded videos, not just synthetic data.

## Honest limitations

- Side view only — knee valgus and left/right asymmetry require a frontal camera.
- Torques are estimates (midfoot COP assumption + estimated GRF) — useful for comparison and fault-finding, not clinical measurement.
- Landmark noise on rear-quarter views can produce suspect reps; these are flagged rather than silently trusted.

## Repository

- `backend/app/pipeline/` — pose, preprocess, anthropometry, kinematics, barbell, dynamics, fatigue, rules, annotate, report, run
- `frontend/src/` — upload form, report dashboard, API client
- `backend/tests/` — 16 tests on synthetic kinematics
- `IMPLEMENTATION_PLAN.md` — the original design doc
