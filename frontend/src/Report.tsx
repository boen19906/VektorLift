import {
  Line, LineChart, CartesianGrid, XAxis, YAxis, Tooltip,
  ResponsiveContainer, BarChart, Bar, Legend,
} from 'recharts'
import type { Report as ReportT, Finding } from './types'
import { videoUrl } from './api'

const SEV = {
  3: { label: 'Injury risk', card: 'border-red-200 bg-red-50', tag: 'bg-red-100 text-red-700', text: 'text-red-900' },
  2: { label: 'Form fault', card: 'border-amber-200 bg-amber-50', tag: 'bg-amber-100 text-amber-800', text: 'text-amber-900' },
  1: { label: 'Efficiency', card: 'border-sky-200 bg-sky-50', tag: 'bg-sky-100 text-sky-700', text: 'text-sky-900' },
} as const

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
  if (r.lift_type === 'deadlift') {
    const ratios = m('hip_bar_rise_ratio')
    if (ratios.length && ratios.every(x => x <= 2))
      g.push('Hips and bar rose together off the floor — no stiff-legging')
    if (m('bar_reversals').every(x => x === 0))
      g.push('Smooth, hitch-free pull through the knee region')
  }
  return g
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
    rep: `R${r.index}`, mcv: r.velocity?.mcv ?? 0, loss: r.velocity?.v_loss_pct ?? 0,
  }))
  const bestDepth = Math.max(...report.reps.map(r => r.metrics.depth_margin ?? -9))
  const peakHip = Math.max(...report.reps.map(r => Math.abs(r.torque_peaks?.hip_peak_norm ?? 0)))

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      {/* activity header — Strava-style */}
      <div className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-lg font-bold text-neutral-900 capitalize">
              {report.lift_type} · {report.reps.length} rep{report.reps.length !== 1 ? 's' : ''}
            </div>
            <div className="text-xs text-neutral-500">
              {report.side} side · bar {report.quality.bar_tracking} ·{' '}
              {report.quality.metric_scale ? 'metric scale' : 'stature units'} ·{' '}
              {report.quality.frames_usable_pct}% frames usable
            </div>
          </div>
          <div className={`rounded-full px-3 py-1 text-xs font-semibold ${
            injury.length ? 'bg-red-100 text-red-700'
            : faults.length ? 'bg-amber-100 text-amber-800'
            : 'bg-emerald-100 text-emerald-700'}`}>
            {injury.length ? `${injury.length} injury risk${injury.length > 1 ? 's' : ''}`
              : faults.length ? `${faults.length} issue${faults.length > 1 ? 's' : ''}`
              : 'Clean set'}
          </div>
        </div>
        <div className="mt-4 grid grid-cols-4 divide-x divide-neutral-200 rounded-xl border border-neutral-200 py-3 text-center">
          <Stat label="Reps" value={`${report.reps.length}`} />
          <Stat label="Best depth" value={`${bestDepth > -9 ? `${bestDepth > 0 ? '+' : ''}${bestDepth.toFixed(2)} m` : '—'}`} sub="vs parallel" />
          <Stat label="Top bar speed" value={report.fatigue ? `${report.fatigue.best_mcv.toFixed(2)}` : '—'} sub="m/s" />
          <Stat label="Peak hip load" value={peakHip ? peakHip.toFixed(1) : '—'} sub="N·m/kg" />
        </div>
        {!report.quality.camera_side_on && (
          <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            Camera looks angled rather than side-on — 2-D angles and distances are
            approximate. Re-film square to the lifter for precise numbers.
          </p>
        )}
      </div>

      {/* annotated video */}
      <div className="rounded-2xl border border-neutral-200 bg-white p-3 shadow-sm">
        <video src={videoUrl(jobId)} controls loop muted className="w-full rounded-xl bg-black" />
      </div>

      {/* injury risks */}
      {injury.length > 0 && (
        <Section title="Injury risks" subtitle="Address these first — the tagged body parts are carrying the load." accent="text-red-700">
          {injury.map((f, i) => <FindingCard key={i} f={f} />)}
        </Section>
      )}

      {/* what's working */}
      {goods.length > 0 && (
        <div className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm">
          <h3 className="text-sm font-bold text-emerald-700">What's working — keep doing this</h3>
          <ul className="mt-3 space-y-1.5 text-sm text-neutral-700">
            {goods.map((g, i) => (
              <li key={i} className="flex gap-2"><span className="font-bold text-emerald-500">✓</span>{g}</li>
            ))}
          </ul>
        </div>
      )}

      {/* coaching cues */}
      {faults.length > 0 && (
        <Section title="Coaching cues" subtitle="Ranked by impact — each shows the measurement that triggered it." accent="text-amber-700">
          {faults.map((f, i) => <FindingCard key={i} f={f} />)}
        </Section>
      )}
      {report.findings.length === 0 && (
        <div className="rounded-2xl border border-neutral-200 bg-white p-5 text-sm text-neutral-600 shadow-sm">
          Clean lift — no faults detected. Add load or send a heavier set for a harder look.
        </div>
      )}

      {/* fatigue */}
      {report.fatigue && (
        <div className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm">
          <h3 className="text-sm font-bold text-neutral-900">Fatigue / bar speed</h3>
          <p className="mt-1 text-xs text-neutral-500">
            Mean concentric velocity (MCV) = how fast the bar moved up. Velocity loss compares each rep
            to your fastest — under 10% is fresh, 20%+ means you're past the productive part of the set.
          </p>
          <div className="mt-3 grid grid-cols-3 divide-x divide-neutral-200 rounded-xl border border-neutral-200 py-3 text-center">
            <Stat label="Best rep" value={`${report.fatigue.best_mcv.toFixed(2)}`} sub={report.fatigue.units} />
            <Stat label="Velocity loss" value={`${report.fatigue.set_v_loss_pct.toFixed(0)}%`} sub="first → last" />
            <Stat label="Set status" value={report.fatigue.fatigue_band} sub="fresh → excessive" />
          </div>
          <div className="mt-4 h-40">
            <ResponsiveContainer>
              <BarChart data={velData}>
                <CartesianGrid stroke="#e5e5e5" />
                <XAxis dataKey="rep" stroke="#a3a3a3" fontSize={11} />
                <YAxis yAxisId="l" stroke="#a3a3a3" fontSize={11} />
                <YAxis yAxisId="r" orientation="right" stroke="#a3a3a3" fontSize={11} unit="%" />
                <Tooltip contentStyle={{ background: '#fff', border: '1px solid #e5e5e5', fontSize: 12 }} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar yAxisId="l" dataKey="mcv" name="rep speed (m/s)" fill="#FC4C02" />
                <Bar yAxisId="r" dataKey="loss" name="velocity loss %" fill="#94a3b8" />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className="mt-2 text-xs text-neutral-500">
            Orange bars are rep speed — want them roughly level. Gray bars show each rep's slowdown vs your best.
          </p>
        </div>
      )}

      {/* anthropometry */}
      <div className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm">
        <h3 className="text-sm font-bold text-neutral-900">Your proportions</h3>
        <p className="mt-1 text-xs text-neutral-500">
          Segment lengths measured from video. Femur:trunk ratio sets the forward lean mechanically
          expected — your torso angle is judged against <em>your</em> build, not an ideal.
        </p>
        <div className="mt-3 grid grid-cols-3 gap-x-4 gap-y-3 text-sm">
          {Object.entries(report.anthropometry.lengths).map(([k, v]) => (
            <Stat key={k} label={k} value={`${(v * 100).toFixed(0)}`} sub="cm" left />
          ))}
          <Stat label="femur:trunk" value={report.anthropometry.ratios.femur_to_trunk?.toFixed(2) ?? '—'} sub="higher = more lean" left />
          <Stat label="expected lean" value={`${report.anthropometry.expected_trunk_lean_deg}°`} sub="at bottom" left />
        </div>
      </div>

      {/* charts */}
      <ChartCard
        title="Joint angles through the set"
        guide="Each dip is a rep's deepest point. Knee/hip flexion should peak together; trunk climbing past expected lean = folding forward."
      >
        <LineChart data={angleData}>
          <CartesianGrid stroke="#e5e5e5" />
          <XAxis dataKey="t" stroke="#a3a3a3" fontSize={11} unit="s" />
          <YAxis stroke="#a3a3a3" fontSize={11} unit="°" />
          <Tooltip contentStyle={{ background: '#fff', border: '1px solid #e5e5e5', fontSize: 12 }} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Line dataKey="knee" name="knee flexion" stroke="#FC4C02" dot={false} />
          <Line dataKey="hip" name="hip flexion" stroke="#0284c7" dot={false} />
          <Line dataKey="trunk" name="trunk incl" stroke="#a16207" dot={false} />
        </LineChart>
      </ChartCard>
      <ChartCard
        title="Estimated joint torques (N·m/kg)"
        guide="Joint demand normalized to bodyweight. A knee- or hip-dominant strategy shows up as one line towering over the other."
      >
        <LineChart data={momentData}>
          <CartesianGrid stroke="#e5e5e5" />
          <XAxis dataKey="t" stroke="#a3a3a3" fontSize={11} unit="s" />
          <YAxis stroke="#a3a3a3" fontSize={11} />
          <Tooltip contentStyle={{ background: '#fff', border: '1px solid #e5e5e5', fontSize: 12 }} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Line dataKey="knee" name="knee" stroke="#FC4C02" dot={false} />
          <Line dataKey="hip" name="hip" stroke="#0284c7" dot={false} />
          <Line dataKey="l5s1" name="L5/S1 (low back)" stroke="#dc2626" dot={false} />
        </LineChart>
      </ChartCard>

      {/* rep table */}
      <div className="overflow-x-auto rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm">
        <h3 className="text-sm font-bold text-neutral-900">Per-rep detail</h3>
        <p className="mt-1 mb-3 text-xs text-neutral-500">
          Depth margin: positive = below parallel. MCV: rep speed. v-loss: slowdown vs best rep.
          Torques: peak joint demand per kg bodyweight.
        </p>
        <table className="w-full text-left text-xs">
          <thead className="text-neutral-500">
            <tr>
              <th className="py-1 pr-4">rep</th><th className="py-1 pr-4">dur s</th>
              <th className="py-1 pr-4">depth margin</th><th className="py-1 pr-4">max knee flex</th>
              <th className="py-1 pr-4">trunk incl max</th><th className="py-1 pr-4">MCV</th>
              <th className="py-1 pr-4">v-loss %</th><th className="py-1 pr-4">knee Nm/kg</th>
              <th className="py-1 pr-4">hip Nm/kg</th><th className="py-1 pr-4">L5/S1 Nm/kg</th>
            </tr>
          </thead>
          <tbody className="text-neutral-700">
            {report.reps.map(r => (
              <tr key={r.index} className="border-t border-neutral-100">
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
        <p className="mt-2 text-[11px] text-neutral-400">
          ⚠ = tracking suspect — pose detection uncertain on that rep; treat its numbers as approximate
        </p>
      </div>
    </div>
  )
}

function Section({ title, subtitle, accent, children }: {
  title: string; subtitle: string; accent: string; children: React.ReactNode
}) {
  return (
    <div className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm">
      <h3 className={`text-sm font-bold ${accent}`}>{title}</h3>
      <p className="mt-0.5 mb-4 text-xs text-neutral-500">{subtitle}</p>
      <div className="space-y-3">{children}</div>
    </div>
  )
}

function FindingCard({ f }: { f: Finding }) {
  const sev = SEV[f.severity]
  return (
    <div className={`rounded-xl border p-4 ${sev.card}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className={`font-semibold ${sev.text}`}>{f.title}</span>
        <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ${sev.tag}`}>
          {sev.label}
        </span>
        {f.body_part && (
          <span className="rounded-full bg-white/80 px-2 py-0.5 text-[10px] font-semibold uppercase text-neutral-600 border border-neutral-200">
            {f.body_part}
          </span>
        )}
        {f.reps.length > 0 && (
          <span className="rounded-full bg-white/80 px-2 py-0.5 text-[10px] text-neutral-500 border border-neutral-200">
            rep {f.reps.join(', ')}
          </span>
        )}
      </div>
      <p className="mt-1.5 text-xs text-neutral-500">Measured: {f.evidence}</p>
      <p className={`mt-2 text-sm ${sev.text}`}><span className="font-semibold">Cue: </span>{f.cue}</p>
      <p className="mt-1 text-sm text-neutral-600"><span className="font-semibold">Train it: </span>{f.drill}</p>
    </div>
  )
}

function Stat({ label, value, sub, left }: { label: string; value: string; sub?: string; left?: boolean }) {
  return (
    <div className={left ? 'text-left' : ''}>
      <div className="text-[10px] font-semibold uppercase tracking-wide text-neutral-400">{label}</div>
      <div className="text-xl font-bold text-neutral-900">{value}</div>
      {sub && <div className="text-[10px] text-neutral-400">{sub}</div>}
    </div>
  )
}

function ChartCard({ title, guide, children }: {
  title: string; guide: string; children: React.ReactElement
}) {
  return (
    <div className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm">
      <h3 className="text-sm font-bold text-neutral-900">{title}</h3>
      <p className="mb-2 mt-0.5 text-xs text-neutral-500">{guide}</p>
      <div className="h-52">
        <ResponsiveContainer width="100%" height="100%">{children}</ResponsiveContainer>
      </div>
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
