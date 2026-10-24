import {
  Line, LineChart, CartesianGrid, XAxis, YAxis, Tooltip,
  ResponsiveContainer, BarChart, Bar, Legend,
} from 'recharts'
import type { Report as ReportT } from './types'
import { videoUrl } from './api'

const SEV = {
  3: { label: 'Injury risk', cls: 'border-red-800 bg-red-950/60 text-red-300' },
  2: { label: 'Form fault', cls: 'border-amber-800 bg-amber-950/60 text-amber-300' },
  1: { label: 'Efficiency', cls: 'border-sky-800 bg-sky-950/60 text-sky-300' },
} as const

/** Positives derived from metrics — shown when the matching fault did NOT fire. */
function computeGoods(r: ReportT): string[] {
  const g: string[] = []
  const reps = r.reps
  if (!reps.length) return g
  const m = (k: string) => reps.map(x => x.metrics[k]).filter(v => v != null)

  const depths = m('depth_margin')
  if (depths.length && depths.every(d => d > 0))
    g.push(`Hit full depth on all ${depths.length} rep${depths.length > 1 ? 's' : ''} — hip crease below the knee every time`)
  const wink = m('buttwink_deg')
  if (wink.length && wink.every(w => w <= 8))
    g.push('No pelvic tuck ("butt wink") detected at the bottom of any rep')
  const heels = m('heel_lift_max')
  if (heels.length && heels.every(h => h <= (r.quality.metric_scale ? 0.02 : 0.015)))
    g.push('Feet stayed planted — no heel lift through the set')
  if (r.fatigue && r.fatigue.set_v_loss_pct < 10 && reps.length > 1)
    g.push(`Consistent bar speed — only ${r.fatigue.set_v_loss_pct.toFixed(0)}% velocity loss across the set`)
  const ranges = m('bar_path_range_x')
  if (r.quality.bar_tracking === 'plate' && ranges.length && ranges.every(x => x < 0.08))
    g.push('Bar path stayed nearly vertical over midfoot — efficient line of pull')
  const flex = m('max_knee_flexion')
  if (r.lift_type === 'deadlift') {
    const ratios = m('hip_bar_rise_ratio')
    if (ratios.length && ratios.every(x => x <= 2))
      g.push('Hips and bar rose together off the floor — no stiff-legging')
    if (m('bar_reversals').every(x => x === 0))
      g.push('Smooth, hitch-free pull through the knee region')
  } else if (flex.length && flex.every(f => f < 160)) {
    // nothing extra — depth covered above
  }
  return g
}

function takeaway(r: ReportT, chart: 'angles' | 'moments'): string {
  const reps = r.reps
  if (!reps.length) return ''
  if (chart === 'angles') {
    const kf = Math.max(...reps.map(x => x.metrics.max_knee_flexion ?? 0))
    const ti = Math.max(...reps.map(x => x.metrics.trunk_incl_max ?? 0))
    return `Peak knee bend ${kf.toFixed(0)}° at the bottom; trunk leaned up to ${ti.toFixed(0)}° (expected ~${r.anthropometry.expected_trunk_lean_deg}° for your proportions).`
  }
  const kp = Math.max(...reps.map(x => Math.abs(x.torque_peaks?.knee_peak_norm ?? 0)))
  const hp = Math.max(...reps.map(x => Math.abs(x.torque_peaks?.hip_peak_norm ?? 0)))
  return `Peak demand: knee ${kp.toFixed(1)}, hip ${hp.toFixed(1)} N·m/kg. A hip:knee ratio far from ~1.5-2 means one joint is doing most of the work.`
}

export default function Report({ jobId, report }: { jobId: string; report: ReportT }) {
  const injury = report.findings.filter(f => f.severity === 3)
  const faults = report.findings.filter(f => f.severity < 3)
  const goods = computeGoods(report)
  const s = report.series

  const angleData = s.t.map((t, i) => ({
    t: +t.toFixed(2), knee: s.knee_flexion[i], hip: s.hip_flexion[i],
    trunk: s.trunk_inclination[i],
  }))
  const momentData = s.t.map((t, i) => ({
    t: +t.toFixed(2), knee: s.knee_moment[i], hip: s.hip_moment[i],
    l5s1: s.l5s1_moment[i],
  }))
  const velData = report.reps.map(r => ({
    rep: `R${r.index}`, mcv: r.velocity?.mcv ?? 0,
    loss: r.velocity?.v_loss_pct ?? 0,
  }))

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      {/* verdict row: video + overall assessment */}
      <div className="grid gap-6 lg:grid-cols-2">
        <div className="rounded-2xl border border-neutral-800 bg-neutral-900 p-4">
          <video
            src={videoUrl(jobId)} controls loop muted
            className="w-full rounded-xl bg-black"
          />
          <div className="mt-3 flex flex-wrap gap-2 text-xs text-neutral-400">
            <Chip>{report.lift_type} · {report.side} side</Chip>
            <Chip>{report.reps.length} reps</Chip>
            <Chip>bar: {report.quality.bar_tracking}</Chip>
            <Chip>{report.quality.frames_usable_pct}% frames usable</Chip>
            <Chip>{report.quality.metric_scale ? 'metric scale' : 'stature units'}</Chip>
          </div>
          {!report.quality.camera_side_on && (
            <p className="mt-3 rounded-lg border border-amber-800 bg-amber-950/50 px-3 py-2 text-xs text-amber-300">
              Camera looks angled rather than side-on (shoulder separation{' '}
              {(report.quality.shoulder_sep_frac * 100).toFixed(0)}% of stature).
              2-D joint angles and distances are approximate — re-film square
              to the lifter for precise numbers.
            </p>
          )}
        </div>

        <div className="space-y-4">
          <div className="rounded-2xl border border-neutral-800 bg-neutral-900 p-5">
            <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-neutral-400">
              Assessment
            </h3>
            <p className="text-sm leading-relaxed text-neutral-200">
              {report.reps.length} rep{report.reps.length !== 1 ? 's' : ''} analyzed.{' '}
              {injury.length > 0
                ? <span className="text-red-300">{injury.length} injury-risk pattern{injury.length !== 1 ? 's' : ''} need{injury.length === 1 ? 's' : ''} attention first. </span> : null}
              {faults.length > 0
                ? <span className="text-amber-300">{faults.length} fixable form issue{faults.length !== 1 ? 's' : ''}. </span> : null}
              {injury.length === 0 && faults.length === 0
                ? <span className="text-emerald-300">Clean set — no faults detected. </span> : null}
              {goods.length > 0
                ? <span className="text-emerald-300">{goods.length} thing{goods.length !== 1 ? 's' : ''} looking good.</span> : null}
            </p>
          </div>

          {report.fatigue && (
            <div className="rounded-2xl border border-neutral-800 bg-neutral-900 p-4">
              <h3 className="mb-1 text-sm font-semibold uppercase tracking-wide text-neutral-400">
                Fatigue / bar speed
              </h3>
              <p className="mb-3 text-xs text-neutral-500">
                Mean concentric velocity (MCV) is how fast the bar moved up on
                the way out of the bottom. Velocity loss compares each rep to
                your fastest — under 10% is fresh, 20%+ means you're past the
                productive part of the set.
              </p>
              <div className="flex items-baseline gap-6">
                <Stat label="best rep speed" value={`${report.fatigue.best_mcv.toFixed(2)} ${report.fatigue.units}`}
                  hint="fastest rep of the set" />
                <Stat label="velocity loss" value={`${report.fatigue.set_v_loss_pct.toFixed(0)}%`}
                  hint="first → last rep drop" />
                <Stat label="set status" value={report.fatigue.fatigue_band}
                  hint="fresh / accumulating / high / excessive" />
              </div>
              <div className="mt-3 h-40">
                <ResponsiveContainer>
                  <BarChart data={velData}>
                    <CartesianGrid stroke="#262626" />
                    <XAxis dataKey="rep" stroke="#737373" fontSize={11} />
                    <YAxis yAxisId="l" stroke="#737373" fontSize={11} />
                    <YAxis yAxisId="r" orientation="right" stroke="#737373" fontSize={11} unit="%" />
                    <Tooltip contentStyle={{ background: '#171717', border: '1px solid #333' }} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Bar yAxisId="l" dataKey="mcv" name="rep speed" fill="#34d399" />
                    <Bar yAxisId="r" dataKey="loss" name="velocity loss %" fill="#f87171" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <p className="mt-2 text-xs text-neutral-500">
                Green bars are rep speed — you want them roughly level. Red
                bars are how much slower each rep was vs your best; a rising
                red trend = accumulating fatigue.
              </p>
            </div>
          )}

          <div className="rounded-2xl border border-neutral-800 bg-neutral-900 p-4">
            <h3 className="mb-1 text-sm font-semibold uppercase tracking-wide text-neutral-400">
              Your proportions
            </h3>
            <p className="mb-3 text-xs text-neutral-500">
              Segment lengths measured from the video. The femur:trunk ratio
              sets how much forward lean is mechanically expected — the app
              judges your torso angle against <em>your</em> build, not an ideal.
            </p>
            <div className="grid grid-cols-3 gap-3 text-sm">
              {Object.entries(report.anthropometry.lengths).map(([k, v]) => (
                <Stat key={k} label={k} value={`${(v * 100).toFixed(0)} cm`} />
              ))}
              <Stat label="femur:trunk" value={report.anthropometry.ratios.femur_to_trunk?.toFixed(2) ?? '—'}
                hint="higher = more lean expected" />
              <Stat label="expected lean" value={`${report.anthropometry.expected_trunk_lean_deg}°`}
                hint="bottom-of-rep trunk angle" />
            </div>
          </div>
        </div>
      </div>

      {/* injury risks first */}
      {injury.length > 0 && (
        <div className="rounded-2xl border border-red-900/60 bg-neutral-900 p-5">
          <h3 className="mb-1 text-sm font-semibold uppercase tracking-wide text-red-400">
            Injury risks — address these first
          </h3>
          <p className="mb-4 text-xs text-neutral-500">
            Patterns that load joints in ways associated with common lifting injuries.
          </p>
          <div className="space-y-3">
            {injury.map((f, i) => <FindingCard key={i} f={f} />)}
          </div>
        </div>
      )}

      {/* what's working */}
      {goods.length > 0 && (
        <div className="rounded-2xl border border-emerald-900/60 bg-neutral-900 p-5">
          <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-emerald-400">
            What's working — keep doing this
          </h3>
          <ul className="space-y-1.5 text-sm text-neutral-300">
            {goods.map((g, i) => (
              <li key={i} className="flex gap-2">
                <span className="text-emerald-500">✓</span>{g}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* coaching cues */}
      {faults.length > 0 && (
        <div className="rounded-2xl border border-neutral-800 bg-neutral-900 p-5">
          <h3 className="mb-1 text-sm font-semibold uppercase tracking-wide text-neutral-400">
            Coaching cues — ranked by impact
          </h3>
          <p className="mb-4 text-xs text-neutral-500">
            Each cue includes the measured value that triggered it.
          </p>
          <div className="space-y-3">
            {faults.map((f, i) => <FindingCard key={i} f={f} />)}
          </div>
        </div>
      )}
      {report.findings.length === 0 && (
        <div className="rounded-2xl border border-neutral-800 bg-neutral-900 p-5">
          <p className="text-sm text-neutral-400">
            No faults detected — clean lift. Add load or send a heavier set
            for a harder look at your technique.
          </p>
        </div>
      )}

      {/* charts with reading guides */}
      <div className="grid gap-6 lg:grid-cols-2">
        <ChartCard
          title="Joint angles through the set"
          guide="Each dip is a rep's deepest point. Knee/hip flexion should peak together; a trunk line climbing past the expected lean means you're folding forward."
          takeaway={takeaway(report, 'angles')}
        >
          <LineChart data={angleData}>
            <CartesianGrid stroke="#262626" />
            <XAxis dataKey="t" stroke="#737373" fontSize={11} unit="s" />
            <YAxis stroke="#737373" fontSize={11} unit="°" />
            <Tooltip contentStyle={{ background: '#171717', border: '1px solid #333' }} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Line dataKey="knee" name="knee flexion" stroke="#34d399" dot={false} />
            <Line dataKey="hip" name="hip flexion" stroke="#60a5fa" dot={false} />
            <Line dataKey="trunk" name="trunk incl" stroke="#fbbf24" dot={false} />
          </LineChart>
        </ChartCard>
        <ChartCard
          title="Estimated joint torques (N·m/kg)"
          guide="How hard each joint worked, normalized to bodyweight. Watch which curve is bigger — a knee-dominant or hip-dominant strategy shows up as one line towering over the other."
          takeaway={takeaway(report, 'moments')}
        >
          <LineChart data={momentData}>
            <CartesianGrid stroke="#262626" />
            <XAxis dataKey="t" stroke="#737373" fontSize={11} unit="s" />
            <YAxis stroke="#737373" fontSize={11} />
            <Tooltip contentStyle={{ background: '#171717', border: '1px solid #333' }} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Line dataKey="knee" name="knee" stroke="#34d399" dot={false} />
            <Line dataKey="hip" name="hip" stroke="#60a5fa" dot={false} />
            <Line dataKey="l5s1" name="L5/S1 (low back)" stroke="#f87171" dot={false} />
          </LineChart>
        </ChartCard>
      </div>

      {/* rep table */}
      <div className="overflow-x-auto rounded-2xl border border-neutral-800 bg-neutral-900 p-5">
        <h3 className="mb-1 text-sm font-semibold uppercase tracking-wide text-neutral-400">
          Per-rep detail
        </h3>
        <p className="mb-3 text-xs text-neutral-500">
          Depth margin: positive = below parallel. MCV: rep speed. v-loss:
          slowdown vs your best rep. Torques: peak joint demand per kg
          bodyweight.
        </p>
        <table className="w-full text-left text-xs">
          <thead className="text-neutral-500">
            <tr>
              <th className="py-1 pr-4">rep</th>
              <th className="py-1 pr-4">dur s</th>
              <th className="py-1 pr-4">depth margin</th>
              <th className="py-1 pr-4">max knee flex</th>
              <th className="py-1 pr-4">trunk incl max</th>
              <th className="py-1 pr-4">MCV</th>
              <th className="py-1 pr-4">v-loss %</th>
              <th className="py-1 pr-4">knee Nm/kg</th>
              <th className="py-1 pr-4">hip Nm/kg</th>
              <th className="py-1 pr-4">L5/S1 Nm/kg</th>
            </tr>
          </thead>
          <tbody className="text-neutral-300">
            {report.reps.map(r => (
              <tr key={r.index} className="border-t border-neutral-800">
                <td className="py-1.5 pr-4">{r.index}{r.metrics.tracking_suspect ? ' ⚠' : ''}</td>
                <td className="py-1.5 pr-4">{r.metrics.duration_s?.toFixed(2)}</td>
                <td className="py-1.5 pr-4">{fmtM(r.metrics.depth_margin)}</td>
                <td className="py-1.5 pr-4">{r.metrics.max_knee_flexion?.toFixed(0)}°</td>
                <td className="py-1.5 pr-4">{r.metrics.trunk_incl_max?.toFixed(0)}°</td>
                <td className="py-1.5 pr-4">{r.velocity?.mcv.toFixed(2) ?? '—'}</td>
                <td className="py-1.5 pr-4">{r.velocity?.v_loss_pct.toFixed(0) ?? '—'}</td>
                <td className="py-1.5 pr-4">{num(r.torque_peaks?.knee_peak_norm)}</td>
                <td className="py-1.5 pr-4">{num(r.torque_peaks?.hip_peak_norm)}</td>
                <td className="py-1.5 pr-4">{num(r.torque_peaks?.l5s1_peak_norm)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-2 text-[11px] text-neutral-600">
          ⚠ = tracking suspect — pose detection was uncertain on that rep,
          treat its numbers as approximate
        </p>
      </div>
    </div>
  )
}

function FindingCard({ f }: { f: ReportT['findings'][number] }) {
  const sev = SEV[f.severity]
  return (
    <div className={`rounded-xl border p-4 ${sev.cls}`}>
      <div className="flex items-center justify-between gap-4">
        <span className="font-semibold">{f.title}</span>
        <span className="shrink-0 rounded-full border border-current px-2 py-0.5 text-[10px] uppercase">
          {sev.label}{f.reps.length ? ` · rep ${f.reps.join(',')}` : ''}
        </span>
      </div>
      <p className="mt-1 text-xs opacity-80">Measured: {f.evidence}</p>
      <p className="mt-2 text-sm"><span className="font-medium">Cue: </span>{f.cue}</p>
      <p className="mt-1 text-sm opacity-80"><span className="font-medium">Train it: </span>{f.drill}</p>
    </div>
  )
}

function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded-full border border-neutral-700 px-2.5 py-1">{children}</span>
  )
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wide text-neutral-500">{label}</div>
      <div className="text-lg font-semibold">{value}</div>
      {hint && <div className="text-[10px] text-neutral-600">{hint}</div>}
    </div>
  )
}

function ChartCard({ title, guide, takeaway, children }: {
  title: string; guide: string; takeaway: string; children: React.ReactElement
}) {
  return (
    <div className="rounded-2xl border border-neutral-800 bg-neutral-900 p-4">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-neutral-400">{title}</h3>
      <p className="mb-2 mt-1 text-xs text-neutral-500">{guide}</p>
      <div className="h-52">
        <ResponsiveContainer width="100%" height="100%">{children}</ResponsiveContainer>
      </div>
      {takeaway && <p className="mt-2 text-xs text-emerald-400/90">{takeaway}</p>}
    </div>
  )
}

function num(v: number | null | undefined): string {
  return v == null ? '—' : v.toFixed(2)
}

function fmtM(v: number | null | undefined): string {
  if (v == null) return '—'
  return `${v > 0 ? '+' : ''}${v.toFixed(3)} m`
}
