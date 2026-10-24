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

export default function Report({ jobId, report }: { jobId: string; report: ReportT }) {
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
      {/* top row: video + summary */}
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
          {report.fatigue && (
            <div className="rounded-2xl border border-neutral-800 bg-neutral-900 p-4">
              <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-neutral-400">
                Velocity-based fatigue
              </h3>
              <div className="flex items-baseline gap-6">
                <Stat label="best MCV" value={`${report.fatigue.best_mcv.toFixed(2)} ${report.fatigue.units}`} />
                <Stat label="set velocity loss" value={`${report.fatigue.set_v_loss_pct.toFixed(0)}%`} />
                <Stat label="band" value={report.fatigue.fatigue_band} />
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
                    <Bar yAxisId="l" dataKey="mcv" name="mean concentric v" fill="#34d399" />
                    <Bar yAxisId="r" dataKey="loss" name="velocity loss %" fill="#f87171" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          <div className="rounded-2xl border border-neutral-800 bg-neutral-900 p-4">
            <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-neutral-400">
              Anthropometrics
            </h3>
            <div className="grid grid-cols-3 gap-3 text-sm">
              {Object.entries(report.anthropometry.lengths).map(([k, v]) => (
                <Stat key={k} label={k} value={`${(v * 100).toFixed(0)} cm`} />
              ))}
              <Stat label="femur:trunk" value={report.anthropometry.ratios.femur_to_trunk?.toFixed(2) ?? '—'} />
              <Stat label="expected lean" value={`${report.anthropometry.expected_trunk_lean_deg}°`} />
            </div>
          </div>
        </div>
      </div>

      {/* findings */}
      <div className="rounded-2xl border border-neutral-800 bg-neutral-900 p-5">
        <h3 className="mb-4 text-sm font-semibold uppercase tracking-wide text-neutral-400">
          Coaching cues — ranked by injury risk
        </h3>
        {report.findings.length === 0 && (
          <p className="text-sm text-neutral-400">
            No faults detected — clean lift. Increase load or send a heavier set.
          </p>
        )}
        <div className="space-y-3">
          {report.findings.map((f, i) => (
            <div key={i} className={`rounded-xl border p-4 ${SEV[f.severity].cls}`}>
              <div className="flex items-center justify-between gap-4">
                <span className="font-semibold">{f.title}</span>
                <span className="shrink-0 rounded-full border border-current px-2 py-0.5 text-[10px] uppercase">
                  {SEV[f.severity].label}{f.reps.length ? ` · rep ${f.reps.join(',')}` : ''}
                </span>
              </div>
              <p className="mt-1 text-xs opacity-80">{f.evidence}</p>
              <p className="mt-2 text-sm"><span className="font-medium">Cue: </span>{f.cue}</p>
              <p className="mt-1 text-sm opacity-80"><span className="font-medium">Train it: </span>{f.drill}</p>
            </div>
          ))}
        </div>
      </div>

      {/* charts */}
      <div className="grid gap-6 lg:grid-cols-2">
        <ChartCard title="Joint angles (deg)">
          <LineChart data={angleData}>
            <CartesianGrid stroke="#262626" />
            <XAxis dataKey="t" stroke="#737373" fontSize={11} unit="s" />
            <YAxis stroke="#737373" fontSize={11} />
            <Tooltip contentStyle={{ background: '#171717', border: '1px solid #333' }} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Line dataKey="knee" name="knee flexion" stroke="#34d399" dot={false} />
            <Line dataKey="hip" name="hip flexion" stroke="#60a5fa" dot={false} />
            <Line dataKey="trunk" name="trunk incl" stroke="#fbbf24" dot={false} />
          </LineChart>
        </ChartCard>
        <ChartCard title="Net joint moments (N·m/kg)">
          <LineChart data={momentData}>
            <CartesianGrid stroke="#262626" />
            <XAxis dataKey="t" stroke="#737373" fontSize={11} unit="s" />
            <YAxis stroke="#737373" fontSize={11} />
            <Tooltip contentStyle={{ background: '#171717', border: '1px solid #333' }} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Line dataKey="knee" name="knee" stroke="#34d399" dot={false} />
            <Line dataKey="hip" name="hip" stroke="#60a5fa" dot={false} />
            <Line dataKey="l5s1" name="L5/S1" stroke="#f87171" dot={false} />
          </LineChart>
        </ChartCard>
      </div>

      {/* rep table */}
      <div className="overflow-x-auto rounded-2xl border border-neutral-800 bg-neutral-900 p-5">
        <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-neutral-400">
          Per-rep detail
        </h3>
        <table className="w-full text-left text-xs">
          <thead className="text-neutral-500">
            <tr>
              <th className="py-1 pr-4">rep</th>
              <th className="py-1 pr-4">dur s</th>
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
                <td className="py-1.5 pr-4">{r.index}</td>
                <td className="py-1.5 pr-4">{r.metrics.duration_s?.toFixed(2)}</td>
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
      </div>
    </div>
  )
}

function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded-full border border-neutral-700 px-2.5 py-1">{children}</span>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wide text-neutral-500">{label}</div>
      <div className="text-lg font-semibold">{value}</div>
    </div>
  )
}

function ChartCard({ title, children }: { title: string; children: React.ReactElement }) {
  return (
    <div className="h-64 rounded-2xl border border-neutral-800 bg-neutral-900 p-4">
      <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-neutral-400">{title}</h3>
      <ResponsiveContainer width="100%" height="85%">{children}</ResponsiveContainer>
    </div>
  )
}

function num(v: number | null | undefined): string {
  return v == null ? '—' : v.toFixed(2)
}
