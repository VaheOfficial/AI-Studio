/**
 * Dub client (React Query). Long work (prepare, translate, generate, verify, export) returns a Job whose
 * `ref` is `dub:<project id>`; progress arrives over the socket and the project is refetched when it ends.
 */
import { useEffect, useMemo, useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from '@studio/ui'
import { api } from '../../api/client'
import type {
  DubAutoGlossaryRequest,
  DubCreateResponse,
  DubExportRequest,
  DubGlossaryInput,
  DubGlossaryTerm,
  DubParsedSubtitles,
  DubParseSubtitlesRequest,
  DubPreviewResponse,
  DubProject,
  DubProjectPatch,
  DubProjectSummary,
  DubRunRequest,
  DubStatus,
  DubVoiceSample,
  DubWaveform,
} from '../../api/contracts/dub'
import { useLive } from '../../api/live'
import type { Job } from '../../api/types'
import { isActive } from '../../lib/jobs'

export const dk = {
  status: ['dub', 'status'] as const,
  projects: ['dub', 'projects'] as const,
  project: (id: string) => ['dub', 'project', id] as const,
  waveform: (id: string) => ['dub', 'waveform', id] as const,
  glossary: (id: string) => ['dub', 'glossary', id] as const,
  samples: (id: string) => ['dub', 'samples', id] as const,
}

const onError = (title: string) => (e: Error) => toast.error(title, e.message)
const upsertJob = (job: Job) => useLive.getState().upsertJob(job)
const path = (id: string) => `/dub/projects/${encodeURIComponent(id)}`

export const useDubStatus = () => useQuery({ queryKey: dk.status, queryFn: () => api.get<DubStatus>('/dub/status') })

export function useInstallMediaTools() {
  return useMutation({
    mutationFn: () => api.post<Job>('/media-tools/install'),
    onSuccess: upsertJob,
    onError: onError('Could not install ffmpeg'),
  })
}

export const useDubProjects = () =>
  useQuery({ queryKey: dk.projects, queryFn: () => api.get<DubProjectSummary[]>('/dub/projects') })

export const useDubProject = (id: string | null) =>
  useQuery({ queryKey: dk.project(id ?? ''), queryFn: () => api.get<DubProject>(path(id!)), enabled: !!id })

export const useDubWaveform = (id: string, enabled: boolean) =>
  useQuery({ queryKey: dk.waveform(id), queryFn: () => api.get<DubWaveform>(`${path(id)}/waveform`), enabled, staleTime: Infinity })

/** A speaker's clone-sample choices; refetched whenever the project changes (clips are re-cut on edits). */
export const useVoiceSamples = (id: string, speaker: string, enabled: boolean) =>
  useQuery({
    queryKey: [...dk.samples(id), speaker],
    queryFn: () => api.get<DubVoiceSample[]>(`${path(id)}/speakers/${encodeURIComponent(speaker)}/samples`),
    enabled,
  })

export const useGlossary = (id: string) =>
  useQuery({ queryKey: dk.glossary(id), queryFn: () => api.get<DubGlossaryTerm[]>(`${path(id)}/glossary`) })

/** The project's running job (if any); when a job for it finishes the project data is refetched. */
export function useProjectJob(id: string) {
  const qc = useQueryClient()
  const jobs = useLive((s) => s.jobs)
  const mine = useMemo(() => jobs.filter((j) => j.ref === `dub:${id}`), [jobs, id])
  const active = mine.find(isActive)
  const seen = useRef(new Map<string, string>())
  useEffect(() => {
    for (const j of mine) {
      const prev = seen.current.get(j.id)
      seen.current.set(j.id, j.status)
      if (prev && prev !== j.status && !isActive(j)) {
        void qc.invalidateQueries({ queryKey: dk.project(id) })
        void qc.invalidateQueries({ queryKey: dk.waveform(id) })
        void qc.invalidateQueries({ queryKey: dk.samples(id) })
        void qc.invalidateQueries({ queryKey: dk.projects })
        if (j.status === 'done' && j.message) toast.success(j.title, j.message)
      }
    }
  }, [mine, qc, id])
  return active
}

/** The project's most recent job when it failed — its result (e.g. the dub track) is still the previous one. */
export function useFailedProjectJob(id: string) {
  const jobs = useLive((s) => s.jobs)
  return useMemo(() => {
    const latest = jobs.filter((j) => j.ref === `dub:${id}`).sort((a, b) => b.created_at.localeCompare(a.created_at))[0]
    return latest?.status === 'error' ? latest : undefined
  }, [jobs, id])
}

export function useCreateDubProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { file?: File; url?: string; name?: string; sourceLang?: string; numSpeakers?: number }) => {
      const form = new FormData()
      if (v.file) form.append('file', v.file, v.file.name)
      if (v.url) form.append('url', v.url)
      if (v.name) form.append('name', v.name)
      if (v.sourceLang) form.append('source_lang', v.sourceLang)
      if (v.numSpeakers) form.append('num_speakers', String(v.numSpeakers))
      return api.upload<DubCreateResponse>('/dub/projects', form)
    },
    onSuccess: (res) => {
      upsertJob(res.job)
      qc.setQueryData(dk.project(res.project.id), res.project)
      void qc.invalidateQueries({ queryKey: dk.projects })
    },
    onError: onError('Could not start the dub'),
  })
}

export function usePatchDubProject(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (patch: DubProjectPatch) => api.patch<DubProject>(path(id), patch),
    onSuccess: (p) => qc.setQueryData(dk.project(id), p),
    onError: onError('Could not save'),
  })
}

export function useDeleteDubProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.del(path(id)),
    onSuccess: () => void qc.invalidateQueries({ queryKey: dk.projects }),
    onError: onError('Could not delete the project'),
  })
}

type RunKind = 'transcribe' | 'translate' | 'generate'

export function useRunDub(id: string, kind: RunKind) {
  return useMutation({
    mutationFn: (req: DubRunRequest) => api.post<Job>(`${path(id)}/${kind}`, req),
    onSuccess: upsertJob,
    onError: onError(`Could not ${kind}`),
  })
}

export function useVerifyDub(id: string) {
  return useMutation({
    mutationFn: (lang: string) => api.post<Job>(`${path(id)}/qc/${encodeURIComponent(lang)}`),
    onSuccess: upsertJob,
    onError: onError('Could not verify'),
  })
}

export function useExportDub(id: string) {
  return useMutation({
    mutationFn: (req: DubExportRequest) => api.post<Job>(`${path(id)}/export`, req),
    onSuccess: upsertJob,
    onError: onError('Could not export'),
  })
}

export function useDeleteExport(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (exportId: string) => api.del(`${path(id)}/exports/${exportId}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: dk.project(id) }),
  })
}

export function usePreviewLine(id: string) {
  return useMutation({
    mutationFn: (v: { segment_id: string; lang: string }) => api.post<DubPreviewResponse>(`${path(id)}/preview`, v),
    onError: onError('Preview failed'),
  })
}

export function useCleanupSegments(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<DubProject>(`${path(id)}/cleanup`),
    onSuccess: (p) => qc.setQueryData(dk.project(id), p),
    onError: onError('Clean-up failed'),
  })
}

export function useImportSubtitles(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ file, lang }: { file: File; lang?: string }) => {
      const form = new FormData()
      form.append('file', file, file.name)
      if (lang) form.append('lang', lang)
      return api.upload<DubProject>(`${path(id)}/import-subtitles`, form)
    },
    onSuccess: (p) => {
      qc.setQueryData(dk.project(id), p)
      toast.success('Subtitles imported', `${p.segments.length} segments`)
    },
    onError: onError('Could not import subtitles'),
  })
}

export const parseSubtitles = (text: string) => api.post<DubParsedSubtitles>('/dub/parse-subtitles', { text } satisfies DubParseSubtitlesRequest)

export function useGlossaryMutations(id: string) {
  const qc = useQueryClient()
  const refresh = () => void qc.invalidateQueries({ queryKey: dk.glossary(id) })
  return {
    add: useMutation({
      mutationFn: (t: DubGlossaryInput) => api.post<DubGlossaryTerm>(`${path(id)}/glossary`, t),
      onSuccess: refresh,
      onError: onError('Could not add term'),
    }),
    update: useMutation({
      mutationFn: ({ termId, ...t }: DubGlossaryInput & { termId: string }) =>
        api.put<DubGlossaryTerm>(`${path(id)}/glossary/${termId}`, t),
      onSuccess: refresh,
      onError: onError('Could not update term'),
    }),
    remove: useMutation({
      mutationFn: (termId: string) => api.del(`${path(id)}/glossary/${termId}`),
      onSuccess: refresh,
    }),
    auto: useMutation({
      mutationFn: (lang: string) => api.post<DubGlossaryTerm[]>(`${path(id)}/glossary/auto`, { lang } satisfies DubAutoGlossaryRequest),
      onSuccess: (terms) => {
        qc.setQueryData(dk.glossary(id), terms)
        toast.success('Terminology proposed', `${terms.filter((t) => t.auto).length} automatic terms`)
      },
      onError: onError('Auto-extract failed'),
    }),
  }
}
