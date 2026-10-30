import { useCallback, useEffect, useRef, useState } from 'react'
import type { DictationEvent } from '../../api/contracts/voice'

export type DictationStage = 'idle' | 'connecting' | 'loading' | 'listening' | 'finishing'

const SAMPLE_RATE = 16000
const FRAME = SAMPLE_RATE / 10 // send ~100 ms of audio per WebSocket frame

// AudioWorklet that forwards each 128-sample block of the (16 kHz) input to the main thread.
const TAP = `class PcmTap extends AudioWorkletProcessor {
  process(inputs) { const ch = inputs[0][0]; if (ch) this.port.postMessage(ch.slice(0)); return true }
}
registerProcessor('pcm-tap', PcmTap)`

interface Session {
  ws: WebSocket
  media: MediaStream
  ctx: AudioContext
}

/** Live dictation: streams 16 kHz PCM16 from the microphone to `/api/voice/dictate` and collects the text. */
export function useDictation(modelId: string | undefined, language?: string, options?: { paused?: boolean; onSpeech?: (text: string) => void }) {
  const [stage, setStage] = useState<DictationStage>('idle')
  const [finals, setFinals] = useState<string[]>([])
  const [partial, setPartial] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [stream, setStream] = useState<MediaStream | null>(null)
  const session = useRef<Session | null>(null)
  const generation = useRef(0)
  const starting = useRef(false)
  const paused = useRef(false)
  const onSpeech = useRef(options?.onSpeech)
  useEffect(() => { paused.current = options?.paused ?? false }, [options?.paused])
  useEffect(() => { onSpeech.current = options?.onSpeech }, [options?.onSpeech])

  const release = useCallback(() => {
    generation.current++
    starting.current = false
    const s = session.current
    session.current = null
    if (!s) return
    s.media.getTracks().forEach((t) => t.stop())
    void s.ctx.close()
    if (s.ws.readyState === WebSocket.OPEN || s.ws.readyState === WebSocket.CONNECTING) s.ws.close()
    setStream(null)
    setStage('idle')
  }, [])

  useEffect(() => release, [release])

  const start = useCallback(async () => {
    if (session.current || starting.current || !modelId) return
    starting.current = true
    const ticket = ++generation.current
    setError(null)
    setFinals([])
    setPartial('')
    setStage('connecting')
    let media: MediaStream
    try {
      media = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } })
    } catch (e) {
      setError((e as Error).name === 'NotAllowedError' ? 'Microphone permission was denied.' : (e as Error).message)
      setStage('idle')
      starting.current = false
      return
    }
    if (ticket !== generation.current) { media.getTracks().forEach(t => t.stop()); return }
    const query = new URLSearchParams({ model_id: modelId, ...(language ? { language } : {}) })
    const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/voice/dictate?${query}`)
    const ctx = new AudioContext({ sampleRate: SAMPLE_RATE })
    session.current = { ws, media, ctx }
    starting.current = false
    setStream(media)

    ws.onmessage = (msg) => {
      if (session.current?.ws !== ws) return
      const ev = JSON.parse(String(msg.data)) as DictationEvent
      if (ev.type === 'status') setStage((s) => (s === 'finishing' ? s : ev.stage === 'loading' ? 'loading' : 'listening'))
      else if (ev.type === 'partial') { setPartial(ev.text); if (ev.text.trim()) onSpeech.current?.(ev.text) }
      else if (ev.type === 'error') setError(ev.message)
      else if (ev.final_kind === 'utterance') {
        if (ev.text.trim()) onSpeech.current?.(ev.text)
        setFinals((f) => [...f, ev.text])
        setPartial('')
      } else release()
    }
    ws.onclose = () => { if (session.current?.ws === ws) release() }
    ws.onerror = () => setError('The dictation connection failed.')

    const url = URL.createObjectURL(new Blob([TAP], { type: 'text/javascript' }))
    try { await ctx.audioWorklet.addModule(url) }
    catch (e) { if (ticket === generation.current) { setError((e as Error).message); release() }; return }
    finally { URL.revokeObjectURL(url) }
    if (ticket !== generation.current) return
    const node = new AudioWorkletNode(ctx, 'pcm-tap')
    let pending: Float32Array[] = []
    let count = 0
    node.port.onmessage = (e: MessageEvent<Float32Array>) => {
      if (session.current?.ws !== ws) return
      pending.push(paused.current ? new Float32Array(e.data.length) : e.data)
      count += e.data.length
      if (count < FRAME) return
      const pcm = new Int16Array(count)
      let offset = 0
      for (const block of pending) {
        for (let i = 0; i < block.length; i++) pcm[offset++] = Math.max(-1, Math.min(1, block[i])) * 0x7fff
      }
      pending = []
      count = 0
      if (ws.readyState === WebSocket.OPEN && ws.bufferedAmount < SAMPLE_RATE * 4) ws.send(pcm.buffer)
    }
    ctx.createMediaStreamSource(media).connect(node)
    node.connect(ctx.destination) // pulls the graph; the tap writes no output, so this stays silent
  }, [modelId, language, release])

  /** Stop listening; the server sends the last utterance and a summary, then closes. */
  const stop = useCallback(() => {
    const s = session.current
    if (!s) return
    s.media.getTracks().forEach((t) => t.stop())
    void s.ctx.suspend()
    setStream(null)
    setStage('finishing')
    if (s.ws.readyState === WebSocket.OPEN) s.ws.send('EOF')
    else release()
  }, [release])

  return { stage, finals, partial, error, stream, start, stop, cancel: release }
}
