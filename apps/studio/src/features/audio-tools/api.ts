/** Audio tools client: stem isolation and voice conversion return Jobs whose outputs are audio `Output`s. */
import { useMutation } from '@tanstack/react-query'
import { toast } from '@studio/ui'
import { api } from '../../api/client'
import { useLive } from '../../api/live'
import type { Job } from '../../api/types'

export type IsolateMode = 'vocals' | 'stems4' | 'stems4_ft' | 'stems6'

const submitted = (job: Job) => useLive.getState().upsertJob(job)

export function useIsolate() {
  return useMutation({
    mutationFn: ({ file, mode }: { file: File; mode: IsolateMode }) => {
      const form = new FormData()
      form.append('file', file, file.name)
      form.append('mode', mode)
      return api.upload<Job>('/audio-tools/isolate', form)
    },
    onSuccess: submitted,
    onError: (e: Error) => toast.error('Could not separate', e.message),
  })
}

export function useConvertVoice() {
  return useMutation({
    mutationFn: (v: { file: Blob; voiceId: string; sttModelId: string; ttsModelId?: string; language?: string; matchDuration: boolean }) => {
      const form = new FormData()
      form.append('file', v.file, v.file instanceof File ? v.file.name : 'recording.webm')
      form.append('voice_id', v.voiceId)
      form.append('stt_model_id', v.sttModelId)
      if (v.ttsModelId) form.append('tts_model_id', v.ttsModelId)
      if (v.language) form.append('language', v.language)
      form.append('match_duration', String(v.matchDuration))
      return api.upload<Job>('/audio-tools/convert', form)
    },
    onSuccess: submitted,
    onError: (e: Error) => toast.error('Could not convert', e.message),
  })
}
