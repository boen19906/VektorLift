export interface AnalyzeMeta {
  lift_type: 'squat' | 'deadlift'
  load_kg: number
  bodyweight_kg: number
  height_m: number
  sex: 'male' | 'female'
}

export interface JobStatus {
  id: string
  status: 'queued' | 'running' | 'done' | 'error'
  progress: number
  error: string | null
}

export interface RepReport {
  index: number
  frames: { start: number; bottom: number; lockout: number; end: number }
  metrics: Record<string, number>
  velocity: {
    mcv: number; peak: number; v_loss_pct: number
    concentric_s: number; rom: number; flags: string[]
  } | null
  torque_peaks: Record<string, number | null> | null
}

export interface Finding {
  rule: string
  severity: 1 | 2 | 3
  title: string
  evidence: string
  cue: string
  drill: string
  body_part: string
  reps: number[]
  timestamp: number
}

export interface Report {
  meta: Record<string, unknown>
  lift_type: string
  side: string
  fps: number
  duration_s: number
  anthropometry: {
    lengths: Record<string, number>
    ratios: Record<string, number>
    expected_trunk_lean_deg: number
  }
  reps: RepReport[]
  fatigue: {
    best_mcv: number; set_v_loss_pct: number
    fatigue_band: string; units: string
  } | null
  findings: Finding[]
  series: {
    t: number[]; hip_y: number[]; bar_y: number[]; bar_x: number[]
    knee_flexion: number[]; hip_flexion: number[]
    trunk_inclination: number[]; bar_v: number[]
    knee_moment: number[]; hip_moment: number[]; l5s1_moment: number[]
  }
  quality: {
    key_visibility_mean: number
    frames_usable_pct: number
    bar_tracking: string
    metric_scale: boolean
    camera_side_on: boolean
    shoulder_sep_frac: number
  }
}
