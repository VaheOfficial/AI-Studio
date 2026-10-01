/**
 * Voice area client: profiles, reference clips, speech + takes, languages, voice design, archetype gallery and
 * the pronunciation dictionary (React Query). Speech jobs report through the socket like every other job.
 */
import { useEffect, useMemo, useRef } from 'react'
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from '@studio/ui'
import { api } from './client'
import type {
  ArchetypeFilters,
  ArchetypePage,
  ArchetypePreview,
  ArchetypeUse,
  DescribeResult,
  DesignVocabulary,
  LanguageCatalog,
  ProfileCreate,
  ProfileUpdate,
  PronunciationEntry,
  PronunciationInput,
  PronunciationTestResult,
  SpeakRequest,
  StagedReference,
  VoiceProfile,
  VoiceTake,
} from './contracts/voice'
import { qk } from './keys'
import { useJob, useLive } from './live'
import type { Job } from './types'

export const vk = {
  profiles: (models: string) => [...qk.voiceProfiles, models] as const,
  takes: ['voice', 'takes'] as const,
  languages: ['voice', 'languages'] as const,
  design: ['voice', 'design'] as const,
  archetypes: (filters: ArchetypeFilters) => ['voice', 'archetypes', filters] as const,
  pronunciation: ['voice', 'pronunciation'] as const,
}

const onError = (title: string) => (e: Error) => toast.error(title, e.message)
const upsertJob = (job: Job) => useLive.getState().upsertJob(job)

/** Runs `onDone` once when the job reaches `done` (e.g. to refresh data the job produced). */
export function useOnJobDone(jobId: string | undefined, onDone: (job: Job) => void) {
  const job = useJob(jobId)
  const fired = useRef<string | undefined>(undefined)
  const callback = useRef(onDone)
  useEffect(() => {
    callback.current = onDone
  })
  useEffect(() => {
    if (job?.status === 'done' && fired.current !== job.id) {
      fired.current = job.id
      callback.current(job)
    }
  }, [job])
  return job
}

/* ------------------------------ languages ------------------------------ */

export const useLanguages = () =>
  useQuery({ queryKey: vk.languages, queryFn: () => api.get<LanguageCatalog>('/voice/languages'), staleTime: Infinity })

/** Display name of a language id ("Auto" when absent, the id itself while loading). */
export function useLanguageName() {
  const { data } = useLanguages()
  return useMemo(() => {
    const names = new Map(data?.languages.map((l) => [l.id, l.name]))
    return (id: string | undefined) => (id ? (names.get(id) ?? id) : 'Auto')
  }, [data])
}

/* ------------------------------- profiles ------------------------------- */

/** Every voice (stored profiles first, then the presets of installed models); refetched when voice models change. */
export function useVoiceProfiles() {
  const models = useLive((s) =>
    s.models
      .filter((m) => m.kind === 'voice')
      .map((m) => m.id)
      .sort()
      .join(','),
  )
  return useQuery({ queryKey: vk.profiles(models), queryFn: () => api.get<VoiceProfile[]>('/voice/profiles') })
}

function useProfileMutation<V>(fn: (vars: V) => Promise<VoiceProfile>, title: string, success?: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: (p) => {
      void qc.invalidateQueries({ queryKey: qk.voiceProfiles })
      void qc.invalidateQueries({ queryKey: ['voice', 'archetypes'] })
      if (success) toast.success(success, p.name)
    },
    onError: onError(title),
  })
}

export const useCreateProfile = () =>
  useProfileMutation((body: ProfileCreate) => api.post<VoiceProfile>('/voice/profiles', body), 'Could not save voice', 'Voice saved')

export const useUpdateProfile = () =>
  useProfileMutation(
    ({ id, ...patch }: ProfileUpdate & { id: string }) => api.patch<VoiceProfile>(`/voice/profiles/${encodeURIComponent(id)}`, patch),
    'Could not update voice',
  )

export const useUnlockProfile = () =>
  useProfileMutation((id: string) => api.post<VoiceProfile>(`/voice/profiles/${encodeURIComponent(id)}/unlock`), 'Could not unlock', 'Unlocked')

export function useDeleteProfile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.del(`/voice/profiles/${encodeURIComponent(id)}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.voiceProfiles })
      void qc.invalidateQueries({ queryKey: ['voice', 'archetypes'] })
    },
    onError: onError('Could not delete voice'),
  })
}

/** Upload a reference clip: normalised, trimmed to the best ~15 s and auto-transcribed server-side. */
export function useStageReference() {
  return useMutation({
    mutationFn: ({ file, language }: { file: Blob; language?: string }) => {
      const form = new FormData()
      form.append('file', file, file instanceof File ? file.name : 'reference.webm')
      if (language) form.append('language', language)
      return api.upload<StagedReference>('/voice/references', form)
    },
    onError: onError('Could not use this clip'),
  })
}

export function useRetranscribe() {
  return useMutation({
    mutationFn: (id: string) => api.post<StagedReference>(`/voice/references/${id}/transcribe`),
    onError: onError('Transcription failed'),
  })
}

/* -------------------------------- speech -------------------------------- */

export function useSpeak() {
  return useMutation({
    mutationFn: (body: SpeakRequest) => api.post<Job>('/voice/tts', body),
    onSuccess: upsertJob,
    onError: onError('Speech generation failed'),
  })
}

export const useTakes = () => useQuery({ queryKey: vk.takes, queryFn: () => api.get<VoiceTake[]>('/voice/takes?limit=200') })

export function useStarTake() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, starred }: { id: string; starred: boolean }) => api.patch<VoiceTake>(`/voice/takes/${id}`, { starred }),
    onMutate: ({ id, starred }) => qc.setQueryData<VoiceTake[]>(vk.takes, (old) => old?.map((t) => (t.id === id ? { ...t, starred } : t))),
    onError: (e: Error) => {
      toast.error('Could not update take', e.message)
      void qc.invalidateQueries({ queryKey: vk.takes })
    },
  })
}

export function useDeleteTake() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.del(`/voice/takes/${id}`),
    onMutate: (id) => {
      qc.setQueryData<VoiceTake[]>(vk.takes, (old) => old?.filter((t) => t.id !== id))
      qc.setQueriesData<{ id: string }[]>({ queryKey: ['outputs'] }, (old) => old?.filter((o) => o.id !== id))
    },
    onError: onError('Could not delete take'),
  })
}

export const useLockTake = () =>
  useProfileMutation(
    ({ id, profileId }: { id: string; profileId?: string }) => api.post<VoiceProfile>(`/voice/takes/${id}/lock`, { profile_id: profileId }),
    'Could not lock take',
    'Voice locked to this take',
  )

/* -------------------------------- design -------------------------------- */

export const useDesignVocabulary = () =>
  useQuery({ queryKey: vk.design, queryFn: () => api.get<DesignVocabulary>('/voice/design'), staleTime: Infinity })

/** Deterministic description -> design tags mapping. */
export const useDescribeVoice = () =>
  useMutation({ mutationFn: (description: string) => api.post<DescribeResult>('/voice/design/describe', { description }) })

const PAGE = 60

export function useArchetypes(filters: ArchetypeFilters) {
  return useInfiniteQuery({
    queryKey: vk.archetypes(filters),
    initialPageParam: 0,
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams({ offset: String(pageParam), limit: String(PAGE) })
      for (const [k, v] of Object.entries(filters)) if (v !== undefined && v !== '') params.set(k, String(v))
      return api.get<ArchetypePage>(`/voice/archetypes?${params}`)
    },
    getNextPageParam: (last) => (last.offset + last.items.length < last.total ? last.offset + last.items.length : undefined),
  })
}

export function usePreviewArchetype() {
  return useMutation({
    mutationFn: (id: string) => api.post<ArchetypePreview>(`/voice/archetypes/${encodeURIComponent(id)}/preview`),
    onSuccess: (r) => r.job && upsertJob(r.job),
    onError: onError('Could not render the preview'),
  })
}

export function useAdoptArchetype() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.post<ArchetypeUse>(`/voice/archetypes/${encodeURIComponent(id)}/use`),
    onSuccess: (r) => {
      if (r.job) upsertJob(r.job)
      if (r.profile) {
        toast.success('Added to your voices', r.profile.name)
        void qc.invalidateQueries({ queryKey: qk.voiceProfiles })
        void qc.invalidateQueries({ queryKey: ['voice', 'archetypes'] })
      }
    },
    onError: onError('Could not add this voice'),
  })
}

/* ----------------------------- pronunciation ----------------------------- */

export const usePronunciation = () =>
  useQuery({ queryKey: vk.pronunciation, queryFn: () => api.get<PronunciationEntry[]>('/voice/pronunciation') })

function usePronunciationMutation<V>(fn: (vars: V) => Promise<unknown>, title: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => void qc.invalidateQueries({ queryKey: vk.pronunciation }),
    onError: onError(title),
  })
}

export const useCreatePronunciation = () =>
  usePronunciationMutation((body: PronunciationInput) => api.post<PronunciationEntry>('/voice/pronunciation', body), 'Could not add entry')

export const useUpdatePronunciation = () =>
  usePronunciationMutation(
    ({ id, ...patch }: Partial<PronunciationInput> & { id: string }) => api.patch<PronunciationEntry>(`/voice/pronunciation/${id}`, patch),
    'Could not update entry',
  )

export const useDeletePronunciation = () =>
  usePronunciationMutation((id: string) => api.del(`/voice/pronunciation/${id}`), 'Could not delete entry')

export function useTestPronunciation() {
  return useMutation({
    mutationFn: (body: { text: string; language?: string }) => api.post<PronunciationTestResult>('/voice/pronunciation/test', body),
    onError: onError('Test failed'),
  })
}
