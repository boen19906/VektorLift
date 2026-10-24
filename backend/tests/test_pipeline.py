import numpy as np
import pytest

from app.pipeline import (
    Preprocessor, BarbellTracker, build_anthropometry, compute_kinematics,
    compute_dynamics, compute_fatigue, evaluate_rules, build_report,
)
from conftest import make_series, squat_frame, deadlift_frame, PPM

HEIGHT_M = 1.80


def _run_stack(lift, pose_fn, **kw):
    raw = make_series(pose_fn, **kw)
    pre = Preprocessor(height_m=HEIGHT_M).run(raw)
    bar = BarbellTracker(lift).track(pre, video_path=None)
    anthro = build_anthropometry(pre, bodyweight_kg=85.0, height_m=HEIGHT_M)
    kin = compute_kinematics(pre, bar.pos, lift)
    return pre, bar, anthro, kin, raw


# ---------------------------------------------------------------------------
# preprocessing / calibration
# ---------------------------------------------------------------------------

class TestPreprocess:
    def test_scale_from_height(self):
        raw = make_series(squat_frame)
        pre = Preprocessor(height_m=HEIGHT_M).run(raw)
        assert pre.px_per_m == pytest.approx(PPM, rel=0.08)

    def test_ground_and_standing(self):
        raw = make_series(squat_frame)
        pre = Preprocessor(height_m=HEIGHT_M).run(raw)
        # standing hip height ~0.95 m, floor ~0
        assert pre.positions["hip"][pre.calib_frame, 1] == pytest.approx(0.95, abs=0.08)
        assert pre.positions["ankle"][pre.calib_frame, 1] == pytest.approx(0.07, abs=0.03)

    def test_facing_flip(self):
        raw = make_series(squat_frame)
        pre = Preprocessor(height_m=HEIGHT_M).run(raw)
        assert pre.facing == 1  # toes point +x in the synthetic scene


# ---------------------------------------------------------------------------
# kinematics / segmentation
# ---------------------------------------------------------------------------

class TestKinematics:
    def test_squat_reps_detected(self):
        *_, kin, _raw = _run_stack("squat", squat_frame)
        assert len(kin.reps) == 2

    def test_squat_depth_below_parallel(self):
        *_, kin, _raw = _run_stack("squat", squat_frame)
        for rep in kin.reps:
            assert rep.metrics["depth_margin"] > 0.0  # hip below knee

    def test_knee_flexion_range(self):
        *_, kin, _raw = _run_stack("squat", squat_frame)
        for rep in kin.reps:
            assert rep.metrics["max_knee_flexion"] > 80

    def test_deadlift_reps_detected(self):
        *_, kin, _raw = _run_stack("deadlift", deadlift_frame)
        assert len(kin.reps) == 2

    def test_deadlift_bar_rises(self):
        *_, kin, _raw = _run_stack("deadlift", deadlift_frame)
        for rep in kin.reps:
            assert rep.metrics["bar_rise_early"] > 0


# ---------------------------------------------------------------------------
# anthropometry + dynamics
# ---------------------------------------------------------------------------

class TestDynamics:
    def test_segment_lengths_measured(self):
        pre, bar, anthro, kin, _ = _run_stack("squat", squat_frame)
        assert anthro.lengths["thigh"] == pytest.approx(0.49, abs=0.08)
        assert anthro.lengths["shank"] == pytest.approx(0.44, abs=0.08)

    def test_moments_finite_and_signed(self):
        pre, bar, anthro, kin, _ = _run_stack("squat", squat_frame)
        dyn = compute_dynamics(pre, anthro, kin, kin.bar_pos, bar_kg=100.0)
        for rep in kin.reps:
            sl = slice(rep.start, rep.end + 1)
            assert np.all(np.isfinite(dyn.moments["knee"][sl]))
            # extensor demand positive during loaded flexion
            assert np.max(dyn.moments["knee"][sl]) > 0
            assert np.max(np.abs(dyn.moments["hip"][sl])) > 0

    def test_heavier_bar_more_torque(self):
        pre, bar, anthro, kin, _ = _run_stack("squat", squat_frame)
        d0 = compute_dynamics(pre, anthro, kin, kin.bar_pos, bar_kg=0.0)
        d1 = compute_dynamics(pre, anthro, kin, kin.bar_pos, bar_kg=140.0)
        pk0 = max(p["hip_peak"] for p in d0.rep_peaks)
        pk1 = max(p["hip_peak"] for p in d1.rep_peaks)
        assert pk1 > pk0

    def test_grf_reasonable_at_stand(self):
        pre, bar, anthro, kin, _ = _run_stack("squat", squat_frame)
        dyn = compute_dynamics(pre, anthro, kin, kin.bar_pos, bar_kg=0.0)
        # during the static standing interval GRF ~ bodyweight * g
        grf_stand = np.median(dyn.grf[2:20, 1])
        assert grf_stand == pytest.approx(85 * 9.81, rel=0.25)


# ---------------------------------------------------------------------------
# fatigue
# ---------------------------------------------------------------------------

class TestFatigue:
    def test_slower_rep_shows_velocity_loss(self):
        # rep 2 deliberately slowed by stretching concentric time
        raw = make_series(squat_frame, reps=2)
        pre = Preprocessor(height_m=HEIGHT_M).run(raw)
        bar = BarbellTracker("squat").track(pre)
        anthro = build_anthropometry(pre, 85.0, HEIGHT_M)
        kin = compute_kinematics(pre, bar.pos, "squat")
        fat = compute_fatigue(pre, kin, metric_scale=True)
        assert len(fat.reps) == 2
        assert fat.best_mcv > 0
        assert fat.fatigue_band in ("fresh", "accumulating", "high", "excessive")


# ---------------------------------------------------------------------------
# rules + report
# ---------------------------------------------------------------------------

class TestRulesReport:
    def test_findings_sorted_and_serializable(self):
        pre, bar, anthro, kin, _ = _run_stack("squat", squat_frame)
        dyn = compute_dynamics(pre, anthro, kin, kin.bar_pos, bar_kg=100.0)
        fat = compute_fatigue(pre, kin, metric_scale=True)
        findings = evaluate_rules(kin, dyn, fat, anthro, pre)
        assert all(f.severity in (1, 2, 3) for f in findings)
        sevs = [f.severity for f in findings]
        assert sevs == sorted(sevs, reverse=True)

    def test_shallow_squat_flags_depth(self):
        shallow = lambda u: squat_frame(u, depth=0.35)  # noqa: E731
        pre, bar, anthro, kin, _ = _run_stack("squat", shallow)
        dyn = compute_dynamics(pre, anthro, kin, kin.bar_pos, 60.0)
        fat = compute_fatigue(pre, kin, True)
        findings = evaluate_rules(kin, dyn, fat, anthro, pre)
        assert any(f.rule == "squat_depth" for f in findings)

    def test_report_json(self):
        import json
        pre, bar, anthro, kin, _ = _run_stack("squat", squat_frame)
        dyn = compute_dynamics(pre, anthro, kin, kin.bar_pos, 100.0)
        fat = compute_fatigue(pre, kin, True)
        findings = evaluate_rules(kin, dyn, fat, anthro, pre)
        rep = build_report(
            meta={}, pre=pre, anthro=anthro, kin=kin, dyn=dyn, fat=fat,
            findings=findings, bar_method="proxy",
        )
        s = json.dumps(rep)  # must serialize
        assert '"reps"' in s and '"findings"' in s
