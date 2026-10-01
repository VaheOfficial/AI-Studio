import { useCallback, useEffect, useRef, useState } from 'react'
import { Download, Pause, Play } from 'lucide-react'
import { cn } from '../../lib/cn'
import s from './Audio.module.css'

const peakCache = new Map<string, Promise<Float32Array>>()

/** Decode audio once per URL and reduce it to `bars` normalized peak values. */
function loadPeaks(url: string, bars: number): Promise<Float32Array> {
  const key = `${url}#${bars}`
  let p = peakCache.get(key)
  if (!p) {
    p = fetch(url)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.arrayBuffer()
      })
      .then(async (buf) => {
        const ctx = new OfflineAudioContext(1, 1, 44100)
        const audio = await ctx.decodeAudioData(buf)
        const data = audio.getChannelData(0)
        const step = Math.max(1, Math.floor(data.length / bars))
        const peaks = new Float32Array(bars)
        let max = 0
        for (let i = 0; i < bars; i++) {
          let sum = 0
          const start = i * step
          for (let j = 0; j < step; j++) sum += Math.abs(data[start + j] ?? 0)
          peaks[i] = sum / step
          max = Math.max(max, peaks[i])
        }
        for (let i = 0; i < bars; i++) peaks[i] = max ? Math.pow(peaks[i] / max, 0.8) : 0
        return peaks
      })
    p.catch(() => peakCache.delete(key))
    peakCache.set(key, p)
  }
  return p
}

function fmt(t: number) {
  if (!isFinite(t)) return '0:00'
  const m = Math.floor(t / 60)
  const sec = Math.floor(t % 60)
  return `${m}:${sec.toString().padStart(2, '0')}`
}

export interface AudioPlayerProps {
  src: string
  /** Waveform color, e.g. "var(--hue-voice)". */
  color?: string
  bars?: number
  height?: number
  compact?: boolean
  autoPlay?: boolean
  downloadName?: string
  className?: string
}

/** Audio player with a canvas waveform you can click/drag to seek. */
export function AudioPlayer({
  src,
  color = 'var(--accent)',
  bars = 96,
  height = 44,
  compact,
  autoPlay,
  downloadName,
  className,
}: AudioPlayerProps) {
  const audioRef = useRef<HTMLAudioElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const wrapRef = useRef<HTMLDivElement>(null)
  const [peaks, setPeaks] = useState<Float32Array | null>(null)
  const [playing, setPlaying] = useState(false)
  const [time, setTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [hover, setHover] = useState<number | null>(null)

  useEffect(() => {
    let alive = true
    setPeaks(null)
    loadPeaks(src, bars)
      .then((p) => alive && setPeaks(p))
      .catch(() => alive && setPeaks(new Float32Array(bars).fill(0.08)))
    return () => {
      alive = false
    }
  }, [src, bars])

  const draw = useCallback(() => {
    const canvas = canvasRef.current
    const wrap = wrapRef.current
    if (!canvas || !wrap) return
    const dpr = window.devicePixelRatio || 1
    const w = wrap.clientWidth
    const h = height
    if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
      canvas.width = w * dpr
      canvas.height = h * dpr
    }
    const ctx = canvas.getContext('2d')!
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, w, h)
    const styles = getComputedStyle(wrap)
    const played = styles.color
    const dim = styles.getPropertyValue('--text-4').trim() || '#444'
    const n = peaks?.length ?? bars
    const gap = 2
    const bw = Math.max(1, (w - gap * (n - 1)) / n)
    const progress = duration ? time / duration : 0
    for (let i = 0; i < n; i++) {
      const v = peaks ? peaks[i] : 0.12 + 0.1 * Math.sin(i * 0.5 + performance.now() / 200)
      const bh = Math.max(2, v * (h - 4))
      const frac = i / n
      ctx.globalAlpha = frac <= progress ? 1 : hover != null && frac <= hover ? 0.55 : 1
      ctx.fillStyle = frac <= progress || (hover != null && frac <= hover) ? played : dim
      ctx.beginPath()
      ctx.roundRect(i * (bw + gap), (h - bh) / 2, bw, bh, Math.min(bw / 2, 2))
      ctx.fill()
    }
    ctx.globalAlpha = 1
  }, [peaks, bars, height, time, duration, hover])

  useEffect(() => {
    draw()
    if (peaks) return
    // Idle shimmer while decoding
    let raf = 0
    const loop = () => {
      draw()
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [draw, peaks])

  useEffect(() => {
    const ro = new ResizeObserver(draw)
    if (wrapRef.current) ro.observe(wrapRef.current)
    return () => ro.disconnect()
  }, [draw])

  // Smooth playhead while playing (timeupdate only fires ~4×/s)
  useEffect(() => {
    if (!playing) return
    let raf = 0
    const tick = () => {
      setTime(audioRef.current?.currentTime ?? 0)
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [playing])

  const seekFromEvent = (clientX: number) => {
    const el = wrapRef.current
    const a = audioRef.current
    if (!el || !a || !duration) return
    const r = el.getBoundingClientRect()
    a.currentTime = Math.min(1, Math.max(0, (clientX - r.left) / r.width)) * duration
    setTime(a.currentTime)
  }

  const toggle = () => {
    const a = audioRef.current
    if (!a) return
    if (a.paused) void a.play()
    else a.pause()
  }

  return (
    <div className={cn(s.player, compact && s.compact, className)} style={{ ['--wave-color' as string]: color }}>
      <audio
        ref={audioRef}
        src={src}
        preload="metadata"
        autoPlay={autoPlay}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => {
          setPlaying(false)
          setTime(0)
        }}
        onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
        onTimeUpdate={(e) => !playing && setTime(e.currentTarget.currentTime)}
      />
      <button className={s.play} onClick={toggle} aria-label={playing ? 'Pause' : 'Play'}>
        {playing ? <Pause size={15} fill="currentColor" /> : <Play size={15} fill="currentColor" className={s.playIcon} />}
      </button>
      <div
        ref={wrapRef}
        className={s.wave}
        style={{ height }}
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture(e.pointerId)
          seekFromEvent(e.clientX)
        }}
        onPointerMove={(e) => {
          const r = e.currentTarget.getBoundingClientRect()
          setHover((e.clientX - r.left) / r.width)
          if (e.buttons === 1) seekFromEvent(e.clientX)
        }}
        onPointerLeave={() => setHover(null)}
      >
        <canvas ref={canvasRef} style={{ width: '100%', height }} />
      </div>
      <span className={s.time}>
        {fmt(time)}
        {!compact && <span className={s.total}> / {fmt(duration)}</span>}
      </span>
      {downloadName && (
        <a className={s.download} href={src} download={downloadName} aria-label="Download">
          <Download size={15} />
        </a>
      )}
    </div>
  )
}
