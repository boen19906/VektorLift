import { useRef, useState } from 'react'
import type { AnalyzeMeta } from './types'

interface Props {
  onSubmit: (file: File, meta: AnalyzeMeta) => void
  busy: boolean
}

export default function UploadForm({ onSubmit, busy }: Props) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [meta, setMeta] = useState<AnalyzeMeta>({
    lift_type: 'squat',
    load_kg: 100,
    bodyweight_kg: 80,
    height_m: 1.78,
    sex: 'male',
  })

  const set = (k: keyof AnalyzeMeta, v: string) =>
    setMeta(m => ({ ...m, [k]: k === 'lift_type' || k === 'sex' ? v : Number(v) }))

  return (
    <div className="mx-auto max-w-xl rounded-2xl border border-neutral-800 bg-neutral-900 p-8">
      <h2 className="mb-1 text-xl font-semibold">Analyze a lift</h2>
      <p className="mb-6 text-sm text-neutral-400">
        Side-angle video, full body visible, plates facing the camera if
        possible. Include a moment standing upright before the first rep.
      </p>

      <div
        className="mb-6 flex h-36 cursor-pointer items-center justify-center rounded-xl border-2 border-dashed border-neutral-700 text-neutral-400 hover:border-emerald-500 hover:text-emerald-400"
        onClick={() => fileRef.current?.click()}
      >
        {file ? `${file.name} (${(file.size / 1e6).toFixed(1)} MB)` : 'Drop or pick a video'}
        <input
          ref={fileRef}
          type="file"
          accept="video/*"
          className="hidden"
          onChange={e => setFile(e.target.files?.[0] ?? null)}
        />
      </div>

      <div className="grid grid-cols-2 gap-4 text-sm">
        <label className="flex flex-col gap-1">
          <span className="text-neutral-400">Lift</span>
          <select
            value={meta.lift_type}
            onChange={e => set('lift_type', e.target.value)}
            className="rounded-lg border border-neutral-700 bg-neutral-800 px-3 py-2"
          >
            <option value="squat">Squat</option>
            <option value="deadlift">Deadlift</option>
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-neutral-400">Sex (anthropometrics)</span>
          <select
            value={meta.sex}
            onChange={e => set('sex', e.target.value)}
            className="rounded-lg border border-neutral-700 bg-neutral-800 px-3 py-2"
          >
            <option value="male">Male</option>
            <option value="female">Female</option>
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-neutral-400">Bar load (kg)</span>
          <input
            type="number" min={0} step={2.5} value={meta.load_kg}
            onChange={e => set('load_kg', e.target.value)}
            className="rounded-lg border border-neutral-700 bg-neutral-800 px-3 py-2"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-neutral-400">Bodyweight (kg)</span>
          <input
            type="number" min={30} step={0.5} value={meta.bodyweight_kg}
            onChange={e => set('bodyweight_kg', e.target.value)}
            className="rounded-lg border border-neutral-700 bg-neutral-800 px-3 py-2"
          />
        </label>
        <label className="col-span-2 flex flex-col gap-1">
          <span className="text-neutral-400">Height (m) — used for metric scale</span>
          <input
            type="number" min={1.2} max={2.3} step={0.01} value={meta.height_m}
            onChange={e => set('height_m', e.target.value)}
            className="rounded-lg border border-neutral-700 bg-neutral-800 px-3 py-2"
          />
        </label>
      </div>

      <button
        disabled={!file || busy}
        onClick={() => file && onSubmit(file, meta)}
        className="mt-6 w-full rounded-xl bg-emerald-600 py-3 font-semibold transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:bg-neutral-700"
      >
        {busy ? 'Uploading…' : 'Analyze'}
      </button>
    </div>
  )
}
