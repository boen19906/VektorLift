import { useEffect, useRef, useState } from 'react'
import UploadForm from './UploadForm'
import Report from './Report'
import { analyzeVideo, getJob, getResult } from './api'
import type { AnalyzeMeta, Report as ReportT } from './types'

type Stage =
  | { kind: 'idle' }
  | { kind: 'uploading' }
  | { kind: 'processing'; jobId: string; progress: number }
  | { kind: 'done'; jobId: string; report: ReportT }
  | { kind: 'error'; message: string }

const LAST_JOB_KEY = 'vektorlift:lastJob'

export default function App() {
  const [stage, setStage] = useState<Stage>({ kind: 'idle' })
  const poll = useRef<number | null>(null)

  useEffect(() => () => { if (poll.current) window.clearInterval(poll.current) }, [])

  // resume an in-flight or finished analysis after a page reload
  useEffect(() => {
    const jobId = localStorage.getItem(LAST_JOB_KEY)
    if (!jobId) return
    let cancelled = false
    ;(async () => {
      try {
        const j = await getJob(jobId)
        if (cancelled) return
        if (j.status === 'done') {
          const report = await getResult(jobId)
          if (!cancelled) setStage({ kind: 'done', jobId, report })
        } else if (j.status === 'error') {
          localStorage.removeItem(LAST_JOB_KEY)
        } else {
          setStage({ kind: 'processing', jobId, progress: j.progress })
          startPolling(jobId)
        }
      } catch {
        localStorage.removeItem(LAST_JOB_KEY)
      }
    })()
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function startPolling(jobId: string) {
    if (poll.current) window.clearInterval(poll.current)
    poll.current = window.setInterval(async () => {
      try {
        const j = await getJob(jobId)
        if (j.status === 'done') {
          const report = await getResult(jobId)
          if (poll.current) window.clearInterval(poll.current)
          setStage({ kind: 'done', jobId, report })
        } else if (j.status === 'error') {
          if (poll.current) window.clearInterval(poll.current)
          localStorage.removeItem(LAST_JOB_KEY)
          setStage({ kind: 'error', message: j.error ?? 'analysis failed' })
        } else {
          setStage({ kind: 'processing', jobId, progress: j.progress })
        }
      } catch {
        /* transient poll errors are fine */
      }
    }, 800)
  }

  async function submit(file: File, meta: AnalyzeMeta) {
    setStage({ kind: 'uploading' })
    try {
      const jobId = await analyzeVideo(file, meta)
      localStorage.setItem(LAST_JOB_KEY, jobId)
      setStage({ kind: 'processing', jobId, progress: 0 })
      startPolling(jobId)
    } catch (e) {
      setStage({ kind: 'error', message: e instanceof Error ? e.message : 'upload failed' })
    }
  }

  function reset() {
    localStorage.removeItem(LAST_JOB_KEY)
    if (poll.current) window.clearInterval(poll.current)
    setStage({ kind: 'idle' })
  }

  return (
    <div className="min-h-screen px-4 py-10">
      <header className="mx-auto mb-8 max-w-6xl">
        <h1 className="text-3xl font-bold tracking-tight">
          Vektor<span className="text-emerald-400">Lift</span>
        </h1>
        <p className="mt-1 text-sm text-neutral-400">
          Bar-path kinematics · anthropometric-normalized form checks ·
          velocity-based fatigue · inverse-statics joint torques
        </p>
      </header>

      {stage.kind === 'idle' && <UploadForm onSubmit={submit} busy={false} />}
      {stage.kind === 'uploading' && <UploadForm onSubmit={submit} busy />}

      {stage.kind === 'processing' && (
        <div className="mx-auto max-w-xl rounded-2xl border border-neutral-800 bg-neutral-900 p-8 text-center">
          <div className="mb-3 text-lg font-semibold">Analyzing your lift…</div>
          <div className="h-2 overflow-hidden rounded-full bg-neutral-800">
            <div
              className="h-full rounded-full bg-emerald-500 transition-all"
              style={{ width: `${Math.round(stage.progress * 100)}%` }}
            />
          </div>
          <div className="mt-2 text-xs text-neutral-500">
            pose tracking → calibration → inverse statics → rendering
          </div>
          <div className="mt-1 text-sm text-neutral-400">
            {Math.round(stage.progress * 100)}%
          </div>
        </div>
      )}

      {stage.kind === 'error' && (
        <div className="mx-auto max-w-xl rounded-2xl border border-red-900 bg-red-950/50 p-8">
          <div className="mb-2 text-lg font-semibold text-red-300">Analysis failed</div>
          <p className="text-sm text-red-200/80">{stage.message}</p>
          <button
            onClick={reset}
            className="mt-4 rounded-lg border border-neutral-700 px-4 py-2 text-sm hover:bg-neutral-800"
          >
            Try another video
          </button>
        </div>
      )}

      {stage.kind === 'done' && (
        <>
          <Report jobId={stage.jobId} report={stage.report} />
          <div className="mx-auto mt-8 max-w-6xl">
            <button
              onClick={reset}
              className="rounded-lg border border-neutral-700 px-4 py-2 text-sm hover:bg-neutral-800"
            >
              Analyze another video
            </button>
          </div>
        </>
      )}
    </div>
  )
}
