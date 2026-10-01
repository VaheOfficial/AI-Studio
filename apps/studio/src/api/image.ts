/**
 * Image area client: model profiles, generation, gallery stars (React Query) and the live denoising previews
 * pushed as `image.preview` frames (`dispatchImagePreview`, called from the socket dispatcher in live.ts).
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from '@studio/ui'
import { create } from 'zustand'
import { api } from './client'
import type { ImageGenerateRequest, ImageModelProfile, ImageServerEvent } from './contracts/image'
import { useLive } from './live'
import type { Job, Output } from './types'

export const ik = {
  profiles: (ids: string) => ['image-models', ids] as const,
  stars: ['image-stars'] as const,
  /** Starts with `['outputs', 'image']`, so pushed outputs and deletions reach it like the other output lists. */
  gallery: ['outputs', 'image', 'gallery'] as const,
}

/** Capabilities + defaults of every installed image model; refetched whenever that set changes. */
export function useImageProfiles() {
  const ids = useLive((s) =>
    s.models
      .filter((m) => m.kind === 'image')
      .map((m) => m.id)
      .sort()
      .join(','),
  )
  return useQuery({ queryKey: ik.profiles(ids), queryFn: () => api.get<ImageModelProfile[]>('/image/models') })
}

export function useGenerateImage() {
  return useMutation({
    mutationFn: (body: ImageGenerateRequest) => api.post<Job>('/image/generate', body),
    onSuccess: (job) => useLive.getState().upsertJob(job),
    onError: (e: Error) => toast.error('Image generation failed', e.message),
  })
}

/** Every image output (newest first) for the gallery. */
export const useGallery = () =>
  useQuery({ queryKey: ik.gallery, queryFn: () => api.get<Output[]>('/outputs?kind=image&limit=1000') })

export const useStars = () => useQuery({ queryKey: ik.stars, queryFn: () => api.get<string[]>('/image/stars') })

export function useToggleStar() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, starred }: { id: string; starred: boolean }) => api.put<void>(`/image/stars/${id}`, { starred }),
    onMutate: ({ id, starred }) =>
      qc.setQueryData<string[]>(ik.stars, (old = []) => (starred ? [id, ...old.filter((x) => x !== id)] : old.filter((x) => x !== id))),
    onError: (e: Error) => {
      toast.error('Could not update star', e.message)
      void qc.invalidateQueries({ queryKey: ik.stars })
    },
  })
}

/* ------------------------------ live previews ------------------------------ */

type Preview = Omit<ImageServerEvent, 'type' | 'job_id'>

const MAX_PREVIEWS = 8

export const useImagePreviews = create<{ byJob: Record<string, Preview> }>(() => ({ byJob: {} }))

export function dispatchImagePreview(ev: ImageServerEvent) {
  useImagePreviews.setState((s) => {
    const entries = Object.entries(s.byJob).filter(([id]) => id !== ev.job_id).slice(-(MAX_PREVIEWS - 1))
    return { byJob: { ...Object.fromEntries(entries), [ev.job_id]: { step: ev.step, total: ev.total, image: ev.image } } }
  })
}

export const useImagePreview = (jobId: string | undefined) => useImagePreviews((s) => (jobId ? s.byJob[jobId] : undefined))
