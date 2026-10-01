import { useMutation, useQuery } from '@tanstack/react-query'
import { toast } from '@studio/ui'
import { api } from './client'
import type { VideoModelProfile, VideoRequest } from './contracts/video'
import { useLive } from './live'
import type { Job } from './types'

export const videoKeys = { profiles: ['video', 'profiles'] as const }

/** What each installed video model can do (sizes, clip lengths, audio, adjustable settings). */
export const useVideoProfiles = () =>
  useQuery({ queryKey: videoKeys.profiles, queryFn: () => api.get<VideoModelProfile[]>('/video/models') })

/** Start a video job; progress and the finished clip arrive over the socket like any other job. */
export function useGenerateVideo() {
  return useMutation({
    mutationFn: (req: VideoRequest) => api.post<Job>('/video/generate', req),
    onSuccess: (job) => useLive.getState().upsertJob(job),
    onError: (e: Error) => toast.error('Video generation failed', e.message),
  })
}
