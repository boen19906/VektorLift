import type { AnalyzeMeta, JobStatus, Report } from './types'

export async function analyzeVideo(file: File, meta: AnalyzeMeta): Promise<string> {
  const fd = new FormData()
  fd.append('file', file)
  Object.entries(meta).forEach(([k, v]) => fd.append(k, String(v)))
  const res = await fetch('/api/analyze', { method: 'POST', body: fd })
  if (!res.ok) throw new Error((await res.json()).detail ?? `upload failed (${res.status})`)
  return (await res.json()).job_id
}

export async function getJob(id: string): Promise<JobStatus> {
  const res = await fetch(`/api/jobs/${id}`)
  if (!res.ok) throw new Error(`status failed (${res.status})`)
  return res.json()
}

export async function getResult(id: string): Promise<Report> {
  const res = await fetch(`/api/jobs/${id}/result`)
  if (!res.ok) throw new Error(`result failed (${res.status})`)
  return res.json()
}

export function videoUrl(id: string): string {
  return `/api/jobs/${id}/video`
}
