import type { AnalyzeMeta, JobStatus, Report } from './types'

export async function analyzeVideo(file: File, meta: AnalyzeMeta): Promise<string> {
  const fd = new FormData()
  fd.append('file', file)
  Object.entries(meta).forEach(([k, v]) => fd.append(k, String(v)))
  const res = await fetch('/api/analyze', { method: 'POST', body: fd })
  if (!res.ok) throw new Error((await res.json()).detail ?? `upload failed (${res.status})`)
  return (await res.json()).job_id
}

export interface JobSummary {
  id: string
  status: string
  progress: number
  error: string | null
  created_at: number
  filename: string | null
  lift_type: string | null
  has_result: boolean
}

export async function getJobs(): Promise<JobSummary[]> {
  const res = await fetch('/api/jobs', { signal: AbortSignal.timeout(10000) })
  if (!res.ok) throw new Error(`jobs list failed (${res.status})`)
  return res.json()
}

export async function getJob(id: string): Promise<JobStatus> {
  const res = await fetch(`/api/jobs/${id}`, { signal: AbortSignal.timeout(10000) })
  if (!res.ok) throw new Error(`status failed (${res.status})`)
  return res.json()
}

export async function getResult(id: string): Promise<Report> {
  const res = await fetch(`/api/jobs/${id}/result`, { signal: AbortSignal.timeout(15000) })
  if (!res.ok) throw new Error(`result failed (${res.status})`)
  return res.json()
}

export async function cancelJob(id: string): Promise<void> {
  await fetch(`/api/jobs/${id}/cancel`, { method: 'POST' })
}

export function videoUrl(id: string): string {
  return `/api/jobs/${id}/video`
}
