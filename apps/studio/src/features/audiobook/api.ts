/** Audiobook client (React Query). Renders are Jobs with `ref: audiobook:<id>`; the project refetches when they end. */
import { useEffect, useMemo, useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from '@studio/ui'
import { api } from '../../api/client'
import type {
  AudiobookCreate,
  AudiobookImportResult,
  AudiobookPatch,
  AudiobookPlan,
  AudiobookPlanRequest,
  AudiobookProject,
  AudiobookRenderRequest,
  AudiobookSummary,
} from '../../api/contracts/dub'
import { useLive } from '../../api/live'
import type { Job } from '../../api/types'
import { isActive } from '../../lib/jobs'

export const ak = {
  projects: ['audiobook', 'projects'] as const,
  project: (id: string) => ['audiobook', 'project', id] as const,
  plan: (script: string) => ['audiobook', 'plan', script] as const,
}

const onError = (title: string) => (e: Error) => toast.error(title, e.message)
const path = (id: string) => `/audiobook/projects/${encodeURIComponent(id)}`

export const useAudiobooks = () =>
  useQuery({ queryKey: ak.projects, queryFn: () => api.get<AudiobookSummary[]>('/audiobook/projects') })

export const useAudiobook = (id: string) => useQuery({ queryKey: ak.project(id), queryFn: () => api.get<AudiobookProject>(path(id)) })

/** Chapter/voice/runtime plan of a script (server-side parser — the single grammar). */
export const usePlan = (script: string) =>
  useQuery({
    queryKey: ak.plan(script),
    queryFn: () => api.post<AudiobookPlan>('/audiobook/plan', { script } satisfies AudiobookPlanRequest),
    placeholderData: (prev) => prev,
    staleTime: Infinity,
  })

export function useRenderJob(id: string) {
  const qc = useQueryClient()
  const jobs = useLive((s) => s.jobs)
  const mine = useMemo(() => jobs.filter((j) => j.ref === `audiobook:${id}`), [jobs, id])
  const seen = useRef(new Map<string, string>())
  useEffect(() => {
    for (const j of mine) {
      const prev = seen.current.get(j.id)
      seen.current.set(j.id, j.status)
      if (prev && prev !== j.status && !isActive(j)) {
        void qc.invalidateQueries({ queryKey: ak.project(id) })
        void qc.invalidateQueries({ queryKey: ak.projects })
        if (j.status === 'done') toast.success(j.title, j.message)
      }
    }
  }, [mine, qc, id])
  return mine.find(isActive)
}

export function useCreateAudiobook() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: AudiobookCreate) => api.post<AudiobookProject>('/audiobook/projects', body),
    onSuccess: (p) => {
      qc.setQueryData(ak.project(p.id), p)
      void qc.invalidateQueries({ queryKey: ak.projects })
    },
    onError: onError('Could not create the audiobook'),
  })
}

export function usePatchAudiobook(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (patch: AudiobookPatch) => api.patch<AudiobookProject>(path(id), patch),
    onSuccess: (p) => qc.setQueryData(ak.project(id), p),
    onError: onError('Could not save'),
  })
}

export function useDeleteAudiobook() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.del(path(id)),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ak.projects }),
    onError: onError('Could not delete'),
  })
}

export function useImportManuscript() {
  return useMutation({
    mutationFn: (file: File) => {
      const form = new FormData()
      form.append('file', file, file.name)
      return api.upload<AudiobookImportResult>('/audiobook/import', form)
    },
    onError: onError('Import failed'),
  })
}

export function useRenderAudiobook(id: string) {
  return useMutation({
    mutationFn: (req: AudiobookRenderRequest) => api.post<Job>(`${path(id)}/render`, req),
    onSuccess: (job) => useLive.getState().upsertJob(job),
    onError: onError('Could not render'),
  })
}

export function useUploadCover(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => {
      const form = new FormData()
      form.append('file', file, file.name)
      return api.upload<AudiobookProject>(`${path(id)}/cover`, form)
    },
    onSuccess: (p) => qc.setQueryData(ak.project(id), p),
    onError: onError('Could not set the cover'),
  })
}

export function useDeleteRender(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (renderId: string) => api.del(`${path(id)}/renders/${renderId}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ak.project(id) }),
  })
}
