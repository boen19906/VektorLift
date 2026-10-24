import { useEffect, useRef, useState } from 'react'
import UploadForm from './UploadForm'
import Report from './Report'
import { analyzeVideo, getJob, getResult, getJobs } from './api'
import type { JobSummary } from './api'
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
  const [connLost, setConnLost] = useState(false)
  const poll = useRef<number | null>(null)

  useEffect(() => () => { if (poll.current) window.clearInterval(poll.current) }, [])

  // resume an in-flight or finished analysis after a page reload
  useEffect(() => {
    const jobId = localStorage.getItem(LAST_JOB_KEY)
    if (!jobId) return
    let cancelled = false
    ;(async () => {
      // retry briefly — a transient failure shouldn't lose a running job
      let j = null
      for (let i = 0; i < 4 && !j; i++) {
        try {
          j = await getJob(jobId)
        } catch {
          await new Promise(r => setTimeout(r, 1500))
        }
      }
      if (cancelled) return
      if (!j) {
        localStorage.removeItem(LAST_JOB_KEY)
        return
      }
      try {
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
    let consecutiveFails = 0
    poll.current = window.setInterval(async () => {
      try {
        const j = await getJob(jobId)
        consecutiveFails = 0
        setConnLost(false)
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
        consecutiveFails += 1
        // surface a lost connection instead of silently freezing; the
        // poll keeps running and self-heals when the server is back
        if (consecutiveFails >= 10) setConnLost(true)
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

  async function openJob(jobId: string) {
    try {
      const j = await getJob(jobId)
      if (j.status === 'done') {
        const report = await getResult(jobId)
        localStorage.setItem(LAST_JOB_KEY, jobId)
        setStage({ kind: 'done', jobId, report })
      } else if (j.status === 'error') {
        setStage({ kind: 'error', message: j.error ?? 'analysis failed' })
      } else {
        localStorage.setItem(LAST_JOB_KEY, jobId)
        setStage({ kind: 'processing', jobId, progress: j.progress })
        startPolling(jobId)
      }
    } catch (e) {
      setStage({ kind: 'error', message: e instanceof Error ? e.message : 'could not open job' })
    }
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

      {stage.kind === 'idle' && (
        <>
          <UploadForm onSubmit={submit} busy={false} />
          <RecentJobs onOpen={openJob} />
        </>
      )}
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
          {connLost && (
            <div className="mt-4 rounded-lg border border-amber-800 bg-amber-950/50 px-3 py-2 text-xs text-amber-300">
              Lost connection to the analysis server — still retrying in the
              background. If this persists, check that the backend is running
              on :8000 and refresh.
            </div>
          )}
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

function RecentJobs({ onOpen }: { onOpen: (jobId: string) => void }) {
  const [jobs, setJobs] = useState<JobSummary[]>([])

  useEffect(() => {
    getJobs()
      .then(js => setJobs(js.filter(j => j.has_result)))
      .catch(() => {})
  }, [])

  if (!jobs.length) return null

  return (
    <div className="mx-auto mt-6 max-w-xl">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">
        Recent analyses
      </h3>
      <div className="space-y-1">
        {jobs.slice(0, 6).map(j => (
          <button
            key={j.id}
            onClick={() => onOpen(j.id)}
            className="flex w-full items-center justify-between rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-2.5 text-left text-sm hover:border-emerald-700"
          >
            <span className="truncate text-neutral-300">
              {j.filename ?? j.id}
            </span>
            <span className="ml-3 shrink-0 text-xs text-neutral-500">
              {j.lift_type} · {new Date(j.created_at * 1000).toLocaleTimeString()}
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}
