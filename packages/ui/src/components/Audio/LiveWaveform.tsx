import { useEffect, useRef } from 'react'
import { cn } from '../../lib/cn'
import s from './Audio.module.css'

export interface LiveWaveformProps {
  /** Live input stream (e.g. from getUserMedia); null renders an idle ripple. */
  stream: MediaStream | null
  color?: string
  height?: number
  className?: string
}

/** Real-time mirrored frequency bars for mic input. */
export function LiveWaveform({ stream, color = 'var(--hue-voice)', height = 64, className }: LiveWaveformProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx2d = canvas.getContext('2d')!
    let raf = 0
    let audioCtx: AudioContext | null = null
    let analyser: AnalyserNode | null = null
    let data: Uint8Array<ArrayBuffer> | null = null

    if (stream) {
      audioCtx = new AudioContext()
      analyser = audioCtx.createAnalyser()
      analyser.fftSize = 256
      analyser.smoothingTimeConstant = 0.75
      audioCtx.createMediaStreamSource(stream).connect(analyser)
      data = new Uint8Array(analyser.frequencyBinCount)
    }

    const render = () => {
      const dpr = window.devicePixelRatio || 1
      const w = canvas.clientWidth
      const h = height
      if (canvas.width !== w * dpr) canvas.width = w * dpr
      if (canvas.height !== h * dpr) canvas.height = h * dpr
      ctx2d.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx2d.clearRect(0, 0, w, h)
      ctx2d.fillStyle = getComputedStyle(canvas).color
      const bars = Math.floor(w / 5)
      if (analyser && data) analyser.getByteFrequencyData(data)
      for (let i = 0; i < bars; i++) {
        // Mirror around the center so low frequencies sit in the middle
        const center = Math.abs(i - bars / 2) / (bars / 2)
        const bin = data ? data[Math.floor(center * data.length * 0.7)] / 255 : 0
        const idle = 0.04 + 0.03 * Math.sin(i * 0.4 + performance.now() / 400)
        const v = Math.max(idle, bin)
        const bh = Math.max(2, v * (h - 6))
        ctx2d.globalAlpha = 0.35 + v * 0.65
        ctx2d.beginPath()
        ctx2d.roundRect(i * 5, (h - bh) / 2, 3, bh, 1.5)
        ctx2d.fill()
      }
      ctx2d.globalAlpha = 1
      raf = requestAnimationFrame(render)
    }
    raf = requestAnimationFrame(render)
    return () => {
      cancelAnimationFrame(raf)
      void audioCtx?.close()
    }
  }, [stream, height])

  return <canvas ref={canvasRef} className={cn(s.live, className)} style={{ height, color }} />
}
