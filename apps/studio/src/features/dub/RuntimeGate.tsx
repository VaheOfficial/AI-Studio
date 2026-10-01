import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Download, Wrench } from 'lucide-react'
import { Button, Progress } from '@studio/ui'
import { useInstallRuntime } from '../../api/hooks'
import { useLive } from '../../api/live'
import { dk, useDubStatus, useInstallMediaTools } from './api'
import s from './RuntimeGate.module.css'

/**
 * What dubbing, audiobooks and audio tools need before they can run: ffmpeg (system or the pinned static build)
 * and — for separation, recognition, diarization and NLLB — the `dub` runtime environment.
 */
export function RuntimeGate({ needsEnv = true }: { needsEnv?: boolean }) {
  const { data: status } = useDubStatus()
  const runtime = useLive((st) => st.runtimes.find((r) => r.id === 'dub'))
  const envJob = useLive((st) => st.jobs.find((j) => j.kind === 'env' && j.ref === 'dub' && (j.status === 'running' || j.status === 'queued')))
  const mediaJob = useLive((st) => st.jobs.find((j) => j.ref === 'media-tools'))
  const installEnv = useInstallRuntime()
  const installMedia = useInstallMediaTools()
  const qc = useQueryClient()
  const mediaStatus = mediaJob?.status
  useEffect(() => {
    if (mediaStatus === 'done') void qc.invalidateQueries({ queryKey: dk.status })
  }, [mediaStatus, qc])
  const missingMedia = status && !status.media.ready
  const missingEnv = needsEnv && runtime && !runtime.env_ready
  if (!missingMedia && !missingEnv) return null
  return (
    <div className={s.gate}>
      {missingMedia && (
        <div className={s.row}>
          <Wrench className={s.icon} />
          <div className={s.text}>
            <strong>ffmpeg is missing</strong>
            <span>Every audio feature needs ffmpeg + ffprobe. Install the pinned, checksum-verified build (~72 MB).</span>
            {mediaJob?.status === 'running' && <Progress value={mediaJob.progress} size="xs" />}
          </div>
          <Button size="sm" variant="primary" loading={installMedia.isPending || mediaJob?.status === 'running'} onClick={() => installMedia.mutate()}>
            Install ffmpeg
          </Button>
        </div>
      )}
      {missingEnv && (
        <div className={s.row}>
          <Download className={s.icon} />
          <div className={s.text}>
            <strong>Dubbing runtime not installed</strong>
            <span>
              Demucs (voice/background separation), faster-whisper, pyannote diarization and NLLB run in their own Python
              environment (~4 GB download).
            </span>
            {envJob && (
              <>
                <Progress value={envJob.progress} size="xs" />
                <span className={s.message}>{envJob.message}</span>
              </>
            )}
          </div>
          <Button size="sm" variant="primary" loading={installEnv.isPending || !!envJob} onClick={() => installEnv.mutate('dub')}>
            Install
          </Button>
        </div>
      )}
    </div>
  )
}
