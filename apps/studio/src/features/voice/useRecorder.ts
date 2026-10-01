import { useCallback, useEffect, useRef, useState } from 'react'

export interface Recorder {
  recording: boolean
  stream: MediaStream | null
  elapsed: number // seconds
  blob: Blob | null
  error: string | null
  start: () => Promise<void>
  stop: () => void
  reset: () => void
}

/** Microphone capture via MediaRecorder; exposes the live stream for visualisation. `onRecorded` receives each
 * finished recording. */
export function useRecorder(onRecorded?: (blob: Blob) => void): Recorder {
  const [recording, setRecording] = useState(false)
  const [stream, setStream] = useState<MediaStream | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const [blob, setBlob] = useState<Blob | null>(null)
  const [error, setError] = useState<string | null>(null)
  const rec = useRef<MediaRecorder | null>(null)
  const onDone = useRef(onRecorded)
  useEffect(() => {
    onDone.current = onRecorded
  })
  const timer = useRef<ReturnType<typeof setInterval> | undefined>(undefined)

  const cleanup = useCallback(() => {
    clearInterval(timer.current)
    stream?.getTracks().forEach((t) => t.stop())
    setStream(null)
  }, [stream])

  useEffect(() => () => cleanup(), [cleanup])

  const start = useCallback(async () => {
    setError(null)
    setBlob(null)
    try {
      const media = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } })
      const chunks: Blob[] = []
      const mr = new MediaRecorder(media)
      mr.ondataavailable = (e) => e.data.size && chunks.push(e.data)
      mr.onstop = () => {
        const recorded = new Blob(chunks, { type: mr.mimeType })
        setBlob(recorded)
        onDone.current?.(recorded)
        media.getTracks().forEach((t) => t.stop())
        setStream(null)
      }
      rec.current = mr
      mr.start(250)
      setStream(media)
      setRecording(true)
      const t0 = performance.now()
      setElapsed(0)
      timer.current = setInterval(() => setElapsed((performance.now() - t0) / 1000), 100)
    } catch (e) {
      setError((e as Error).name === 'NotAllowedError' ? 'Microphone permission was denied.' : (e as Error).message)
    }
  }, [])

  const stop = useCallback(() => {
    clearInterval(timer.current)
    rec.current?.stop()
    setRecording(false)
  }, [])

  const reset = useCallback(() => {
    setBlob(null)
    setElapsed(0)
  }, [])

  return { recording, stream, elapsed, blob, error, start, stop, reset }
}
